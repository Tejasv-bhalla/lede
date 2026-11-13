from datetime import date

import pytest

from app.context.merge import merge_brief
from app.domain.models import (
    About,
    Campaign,
    CompanyInfo,
    Offer,
    Persona,
    ProspectInput,
    RunState,
    SellerProfile,
    Seniority,
)
from app.domain.models import SignalCategory as Cat
from app.pipeline.ports import Contact, Draft, Identity, IdentityStatus
from app.pipeline.run import PipelineDeps, run_prospect
from app.policy.draft_rules import DraftRules
from app.research.loop import ResearchDeps
from app.research.ports import Candidate, Page, PlannedQuery, SearchHit
from tests.fakes import (
    FakeEntailment,
    FakeFactChecker,
    FakeFetcher,
    FakePlanner,
    FakeReader,
    FakeReflector,
    FakeResolver,
    FakeScorer,
    FakeSearcher,
    FakeWriter,
)

TODAY = date(2026, 11, 13)
PROSPECT = ProspectInput(
    company_name="Acme", person_name="Priya Shah", company_domain="acme.example"
)
PRIYA = Contact(
    company_name="Acme", company_domain="acme.example", person_name="Priya Shah", title="VP Finance"
)
PROFILE = SellerProfile(
    company=CompanyInfo(name="Ledgerly", domain="ledgerly.example"),
    offer=Offer(product="Ledgerly", problem_solved="slow month-end close"),
    personas=[Persona(id="fin", title_patterns=["VP Finance"], seniority=Seniority.VP)],
)
BRIEF = merge_brief(PROFILE, Campaign(id="c1", name="Q4", objective="Book demos", persona_id="fin"))
RULES = DraftRules(footer=None)

# ── a small, fixed slice of the web ───────────────────────────────────────────

CAREERS = "https://acme.example/careers"
PODCAST = "https://pod.example/ep41"
PAGES = {
    CAREERS: Page(
        url=CAREERS,
        text="Join Acme. We are hiring three accounts payable specialists in London.",
        published_at=date(2026, 11, 1),
    ),
    PODCAST: Page(
        url=PODCAST,
        text="On episode 41, Priya Shah, VP Finance at Acme, said closing the books faster "
        "is her top priority for 2026.",
        published_at=date(2026, 10, 20),
    ),
}
HIRING = Candidate(
    Cat.HIRING_PATTERN,
    About.COMPANY,
    "Acme is hiring three AP specialists in London",
    "hiring three accounts payable specialists in London",
)
PODCAST_QUOTE = Candidate(
    Cat.OWN_CONTENT,
    About.PERSON,
    "Priya said closing the books faster is her top priority",
    "closing the books faster is her top priority for 2026",
)
QUERY = PlannedQuery(Cat.OWN_CONTENT, "Priya Shah Acme")

GOOD_DRAFT = Draft(
    subject="Closing the books faster",
    body="Priya, on episode 41 you said closing the books faster is your top priority for "
    "2026. Ledgerly helps finance teams shorten month-end close. Worth a short look?",
    citations=("e2",),
)


def deps(
    *,
    pages: dict[str, Page] = PAGES,
    identity: Identity | None = None,
    scores: dict[str, float | list[float]] | None = None,
    candidates: dict[str, list[Candidate]] | None = None,
    drafts: tuple[Draft, ...] = (GOOD_DRAFT,),
    unsupported_claims: tuple[str, ...] = (),
    unsupported_sentences: tuple[str, ...] = (),
) -> PipelineDeps:
    return PipelineDeps(
        research=ResearchDeps(
            searcher=FakeSearcher({QUERY.query: [SearchHit(url=u) for u in pages]}),
            fetcher=FakeFetcher(pages),
            planner=FakePlanner([QUERY]),
            reader=FakeReader(
                candidates
                if candidates is not None
                else {CAREERS: [HIRING], PODCAST: [PODCAST_QUOTE]}
            ),
            reflector=FakeReflector([]),
        ),
        resolver=FakeResolver(identity or Identity(IdentityStatus.CONFIRMED, contact=PRIYA)),
        entailment=FakeEntailment(unsupported_claims),
        scorer=FakeScorer(scores if scores is not None else {PODCAST_QUOTE.claim: 4.5}),
        writer=FakeWriter(drafts),
        fact_checker=FakeFactChecker(unsupported_sentences),
    )


