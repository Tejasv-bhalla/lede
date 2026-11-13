import asyncio
from datetime import UTC, date, datetime, timedelta

import pytest

from app.db.store import Store, StoreLedger
from app.domain.models import SignalCategory as Cat
from app.providers.search.fusion import (
    CACHE_DAYS,
    EngineBudget,
    FusedSearcher,
    MemoryLedger,
    SearchUnavailable,
)
from app.research.ports import PlannedQuery, ResearchTarget, SearchHit

TARGET = ResearchTarget(
    company_name="Acme",
    company_domain="acme.example",
    person_name="Priya Shah",
    title="VP Finance",
    objective="Book demos",
)
QUERY = PlannedQuery(Cat.FUNDING_MNA, "Acme funding round")


class FakeProvider:
    def __init__(self, name: str, hits=(), *, error: Exception | None = None, delay: float = 0):
        self.name, self.hits, self.error, self.delay = name, list(hits), error, delay

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return [
            SearchHit(url=h.url, title=h.title, provider=self.name, published_at=h.published_at)
            for h in self.hits
        ]


def hits(*urls: str) -> list[SearchHit]:
    return [SearchHit(url=u) for u in urls]


async def urls(searcher: FusedSearcher) -> list[str]:
    return [h.url for h in await searcher.search(QUERY, TARGET)]


async def test_pages_found_by_several_providers_rank_above_pages_found_by_one():
    searcher = FusedSearcher(
        [
            FakeProvider("tavily", hits("https://a.example/1", "https://b.example/2")),
            FakeProvider("exa", hits("https://c.example/3", "https://b.example/2")),
            FakeProvider("ddg", hits("https://b.example/2", "https://a.example/1")),
        ]
    )
    assert await urls(searcher) == [
        "https://b.example/2",  # found by all three
        "https://a.example/1",  # found by two, ranked first once
        "https://c.example/3",
    ]


async def test_the_same_page_under_different_urls_counts_once_and_keeps_known_details():
    searcher = FusedSearcher(
        [
            FakeProvider(
                "tavily", [SearchHit(url="https://www.acme.example/news/raise/?utm_source=x#top")]
            ),
            FakeProvider(
                "exa",
                [
                    SearchHit(
                        url="http://acme.example/news/raise",
                        title="Acme raises $40M",
                        published_at=date(2026, 11, 2),
                    )
                ],
            ),
        ]
    )
    (hit,) = await searcher.search(QUERY, TARGET)
    assert hit.url == "https://www.acme.example/news/raise/"  # first seen, tracking removed
    assert (hit.title, hit.published_at) == ("Acme raises $40M", date(2026, 11, 2))
    assert hit.provider == "tavily+exa"


async def test_a_failing_or_slow_provider_does_not_sink_the_search():
    searcher = FusedSearcher(
        [
            FakeProvider("tavily", error=RuntimeError("quota exhausted")),
            FakeProvider("exa", hits("https://slow.example/x"), delay=1.0),
            FakeProvider("ddg", hits("https://b.example/2")),
        ],
        timeout_s=0.05,
    )
    assert await urls(searcher) == ["https://b.example/2"]
    assert {f.provider for f in searcher.last_failures} == {"tavily", "exa"}


async def test_when_every_provider_fails_the_search_fails_loudly():
    searcher = FusedSearcher([FakeProvider("tavily", error=RuntimeError("down"))])
    with pytest.raises(SearchUnavailable):
        await searcher.search(QUERY, TARGET)


async def test_pages_we_must_not_or_cannot_read_are_dropped():
    searcher = FusedSearcher(
        [
            FakeProvider(
                "ddg",
                hits(
                    "https://www.linkedin.com/in/priyashah",
                    "https://www.facebook.com/acme",
                    "https://acme.example/blog/report.pdf",
                    "https://acme.example/blog/post",
                ),
            )
        ]
    )
    assert await urls(searcher) == ["https://acme.example/blog/post"]


