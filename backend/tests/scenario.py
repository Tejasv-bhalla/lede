"""A small, fixed slice of the web and the AI roles' scripted answers, shared by the pipeline
and API tests. Only outer boundaries are faked (see tests/README.md)."""

from datetime import date

from app.domain.models import About
from app.domain.models import SignalCategory as Cat
from app.pipeline.ports import Contact, Draft, Identity, IdentityStatus
from app.pipeline.run import PipelineDeps
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
PRIYA = Contact(
    company_name="Acme", company_domain="acme.example", person_name="Priya Shah", title="VP Finance"
)
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