async def run(d: PipelineDeps, **kwargs):
    return await run_prospect(PROSPECT, BRIEF, d, rules=RULES, today=TODAY, **kwargs)


async def test_drafts_from_the_best_verified_hook_and_marks_the_run_ready():
    d = deps(scores={PODCAST_QUOTE.claim: 4.5, HIRING.claim: 3.5})
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_READY
    assert outcome.draft == GOOD_DRAFT
    assert outcome.ranking is not None
    assert [h.evidence.claim for h in outcome.ranking.top()] == [PODCAST_QUOTE.claim, HIRING.claim]
    request = d.writer.requests[0]  # type: ignore[attr-defined]
    assert request.hook.evidence.claim == PODCAST_QUOTE.claim
    assert request.contact == PRIYA


async def test_contact_who_moved_companies_stops_before_research_and_shows_the_new_role():
    globex = Contact(company_name="Globex", person_name="Priya Shah", title="CFO")
    d = deps(identity=Identity(IdentityStatus.MOVED, contact=globex))
    outcome = await run(d)

    assert outcome.state is RunState.CONTACT_MOVED
    assert outcome.identity is not None and outcome.identity.contact == globex
    assert d.research.searcher.queries == []  # type: ignore[attr-defined]
    assert outcome.draft is None


TWO_PRIYAS = (
    PRIYA,
    Contact(
        company_name="Acme Robotics",
        company_domain="acmerobotics.example",
        person_name="Priya Shah",
    ),
)


@pytest.mark.parametrize("status", [IdentityStatus.AMBIGUOUS, IdentityStatus.SUGGESTED])
async def test_run_pauses_for_the_rep_when_the_contact_is_ambiguous_or_only_suggested(status):
    d = deps(identity=Identity(status, candidates=TWO_PRIYAS))
    outcome = await run(d)

    assert outcome.state is RunState.NEEDS_CLARIFICATION
    assert outcome.identity is not None and outcome.identity.candidates == TWO_PRIYAS
    assert d.research.searcher.queries == []  # type: ignore[attr-defined]


async def test_the_reps_pick_resumes_the_run_without_resolving_identity_again():
    d = deps(identity=Identity(IdentityStatus.AMBIGUOUS, candidates=TWO_PRIYAS))
    outcome = await run(d, pinned=PRIYA)

    assert outcome.state is RunState.DRAFT_READY
    assert d.resolver.calls == 0  # type: ignore[attr-defined]
    assert d.writer.requests[0].contact == PRIYA  # type: ignore[attr-defined]


async def test_person_not_found_falls_back_to_company_research_with_a_note():
    d = deps(
        identity=Identity(IdentityStatus.NOT_FOUND),
        scores={HIRING.claim: 4.0},
        candidates={CAREERS: [HIRING]},
    )
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_READY
    contact = d.writer.requests[0].contact  # type: ignore[attr-defined]
    assert (contact.company_name, contact.person_name) == ("Acme", None)
    assert "person_not_found" in outcome.notes


async def test_weak_signals_end_as_low_signal_without_writing_a_generic_email():
    d = deps(scores={PODCAST_QUOTE.claim: 2.0, HIRING.claim: 1.5})
    outcome = await run(d)

    assert outcome.state is RunState.LOW_SIGNAL
    assert outcome.draft is None
    assert d.writer.requests == []  # type: ignore[attr-defined]


LAYOFFS_PAGE = "https://news.example/acme-layoffs"


async def test_only_sensitive_news_sends_the_run_to_sensitive_review_without_a_draft():
    pages = {
        LAYOFFS_PAGE: Page(
            url=LAYOFFS_PAGE,
            text="Acme announced layoffs of 200 staff across its London office this week.",
        )
    }
    layoffs = Candidate(
        Cat.LAYOFFS, About.COMPANY, "Acme laid off 200 staff", "Acme announced layoffs of 200 staff"
    )
    d = deps(pages=pages, candidates={LAYOFFS_PAGE: [layoffs]})
    outcome = await run(d)

    assert outcome.state is RunState.NEEDS_REVIEW_SENSITIVE
    assert outcome.draft is None


