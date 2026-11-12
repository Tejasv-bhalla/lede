"""The bounded research loop (SYSTEM_DESIGN.md §3): plan, search, read, verify, reflect, repeat.

Only quote-verified candidates enter the evidence ledger. The loop never invents: when a stop rule
fires (coverage met, sufficient, nothing new, budget, round limit) it finishes with what it has.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TypeVar

from rapidfuzz import fuzz

from app.domain.models import About, EntityMatch, Evidence, Sensitivity
from app.policy.entity import match_entity
from app.policy.quotes import verify_quote
from app.policy.sensitivity import screen_sensitivity
from app.policy.sources import classify_source
from app.research.ports import (
    Candidate,
    Fetcher,
    LedgerView,
    Page,
    PlannedQuery,
    Planner,
    Reader,
    Reflector,
    ResearchTarget,
    Searcher,
    SearchHit,
)

QUERY_DUP_SCORE = 90.0  # token-set similarity above which a query counts as a repeat
COVERAGE_PERSON = 1  # usable person-level signals needed to stop early
COVERAGE_COMPANY = 2  # usable company-level signals needed to stop early

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class Budget:
    max_follow_up_rounds: int = 2
    max_searches: int = 20
    max_pages: int = 25


@dataclass(frozen=True, slots=True)
class ResearchDeps:
    searcher: Searcher
    fetcher: Fetcher
    planner: Planner
    reader: Reader
    reflector: Reflector


@dataclass(frozen=True, slots=True)
class Rejected:
    url: str
    claim: str
    reason: str


@dataclass(frozen=True, slots=True)
class Failure:
    url: str  # or the query text, for a failed search
    reason: str


@dataclass(slots=True)
class ResearchResult:
    ledger: list[Evidence] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    rounds: int = 0
    stop_reason: str = ""
    searches_used: int = 0
    pages_used: int = 0


def _usable(e: Evidence) -> bool:
    return e.entity_match is EntityMatch.CONFIRMED and e.sensitivity is Sensitivity.NONE


@dataclass(slots=True)
class _Run:
    target: ResearchTarget
    deps: ResearchDeps
    budget: Budget
    now: Callable[[], datetime]
    result: ResearchResult = field(default_factory=ResearchResult)
    hints: dict[str, SearchHit] = field(default_factory=dict)
    queries_run: list[str] = field(default_factory=list)

    # ── stop-rule helpers ────────────────────────────────────────────────────

    def fresh(self, queries: Sequence[PlannedQuery]) -> list[PlannedQuery]:
        """Drop queries that repeat (or nearly repeat) one already run."""
        kept: list[PlannedQuery] = []
        for q in queries:
            norm = " ".join(q.query.casefold().split())
            if any(fuzz.token_set_ratio(norm, s) >= QUERY_DUP_SCORE for s in self.queries_run):
                continue
            self.queries_run.append(norm)
            kept.append(q)
        return kept

    @property
    def budget_exhausted(self) -> bool:
        return (
            self.result.searches_used >= self.budget.max_searches
            or self.result.pages_used >= self.budget.max_pages
        )

    @property
    def coverage_met(self) -> bool:
        usable = [e for e in self.result.ledger if _usable(e)]
        people = sum(e.about is About.PERSON for e in usable)
        companies = sum(e.about is About.COMPANY for e in usable)
        return people >= COVERAGE_PERSON and companies >= COVERAGE_COMPANY

    def ledger_view(self) -> LedgerView:
        items = tuple((e.id, e.category, e.about, e.claim) for e in self.result.ledger)
        return LedgerView(items=items, covered=frozenset(e.category for e in self.result.ledger))

    # ── one round ────────────────────────────────────────────────────────────

    async def _gather(
        self, labels: Sequence[str], calls: Sequence[Awaitable[T]]
    ) -> list[tuple[str, T]]:
        """Run calls concurrently; record failures instead of letting one sink the round."""
        outcomes = await asyncio.gather(*calls, return_exceptions=True)
        ok: list[tuple[str, T]] = []
        for label, outcome in zip(labels, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                self.result.failures.append(Failure(label, f"{type(outcome).__name__}: {outcome}"))
            else:
                ok.append((label, outcome))
        return ok

    async def round(self, number: int, queries: Sequence[PlannedQuery]) -> None:
        queries = list(queries)[: self.budget.max_searches - self.result.searches_used]
        self.result.searches_used += len(queries)
        searched = await self._gather(
            [q.query for q in queries], [self.deps.searcher.search(q, self.target) for q in queries]
        )

        urls: list[str] = []
        for _, hits in searched:
            for hit in hits:
                if hit.url not in self.hints:
                    self.hints[hit.url] = hit
                    urls.append(hit.url)
        urls = urls[: self.budget.max_pages - self.result.pages_used]
        self.result.pages_used += len(urls)
        fetched = await self._gather(urls, [self.deps.fetcher.fetch(u) for u in urls])

        pages = [page for _, page in fetched if page is not None]
        read = await self._gather(
            [p.url for p in pages], [self.deps.reader.read(p, p.text, self.target) for p in pages]
        )
        by_url = {p.url: p for p in pages}
        for url, candidates in read:
            for candidate in candidates:
                self._admit(number, by_url[url], candidate)

    def _admit(self, number: int, page: Page, c: Candidate) -> None:
        check = verify_quote(c.quote, page.text)
        if not check.verified:
            self.result.rejected.append(Rejected(page.url, c.claim, check.reason or "not_found"))
            return
        hint = self.hints.get(page.url)
        source_type = classify_source(
            page.url, self.target.company_domain, hint=hint.source_hint if hint else None
        )
        self.result.ledger.append(
            Evidence(
                id=f"e{len(self.result.ledger) + 1}",
                category=c.category,
                about=c.about,
                claim=c.claim,
                verbatim_quote=c.quote,
                url=page.url,
                publisher=page.publisher,
                source_type=source_type,
                entity_match=match_entity(
                    c.about,
                    page.text,
                    source_type,
                    company_name=self.target.company_name,
                    person_name=self.target.person_name,
                ),
                published_at=c.published_at
                or page.published_at
                or (hint.published_at if hint else None),
                event_date=c.event_date,
                retrieved_at=self.now(),
                quote_verified=True,
                sensitivity=screen_sensitivity(c.category, f"{c.claim} {c.quote}"),
                round_found=number,
            )
        )


async def run_research(
    target: ResearchTarget,
    deps: ResearchDeps,
    budget: Budget,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ResearchResult:
    run = _Run(target, deps, budget, now)
    queries = run.fresh(await deps.planner.plan(target))
    run.result.stop_reason = "max_rounds"

    for number in range(budget.max_follow_up_rounds + 1):
        found_before = len(run.result.ledger)
        await run.round(number, queries)
        run.result.rounds = number + 1

        if run.coverage_met:
            run.result.stop_reason = "coverage_met"
            break
        if run.budget_exhausted:
            run.result.stop_reason = "budget"
            break
        if number > 0 and len(run.result.ledger) == found_before:
            run.result.stop_reason = "diminishing_returns"
            break
        rounds_left = budget.max_follow_up_rounds - number
        if rounds_left == 0:
            break

        reflection = await deps.reflector.reflect(target, run.ledger_view(), rounds_left)
        if reflection.is_sufficient:
            run.result.stop_reason = "sufficient"
            break
        queries = run.fresh(reflection.follow_up)
        if not queries:
            run.result.stop_reason = "no_new_queries"
            break

    return run.result
