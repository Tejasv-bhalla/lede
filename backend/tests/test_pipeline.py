from datetime import date

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
    identity: Identity | None = None,
    scores: dict[str, float] | None = None,
    candidates: dict[str, list[Candidate]] | None = None,
    drafts: tuple[Draft, ...] = (GOOD_DRAFT,),
    unsupported_claims: tuple[str, ...] = (),
    unsupported_sentences: tuple[str, ...] = (),
) -> PipelineDeps:
    return PipelineDeps(
        research=ResearchDeps(
            searcher=FakeSearcher({QUERY.query: [SearchHit(url=CAREERS), SearchHit(url=PODCAST)]}),
            fetcher=FakeFetcher(PAGES),
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
    (request,) = d.writer.requests  # type: ignore[attr-defined]
    assert request.hook.evidence.claim == PODCAST_QUOTE.claim
    assert request.contact == PRIYA