async def test_a_claim_its_own_quote_does_not_support_never_becomes_the_hook():
    d = deps(
        scores={PODCAST_QUOTE.claim: 4.5, HIRING.claim: 3.5},
        unsupported_claims=(PODCAST_QUOTE.claim,),
    )
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_READY
    assert d.writer.requests[0].hook.evidence.claim == HIRING.claim  # type: ignore[attr-defined]
    assert outcome.ranking is not None
    assert [(v.evidence.claim, v.reason) for v in outcome.ranking.vetoed] == [
        (PODCAST_QUOTE.claim, "claim_not_supported")
    ]


async def test_each_eligible_hook_is_scored_twice_and_the_samples_are_averaged():
    d = deps(
        scores={PODCAST_QUOTE.claim: [5.0, 2.0], HIRING.claim: [4.0, 4.0]},
        unsupported_claims=(),
    )
    outcome = await run(d)

    assert outcome.ranking is not None
    totals = {h.evidence.claim: h.total for h in outcome.ranking.ranked}
    assert totals == {PODCAST_QUOTE.claim: 3.5, HIRING.claim: 4.0}
    assert d.writer.requests[0].hook.evidence.claim == HIRING.claim  # type: ignore[attr-defined]


async def test_vetoed_items_are_never_sent_for_scoring():
    d = deps(unsupported_claims=(PODCAST_QUOTE.claim,), scores={HIRING.claim: 4.0})
    await run(d)
    assert PODCAST_QUOTE.claim not in d.scorer.scored  # type: ignore[attr-defined]


SALESY_DRAFT = Draft(
    subject="Quick question",
    body="I hope this finds you well. Ledgerly is a game-changer for finance teams. "
    "Can we book 30 minutes?",
)


async def test_two_variants_are_drafted_and_the_one_that_passes_the_rules_is_kept():
    d = deps(drafts=(SALESY_DRAFT, GOOD_DRAFT))
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_READY
    assert outcome.draft == GOOD_DRAFT
    assert sorted(r.variant for r in d.writer.requests) == [0, 1]  # type: ignore[attr-defined]


INVENTED = "Teams like yours cut close time by 60%."
DRAFT_WITH_INVENTED_METRIC = Draft(
    subject="Closing the books faster",
    body="Priya, on episode 41 you said closing the books faster is your top priority for "
    f"2026. {INVENTED} Worth a short look?",
)


async def test_an_unsupported_sentence_is_sent_back_for_a_fix_and_the_fixed_draft_is_kept():
    d = deps(
        drafts=(DRAFT_WITH_INVENTED_METRIC, DRAFT_WITH_INVENTED_METRIC, GOOD_DRAFT),
        unsupported_sentences=(INVENTED,),
    )
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_READY
    assert outcome.draft == GOOD_DRAFT
    (problems,) = d.writer.revisions  # type: ignore[attr-defined]
    assert any(INVENTED in p for p in problems)


async def test_a_draft_that_still_fails_after_two_fixes_is_held_with_its_problems_listed():
    d = deps(drafts=(DRAFT_WITH_INVENTED_METRIC,), unsupported_sentences=(INVENTED,))
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_HELD
    assert outcome.draft == DRAFT_WITH_INVENTED_METRIC
    assert len(d.writer.revisions) == 2  # type: ignore[attr-defined]
    assert any(INVENTED in p for p in outcome.problems)


async def test_recency_wording_is_flagged_when_the_hook_is_old():
    old_podcast = {
        PODCAST: Page(url=PODCAST, text=PAGES[PODCAST].text, published_at=date(2024, 3, 1))
    }
    says_recently = Draft(
        subject="Your podcast",
        body="Priya, you recently said closing the books faster is your top priority. "
        "Worth a short look?",
    )
    d = deps(pages=old_podcast, candidates={PODCAST: [PODCAST_QUOTE]}, drafts=(says_recently,))
    outcome = await run(d)

    assert outcome.state is RunState.DRAFT_HELD
    assert any("unsupported_recency" in p for p in outcome.problems)


async def test_links_that_are_not_in_the_evidence_are_flagged():
    with_link = Draft(
        subject="Closing the books faster",
        body=GOOD_DRAFT.body + " Details: https://ledgerly.example/case-study",
    )
    outcome = await run(deps(drafts=(with_link,)))

    assert outcome.state is RunState.DRAFT_HELD
    assert any("unknown_link" in p for p in outcome.problems)
