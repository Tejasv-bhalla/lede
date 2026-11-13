"""Fakes for the outer boundaries only (search, fetch, AI roles). Our own code is never faked."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.context.merge import MergedBrief
from app.domain.hook_dimensions import HOOK_DIMENSIONS
from app.domain.models import Entailment, Evidence, ProspectInput
from app.pipeline.hooks import DimensionScores
from app.pipeline.ports import ClaimVerdict, Draft, DraftRequest, Identity
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
        self.targets: list[ResearchTarget] = []

    async def plan(self, target: ResearchTarget) -> list[PlannedQuery]:
        self.targets.append(target)
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


# ── pipeline AI roles ─────────────────────────────────────────────────────────


class FakeResolver:
    def __init__(self, identity: Identity):
        self.identity = identity
        self.calls = 0

    async def resolve(self, prospect: ProspectInput, brief: MergedBrief) -> Identity:
        self.calls += 1
        return self.identity


class FakeEntailment:
    """Supported unless the claim is listed as unsupported."""

    def __init__(self, unsupported: Iterable[str] = ()):
        self.unsupported = set(unsupported)

    async def entails(self, evidence: Evidence) -> Entailment:
        if evidence.claim in self.unsupported:
            return Entailment.UNSUPPORTED
        return Entailment.SUPPORTED


class FakeScorer:
    """Scores every dimension with the value given for the evidence's claim (default 2).

    A list of values is returned one per call, to script disagreeing samples.
    """

    def __init__(self, by_claim: dict[str, float | list[float]]):
        self.by_claim = by_claim
        self.scored: list[str] = []

    async def score(self, evidence: Evidence, brief: MergedBrief) -> DimensionScores:
        scripted = self.by_claim.get(evidence.claim, 2.0)
        value = (
            scripted[self.scored.count(evidence.claim) % len(scripted)]
            if isinstance(scripted, list)
            else scripted
        )
        self.scored.append(evidence.claim)
        return DimensionScores(
            scores=dict.fromkeys(HOOK_DIMENSIONS, value),
            reasons=dict.fromkeys(HOOK_DIMENSIONS, "scripted"),
        )


class FakeWriter:
    """Returns scripted drafts in order (for draft and revise calls alike)."""

    def __init__(self, drafts: Iterable[Draft]):
        self.drafts = list(drafts)
        self.requests: list[DraftRequest] = []
        self.revisions: list[Sequence[str]] = []

    def _next(self) -> Draft:
        return self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0]

    async def draft(self, request: DraftRequest) -> Draft:
        self.requests.append(request)
        return self._next()

    async def revise(self, draft: Draft, problems: Sequence[str], request: DraftRequest) -> Draft:
        self.revisions.append(list(problems))
        return self._next()


class FakeFactChecker:
    """Flags the listed sentences as unsupported whenever they appear in a draft."""

    def __init__(self, unsupported: Iterable[str] = ()):
        self.unsupported = list(unsupported)
        self.checked: list[str] = []

    async def check(self, draft: Draft, request: DraftRequest) -> list[ClaimVerdict]:
        self.checked.append(draft.body)
        return [
            ClaimVerdict(claim=s, verdict=Entailment.UNSUPPORTED, reason="not in evidence")
            for s in self.unsupported
            if s in draft.body
        ]
