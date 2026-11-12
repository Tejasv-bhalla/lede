"""Fakes for the outer boundaries only (search, fetch, AI roles). Our own code is never faked."""

from __future__ import annotations

from collections.abc import Iterable

from app.research.ports import (
    Candidate,
    LedgerView,
    Page,
    PlannedQuery,
    Reflection,
    ResearchTarget,
    SearchHit,
)


class FakeSearcher:
    def __init__(self, results: dict[str, list[SearchHit]]):
        self.results = results
        self.queries: list[str] = []

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        self.queries.append(query.query)
        return self.results.get(query.query, [])


class FakeFetcher:
    def __init__(self, pages: dict[str, Page]):
        self.pages = pages
        self.fetched: list[str] = []

    async def fetch(self, url: str) -> Page | None:
        self.fetched.append(url)
        return self.pages.get(url)


class FakePlanner:
    def __init__(self, queries: Iterable[PlannedQuery]):
        self.queries = list(queries)

    async def plan(self, target: ResearchTarget) -> list[PlannedQuery]:
        return list(self.queries)


class FakeReader:
    def __init__(self, by_url: dict[str, list[Candidate]]):
        self.by_url = by_url

    async def read(self, page: Page, passages: str, target: ResearchTarget) -> list[Candidate]:
        return list(self.by_url.get(page.url, []))


class FakeReflector:
    """Returns scripted reflections in order; repeats the last one when the script runs out."""

    def __init__(self, script: Iterable[Reflection]):
        self.script = list(script) or [Reflection(is_sufficient=True)]
        self.calls = 0

    async def reflect(
        self, target: ResearchTarget, ledger: LedgerView, rounds_left: int
    ) -> Reflection:
        reflection = self.script[min(self.calls, len(self.script) - 1)]
        self.calls += 1
        return reflection
