"""Merge several search providers into one ranked list (SYSTEM_DESIGN.md §3.3).

Reciprocal rank fusion: a page's score is the sum of 1 / (k + rank) over the providers that
found it, so agreement between independent engines beats any single engine's ordering, and no
provider's raw scores need to be comparable. One slow or failing provider never sinks a search.

Free-tier quotas are protected here: each engine's answers are cached for a few days (re-runs,
replays and several prospects at one company don't pay twice), and an engine whose monthly
budget is nearly spent is skipped while the free engines carry on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.research.ports import PlannedQuery, ResearchTarget, SearchHit

RRF_K = 60  # the standard constant; dampens the gap between rank 1 and rank 2
CACHE_DAYS = 7  # long enough to share across a batch, short enough for news to stay fresh

# Hosts we must not read (terms of service) or cannot read without a login.
BLOCKED_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "x.com",
    "twitter.com",
)
UNREADABLE_SUFFIXES = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip")
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid")


class SearchProvider(Protocol):
    name: str

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]: ...


class SearchUnavailable(RuntimeError):
    """Every provider failed for this query."""


class _BudgetReached(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EngineBudget:
    monthly_limit: float  # in the engine's own unit: credits, dollars...
    cost_per_search: float
    reserve: float = 0.1  # stop this share short of the limit, for searches already in flight


class SearchLedger(Protocol):
    """Where per-engine answers are cached and monthly spend is counted."""

    async def cached(self, key: str, now: datetime) -> list[SearchHit] | None: ...

    async def remember(self, key: str, hits: list[SearchHit], expires: datetime) -> None: ...

    async def spent(self, engine: str, period: str) -> float: ...

    async def charge(self, engine: str, period: str, amount: float) -> None: ...


class MemoryLedger:
    """In-process ledger for local runs and tests; production uses the database (StoreLedger)."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[datetime, list[SearchHit]]] = {}
        self._spend: dict[tuple[str, str], float] = {}

    async def cached(self, key: str, now: datetime) -> list[SearchHit] | None:
        entry = self._cache.get(key)
        return list(entry[1]) if entry and entry[0] > now else None

    async def remember(self, key: str, hits: list[SearchHit], expires: datetime) -> None:
        self._cache[key] = (expires, list(hits))

    async def spent(self, engine: str, period: str) -> float:
        return self._spend.get((engine, period), 0.0)

    async def charge(self, engine: str, period: str, amount: float) -> None:
        self._spend[(engine, period)] = self._spend.get((engine, period), 0.0) + amount


def cache_key(engine: str, query: PlannedQuery) -> str:
    """Same engine + same signal type + same words (any case or spacing) = same answer."""
    return f"{engine}|{query.category.value}|{' '.join(query.query.casefold().split())}"


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    reason: str


def clean_url(url: str) -> str:
    """Drop tracking parameters and the fragment; keep everything that names the page."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def page_key(url: str) -> str:
    """Identity of a page across providers: no scheme, no www, no trailing slash, any case host."""
    parts = urlsplit(clean_url(url))
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}?{parts.query}".rstrip("?")


def _readable(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        return False
    return not parts.path.lower().endswith(UNREADABLE_SUFFIXES)


def _merge(kept: SearchHit, other: SearchHit) -> SearchHit:
    """Keep the first URL; fill in details the first provider didn't have."""
    return replace(
        kept,
        title=kept.title or other.title,
        snippet=kept.snippet or other.snippet,
        published_at=kept.published_at or other.published_at,
        source_hint=kept.source_hint or other.source_hint,
        provider=f"{kept.provider}+{other.provider}",
    )


class FusedSearcher:
    """Implements the research loop's `Searcher` port on top of several providers."""

    def __init__(
        self,
        providers: Sequence[SearchProvider],
        *,
        max_results: int = 8,
        timeout_s: float = 10.0,  # Tavily and Exa answer in 1-5 s; DuckDuckGo sometimes hangs
        ledger: SearchLedger | None = None,
        budgets: Mapping[str, EngineBudget] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._providers = list(providers)
        self._max_results = max_results
        self._timeout_s = timeout_s
        self._ledger: SearchLedger = ledger or MemoryLedger()
        self._budgets = dict(budgets or {})
        self._clock = clock
        self.last_failures: list[ProviderFailure] = []

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        now = self._clock()
        outcomes = await asyncio.gather(
            *(self._ask(p, query, target, now) for p in self._providers),
            return_exceptions=True,
        )
        self.last_failures = []
        lists: list[list[SearchHit]] = []
        for provider, outcome in zip(self._providers, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                self.last_failures.append(ProviderFailure(provider.name, _reason(outcome)))
            else:
                lists.append(outcome)
        if not lists:
            raise SearchUnavailable(
                "; ".join(f"{f.provider}: {f.reason}" for f in self.last_failures)
            )
        return self._fuse(lists)

    async def _ask(
        self, provider: SearchProvider, query: PlannedQuery, target: ResearchTarget, now: datetime
    ) -> list[SearchHit]:
        key = cache_key(provider.name, query)
        cached = await self._ledger.cached(key, now)
        if cached is not None:
            return cached
        period = now.strftime("%Y-%m")
        budget = self._budgets.get(provider.name)
        if budget is not None:
            ceiling = budget.monthly_limit * (1 - budget.reserve)
            spent = await self._ledger.spent(provider.name, period)
            if spent + budget.cost_per_search > ceiling:
                raise _BudgetReached
        hits = await asyncio.wait_for(provider.search(query, target), self._timeout_s)
        if budget is not None:
            await self._ledger.charge(provider.name, period, budget.cost_per_search)
        await self._ledger.remember(key, hits, now + timedelta(days=CACHE_DAYS))
        return hits

    def _fuse(self, lists: list[list[SearchHit]]) -> list[SearchHit]:
        scores: dict[str, float] = {}
        best: dict[str, SearchHit] = {}
        for hits in lists:
            seen_here: set[str] = set()
            for rank, hit in enumerate((h for h in hits if _readable(h.url)), start=1):
                key = page_key(hit.url)
                if key in seen_here:  # a provider listing a page twice gets no extra credit
                    continue
                seen_here.add(key)
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
                if key in best:
                    best[key] = _merge(best[key], hit)
                else:
                    best[key] = replace(hit, url=clean_url(hit.url))
        ranked = sorted(scores, key=lambda k: scores[k], reverse=True)  # stable on ties
        return [best[k] for k in ranked[: self._max_results]]


def _reason(exc: BaseException) -> str:
    if isinstance(exc, _BudgetReached):
        return "monthly budget reached"
    if isinstance(exc, TimeoutError):
        return "timed out"
    return repr(exc)