async def test_results_are_capped_after_ranking():
    many = [f"https://site{i}.example/" for i in range(20)]
    searcher = FusedSearcher([FakeProvider("ddg", hits(*many))], max_results=5)
    assert await urls(searcher) == many[:5]


# ── budgets and cache ─────────────────────────────────────────────────────────

NOV = datetime(2026, 11, 13, tzinfo=UTC)


class CountingProvider(FakeProvider):
    def __init__(self, name: str, hits_=()):
        super().__init__(name, hits_)
        self.calls = 0

    async def search(self, query, target):
        self.calls += 1
        return await super().search(query, target)


@pytest.fixture(params=["memory", "database"])
async def ledger(request, tmp_path):
    if request.param == "memory":
        yield MemoryLedger()
        return
    store = Store(f"sqlite:///{tmp_path / 'ledger.db'}")
    await store.create_all()
    yield StoreLedger(store)
    await store.dispose()


def metered(providers, ledger, *, clock=lambda: NOV, **budgets):
    return FusedSearcher(providers, ledger=ledger, budgets=budgets, clock=clock)


async def test_an_engine_near_its_monthly_budget_is_skipped_and_the_others_carry_on(ledger):
    tavily = CountingProvider("tavily", hits("https://a.example/1"))
    ddg = CountingProvider("ddg", hits("https://b.example/2"))
    searcher = metered(
        [tavily, ddg], ledger, tavily=EngineBudget(monthly_limit=3, cost_per_search=1, reserve=0)
    )
    for i in range(4):
        await searcher.search(PlannedQuery(Cat.FUNDING_MNA, f"query {i}"), TARGET)

    assert (tavily.calls, ddg.calls) == (3, 4)
    assert [f.reason for f in searcher.last_failures] == ["monthly budget reached"]
    assert await ledger.spent("tavily", "2026-11") == 3


async def test_spend_is_counted_per_calendar_month(ledger):
    now = [NOV]
    tavily = CountingProvider("tavily", hits("https://a.example/1"))
    searcher = metered(
        [tavily],
        ledger,
        clock=lambda: now[0],
        tavily=EngineBudget(monthly_limit=1, cost_per_search=1, reserve=0),
    )
    await searcher.search(PlannedQuery(Cat.FUNDING_MNA, "q1"), TARGET)
    now[0] = datetime(2026, 12, 1, tzinfo=UTC)
    await searcher.search(PlannedQuery(Cat.FUNDING_MNA, "q2"), TARGET)
    assert tavily.calls == 2


async def test_a_repeated_query_is_answered_from_the_cache_without_spending(ledger):
    tavily = CountingProvider("tavily", hits("https://a.example/1"))
    searcher = metered(
        [tavily], ledger, tavily=EngineBudget(monthly_limit=100, cost_per_search=1, reserve=0)
    )
    first = await searcher.search(QUERY, TARGET)
    again = await searcher.search(PlannedQuery(QUERY.category, "  ACME funding   round "), TARGET)

    assert again == first
    assert tavily.calls == 1
    assert await ledger.spent("tavily", "2026-11") == 1


async def test_cached_results_expire_so_news_stays_fresh(ledger):
    now = [NOV]
    tavily = CountingProvider("tavily", hits("https://a.example/1"))
    searcher = metered([tavily], ledger, clock=lambda: now[0])
    await searcher.search(QUERY, TARGET)
    now[0] = NOV + timedelta(days=CACHE_DAYS + 1)
    await searcher.search(QUERY, TARGET)
    assert tavily.calls == 2


async def test_the_same_words_searched_as_web_instead_of_news_are_not_answered_from_cache(ledger):
    tavily = CountingProvider("tavily", hits("https://a.example/1"))
    searcher = metered([tavily], ledger)
    await searcher.search(QUERY, TARGET)
    await searcher.search(PlannedQuery(QUERY.category, QUERY.query, news=False), TARGET)
    assert tavily.calls == 2
