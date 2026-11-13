"""Boundaries the research loop talks to. Real adapters (search APIs, HTTP, AI models) implement
these; tests plug in fakes here and nowhere else."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

from app.domain.models import About, SignalCategory, SourceType


@dataclass(frozen=True, slots=True)
class ResearchTarget:
    company_name: str
    company_domain: str | None
    person_name: str | None
    title: str | None
    objective: str
    pains: tuple[str, ...] = ()
    priorities: tuple[SignalCategory, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedQuery:
    category: SignalCategory
    query: str
    goal: str = ""
    # None: news mode for news-type signals. False forces a general web search (e.g. finding
    # who works at a company, which lives on team pages rather than in the news).
    news: bool | None = None


@dataclass(frozen=True, slots=True)
class SearchHit:
    url: str
    title: str = ""
    snippet: str = ""
    published_at: date | None = None
    source_hint: SourceType | None = None
    provider: str = ""


@dataclass(frozen=True, slots=True)
class Page:
    url: str
    text: str
    title: str = ""
    published_at: date | None = None
    publisher: str = ""


@dataclass(frozen=True, slots=True)
class Candidate:
    """A signal the reader AI proposes from one page; unverified until code checks its quote."""

    category: SignalCategory
    about: About
    claim: str
    quote: str
    published_at: date | None = None
    event_date: date | None = None


@dataclass(frozen=True, slots=True)
class LedgerView:
    """Compact view of what has been found so far, the only thing the reflector sees."""

    items: tuple[tuple[str, SignalCategory, About, str], ...]  # (id, category, about, claim)
    covered: frozenset[SignalCategory] = frozenset()


@dataclass(frozen=True, slots=True)
class Reflection:
    is_sufficient: bool
    follow_up: tuple[PlannedQuery, ...] = ()
    missing: tuple[SignalCategory, ...] = field(default_factory=tuple)
    rationale: str = ""


class Searcher(Protocol):
    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]: ...


class Fetcher(Protocol):
    async def fetch(self, url: str) -> Page | None: ...


class Planner(Protocol):
    async def plan(self, target: ResearchTarget) -> list[PlannedQuery]: ...


class Reader(Protocol):
    async def read(self, page: Page, passages: str, target: ResearchTarget) -> list[Candidate]: ...


class Reflector(Protocol):
    async def reflect(
        self, target: ResearchTarget, ledger: LedgerView, rounds_left: int
    ) -> Reflection: ...
