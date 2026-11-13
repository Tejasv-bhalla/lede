from datetime import date

from app.domain.models import About, EntityMatch, SourceType
from app.domain.models import SignalCategory as Cat
from app.research.loop import Budget, ResearchDeps, RoundProgress, run_research
from app.research.ports import Candidate, Page, PlannedQuery, Reflection, ResearchTarget, SearchHit
from tests.fakes import FakeFetcher, FakePlanner, FakeReader, FakeReflector, FakeSearcher

TARGET = ResearchTarget(
    company_name="Acme",
    company_domain="acme.example",
    person_name="Priya Shah",
    title="VP Finance",
    objective="Book demos with finance leaders",
)
CAREERS = "https://acme.example/careers"
CAREERS_TEXT = (
    "Join Acme. We are hiring three accounts payable specialists in London to support our "
    "rapid growth across Europe."
)


def deps(*, queries, results, pages, candidates, reflections=()) -> ResearchDeps:
    return ResearchDeps(
        searcher=FakeSearcher(results),
        fetcher=FakeFetcher(pages),
        planner=FakePlanner(queries),
        reader=FakeReader(candidates),
        reflector=FakeReflector(reflections),
    )


async def test_round_zero_keeps_only_candidates_whose_quote_is_on_the_page():
    d = deps(
        queries=[PlannedQuery(Cat.HIRING_PATTERN, "Acme hiring accounts payable")],
        results={"Acme hiring accounts payable": [SearchHit(url=CAREERS)]},
        pages={CAREERS: Page(url=CAREERS, text=CAREERS_TEXT, published_at=date(2026, 11, 1))},
        candidates={
            CAREERS: [
                Candidate(
                    Cat.HIRING_PATTERN,
                    About.COMPANY,
                    "Acme is hiring three AP specialists in London",
                    "hiring three accounts payable specialists in London",
                ),
                Candidate(
                    Cat.EXPANSION,
                    About.COMPANY,
                    "Acme is opening a Berlin office",
                    "Acme will open a new office in Berlin next spring",
                ),
            ]
        },
        reflections=[Reflection(is_sufficient=True)],
    )
    result = await run_research(TARGET, d, Budget())
    assert [e.claim for e in result.ledger] == ["Acme is hiring three AP specialists in London"]
    assert result.ledger[0].quote_verified is True
    assert result.ledger[0].source_type is SourceType.FIRST_PARTY
    assert [r.reason for r in result.rejected] == ["not_found"]


PODCAST = "https://pod.example/ep41"
PODCAST_TEXT = (
    "On episode 41, Priya Shah, VP Finance at Acme, said closing the books faster is her top "
    "priority for 2026."
)
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


def two_round_deps(reflections):
    return deps(
        queries=[PlannedQuery(Cat.HIRING_PATTERN, "q-hiring")],
        results={
            "q-hiring": [SearchHit(url=CAREERS)],
            "q-podcast": [SearchHit(url=PODCAST, source_hint=SourceType.PODCAST_VIDEO)],
        },
        pages={
            CAREERS: Page(url=CAREERS, text=CAREERS_TEXT),
            PODCAST: Page(url=PODCAST, text=PODCAST_TEXT),
        },
        candidates={CAREERS: [HIRING], PODCAST: [PODCAST_QUOTE]},
        reflections=reflections,
    )


async def test_follow_up_round_runs_when_the_reflector_finds_gaps():
    d = two_round_deps(
        [
            Reflection(False, follow_up=(PlannedQuery(Cat.OWN_CONTENT, "q-podcast"),)),
            Reflection(True),
        ]
    )
    result = await run_research(TARGET, d, Budget())
    assert [(e.category, e.round_found) for e in result.ledger] == [
        (Cat.HIRING_PATTERN, 0),
        (Cat.OWN_CONTENT, 1),
    ]
    assert (result.rounds, result.stop_reason) == (2, "sufficient")


async def test_loop_stops_at_the_round_limit_even_if_the_reflector_wants_more():
    always_more = Reflection(False, follow_up=(PlannedQuery(Cat.OWN_CONTENT, "q-podcast"),))
    result = await run_research(
        TARGET, two_round_deps([always_more]), Budget(max_follow_up_rounds=1)
    )
    assert (result.rounds, result.stop_reason) == (2, "max_rounds")


async def test_repeated_follow_up_queries_are_not_searched_again():
    repeat = Reflection(
        False,
        follow_up=(
            PlannedQuery(Cat.HIRING_PATTERN, "q-hiring"),
            PlannedQuery(Cat.HIRING_PATTERN, "  Q-Hiring "),
        ),
    )
    d = two_round_deps([repeat])
    result = await run_research(TARGET, d, Budget())
    assert d.searcher.queries == ["q-hiring"]
    assert result.stop_reason == "no_new_queries"


async def test_follow_up_round_that_finds_nothing_new_stops_the_loop():
    dead_end = Reflection(False, follow_up=(PlannedQuery(Cat.OWN_CONTENT, "q-nothing"),))
    result = await run_research(TARGET, two_round_deps([dead_end]), Budget(max_follow_up_rounds=3))
    assert (result.rounds, result.stop_reason) == (2, "diminishing_returns")


async def test_evidence_is_confirmed_only_when_the_page_names_the_right_entity():
    other = "https://blog.example/finance-leaders"
    other_text = (
        "Many finance leaders say closing the books faster is their top priority for 2026, "
        "according to a survey of mid-size companies."
    )
    vague = Candidate(
        Cat.OWN_CONTENT,
        About.PERSON,
        "Priya prioritises a faster close",
        "closing the books faster is their top priority for 2026",
    )
    d = deps(
        queries=[PlannedQuery(Cat.OWN_CONTENT, "q-mixed"), PlannedQuery(Cat.OWN_CONTENT, "q-pod")],
        results={
            "q-mixed": [SearchHit(url=other), SearchHit(url=CAREERS)],
            "q-pod": [SearchHit(url=PODCAST)],
        },
        pages={
            other: Page(url=other, text=other_text),
            CAREERS: Page(url=CAREERS, text=CAREERS_TEXT),
            PODCAST: Page(url=PODCAST, text=PODCAST_TEXT),
        },
        candidates={other: [vague], CAREERS: [HIRING], PODCAST: [PODCAST_QUOTE]},
    )
    result = await run_research(TARGET, d, Budget(max_follow_up_rounds=0))
    assert {e.url: e.entity_match for e in result.ledger} == {
        other: EntityMatch.AMBIGUOUS,
        CAREERS: EntityMatch.CONFIRMED,
        PODCAST: EntityMatch.CONFIRMED,
    }


async def test_loop_stops_early_once_coverage_is_met_without_asking_the_reflector():
    funding = Candidate(
        Cat.EXPANSION,
        About.COMPANY,
        "Acme is growing across Europe",
        "to support our rapid growth across Europe",
    )
    d = deps(
        queries=[PlannedQuery(Cat.HIRING_PATTERN, "q1"), PlannedQuery(Cat.OWN_CONTENT, "q2")],
        results={"q1": [SearchHit(url=CAREERS)], "q2": [SearchHit(url=PODCAST)]},
        pages={
            CAREERS: Page(url=CAREERS, text=CAREERS_TEXT),
            PODCAST: Page(url=PODCAST, text=PODCAST_TEXT),
        },
        candidates={CAREERS: [HIRING, funding], PODCAST: [PODCAST_QUOTE]},
    )
    result = await run_research(TARGET, d, Budget())
    assert result.stop_reason == "coverage_met"
    assert d.reflector.calls == 0


class ExplodingFetcher:
    async def fetch(self, url):
        if url == CAREERS:
            raise TimeoutError("slow site")
        return Page(url=PODCAST, text=PODCAST_TEXT)


async def test_a_failing_page_is_logged_and_the_run_continues():
    d = two_round_deps([Reflection(True)])
    d = ResearchDeps(
        d.searcher,
        ExplodingFetcher(),
        FakePlanner(
            [
                PlannedQuery(Cat.HIRING_PATTERN, "q-hiring"),
                PlannedQuery(Cat.OWN_CONTENT, "q-podcast"),
            ]
        ),
        d.reader,
        d.reflector,
    )
    result = await run_research(TARGET, d, Budget())
    assert [e.url for e in result.ledger] == [PODCAST]
    assert [(f.url, f.reason) for f in result.failures] == [(CAREERS, "TimeoutError: slow site")]


async def test_searches_never_exceed_the_budget():
    queries = [PlannedQuery(Cat.FUNDING_MNA, f"q{i}") for i in range(10)]
    d = deps(queries=queries, results={}, pages={}, candidates={})
    result = await run_research(TARGET, d, Budget(max_searches=4))
    assert result.searches_used == 4
    assert d.searcher.queries == ["q0", "q1", "q2", "q3"]
    assert result.stop_reason == "budget"


async def test_progress_is_reported_after_every_round_with_the_new_facts():
    d = two_round_deps(
        [
            Reflection(False, follow_up=(PlannedQuery(Cat.OWN_CONTENT, "q-podcast"),)),
            Reflection(True),
        ]
    )
    rounds: list[RoundProgress] = []
    await run_research(TARGET, d, Budget(), on_round=rounds.append)

    assert [(r.number, r.searches_used, r.pages_used, r.verified) for r in rounds] == [
        (0, 1, 1, 1),
        (1, 2, 2, 2),
    ]
    assert [r.new_claims for r in rounds] == [(HIRING.claim,), (PODCAST_QUOTE.claim,)]
