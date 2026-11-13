"""Run one prospect end to end and decide its final state (SYSTEM_DESIGN.md §2).

Identity → research → verify → score → draft → fact-check. Each stage can end the run early with
an honest state (moved, ambiguous, low signal, sensitive) instead of forcing a weak email.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Literal

from app.context.merge import MergedBrief
from app.domain.models import (
    About,
    Entailment,
    Evidence,
    Priority,
    ProspectInput,
    RunState,
    SourceType,
)
from app.pipeline.hooks import DimensionScores, HookRanking, rank_hooks, veto_reason
from app.pipeline.ports import (
    ClaimVerdict,
    Contact,
    Draft,
    DraftRequest,
    EntailmentChecker,
    FactChecker,
    HookScorer,
    Identity,
    IdentityStatus,
    Resolver,
    Writer,
)
from app.policy.draft_rules import DraftRules, check_draft
from app.policy.recency import Freshness, assess_recency
from app.providers.llm_router import LLMUnavailable
from app.research.loop import Budget, ResearchDeps, ResearchResult, run_research
from app.research.ports import ResearchTarget

DRAFT_VARIANTS = 2  # best-of-N drafting
MAX_REVISIONS = 2  # fact-check fix rounds before the draft is held for the rep
MAX_HOOK_CANDIDATES = 12  # facts checked and scored per run; the rest stay as context
SCORE_SAMPLES = 2  # independent judge samples per hook, averaged to steady the ranking

# Identity results that stop the run until the rep decides.
_PAUSES = {
    IdentityStatus.MOVED: RunState.CONTACT_MOVED,
    IdentityStatus.AMBIGUOUS: RunState.NEEDS_CLARIFICATION,
    IdentityStatus.SUGGESTED: RunState.NEEDS_CLARIFICATION,
}

# Ranking outcomes that end the run without a draft.
_NO_HOOK = {
    "low_signal": RunState.LOW_SIGNAL,
    "only_sensitive": RunState.NEEDS_REVIEW_SENSITIVE,
}


@dataclass(frozen=True, slots=True)
class PipelineDeps:
    research: ResearchDeps
    resolver: Resolver
    entailment: EntailmentChecker
    scorer: HookScorer
    writer: Writer
    fact_checker: FactChecker


EventStatus = Literal["started", "done", "failed", "finished"]


@dataclass(frozen=True, slots=True)
class StageEvent:
    stage: str  # identity | research | verify | score | draft | fact_check | run
    status: EventStatus
    summary: str  # one line for the live view; the final state for the "run" event


@dataclass(slots=True)
class RunOutcome:
    state: RunState
    identity: Identity | None = None
    research: ResearchResult | None = None
    ranking: HookRanking | None = None
    draft: Draft | None = None
    rules: DraftRules | None = None  # the per-run rules the draft was checked against
    problems: list[str] = field(default_factory=list)  # what blocks approval of a held draft
    notes: list[str] = field(default_factory=list)


_PRIORITY_RANK = {Priority.HIGH: 0, Priority.MEDIUM: 1, Priority.LOW: 2}
_SOURCE_RANK = {
    SourceType.FIRST_PARTY: 0,
    SourceType.FILING: 0,
    SourceType.REP_SUPPLIED: 0,
    SourceType.PRESS: 1,
    SourceType.PODCAST_VIDEO: 1,
    SourceType.JOB_BOARD: 2,
}


MAX_PER_PAGE = 2  # one rich page must not crowd out every other source
_FRESHNESS_RANK = {Freshness.RECENT: 0, Freshness.UNDATED: 1, Freshness.STALE: 2}


def _shortlist(
    ledger: list[Evidence], brief: MergedBrief, today: date, limit: int
) -> list[Evidence]:
    """Pick the facts worth spending AI calls on, using only what code already knows: campaign
    priority, freshness within the signal's window, person before company, source strength,
    then age; at most MAX_PER_PAGE from any one page."""

    def key(e: Evidence) -> tuple[int, int, int, int, int]:
        when = e.event_date or e.published_at
        freshness = assess_recency(
            e.category,
            published_at=e.published_at,
            event_date=e.event_date,
            today=today,
            overrides=brief.recency_windows_days,
        ).freshness
        return (
            _PRIORITY_RANK.get(brief.signal_priorities.get(e.category, Priority.MEDIUM), 1),
            _FRESHNESS_RANK[freshness],
            0 if e.about is About.PERSON else 1,
            _SOURCE_RANK.get(e.source_type, 3),
            (today - when).days if when else 10_000,
        )

    picked: list[Evidence] = []
    per_page: dict[str, int] = {}
    for e in sorted((e for e in ledger if veto_reason(e) is None), key=key):
        if per_page.get(e.url, 0) >= MAX_PER_PAGE:
            continue
        per_page[e.url] = per_page.get(e.url, 0) + 1
        picked.append(e)
        if len(picked) == limit:
            break
    return picked


async def _verify(
    ledger: list[Evidence], shortlist: list[Evidence], checker: EntailmentChecker
) -> list[Evidence]:
    """S4: ask whether each shortlisted item's quote supports its claim (one batched call)."""
    verdicts = await checker.entails(shortlist) if shortlist else []
    checked = {
        e.id: e.model_copy(update={"entailment": v})
        for e, v in zip(shortlist, verdicts, strict=True)
    }
    return [checked.get(e.id, e) for e in ledger]


async def _score(
    items: list[Evidence], scorer: HookScorer, brief: MergedBrief
) -> dict[str, list[DimensionScores]]:
    """S5: SCORE_SAMPLES independent batched samples; rank_hooks averages them per item."""
    if not items:
        return {}
    samples = await asyncio.gather(*(scorer.score(items, brief) for _ in range(SCORE_SAMPLES)))
    return {e.id: [sample[i] for sample in samples] for i, e in enumerate(items)}


def _preflight(prospect: ProspectInput, brief: MergedBrief) -> list[str]:
    """S1: cheap checks before any paid call. (Suppression and duplicates are checked by the
    caller, which owns the run history.)"""
    problems = [f"{i.message} {i.fix}" for i in brief.issues if i.severity == "error"]
    if not prospect.company_name.strip():
        problems.insert(0, "A company name is required.")
    return problems


def _rules_for(
    rules: DraftRules, hook: Evidence, ledger: list[Evidence], brief: MergedBrief, today: date
) -> DraftRules:
    """Tighten the workspace rules for this run: the brief's never-claims, recency words only
    for a recent hook, and links only to evidence pages or the seller's approved proof."""
    freshness = assess_recency(
        hook.category,
        published_at=hook.published_at,
        event_date=hook.event_date,
        today=today,
        overrides=brief.recency_windows_days,
    ).freshness
    allowed = {e.url for e in ledger} | {c.proof_url for c in brief.claims if c.proof_url}
    return replace(
        rules,
        never_claims=tuple(dict.fromkeys([*rules.never_claims, *brief.never_claims])),
        recency_allowed=rules.recency_allowed and freshness is Freshness.RECENT,
        allowed_urls=frozenset(allowed),
    )


async def _best_draft(writer: Writer, request: DraftRequest) -> Draft:
    """S6: draft DRAFT_VARIANTS variants; keep the one with the fewest rule violations."""
    drafts = await asyncio.gather(
        *(writer.draft(replace(request, variant=i)) for i in range(DRAFT_VARIANTS))
    )
    return min(drafts, key=lambda d: len(check_draft(d.body, request.rules)))


def _problems(draft: Draft, verdicts: list[ClaimVerdict], rules: DraftRules) -> list[str]:
    unsupported = [
        f"Unsupported claim: {v.claim}" + (f" ({v.reason})" if v.reason else "")
        for v in verdicts
        if v.verdict is not Entailment.SUPPORTED
    ]
    return unsupported + [f"Rule {v.kind}: {v.detail}" for v in check_draft(draft.body, rules)]


async def _fact_check(
    draft: Draft, request: DraftRequest, deps: PipelineDeps
) -> tuple[Draft, list[str]]:
    """S7: check claim by claim; send problems back for a minimal fix, at most MAX_REVISIONS.

    Returns the final draft and whatever problems remain after the last attempt.
    """
    for attempt in range(MAX_REVISIONS + 1):
        verdicts = await deps.fact_checker.check(draft, request)
        problems = _problems(draft, verdicts, request.rules)
        if not problems or attempt == MAX_REVISIONS:
            return draft, problems
        draft = await deps.writer.revise(draft, problems, request)
    raise AssertionError("unreachable")


async def run_prospect(
    prospect: ProspectInput,
    brief: MergedBrief,
    deps: PipelineDeps,
    *,
    rules: DraftRules,
    today: date,
    budget: Budget | None = None,
    pinned: Contact | None = None,
    on_event: Callable[[StageEvent], None] | None = None,
    max_hook_candidates: int = MAX_HOOK_CANDIDATES,
) -> RunOutcome:
    """Run every stage and return the outcome; never raises for model outages.

    `pinned` is the contact the rep confirmed after a pause; identity is not resolved again.
    `on_event` receives a started/done event per stage and a final one, for the live view.
    """
    events = _Events(on_event)
    problems = _preflight(prospect, brief)
    outcome = RunOutcome(
        RunState.INVALID_INPUT if problems else RunState.RUNNING, problems=problems
    )
    if not problems:
        try:
            await _stages(
                outcome,
                events,
                prospect,
                brief,
                deps,
                rules,
                today,
                budget or Budget(),
                pinned,
                max_hook_candidates,
            )
        except LLMUnavailable as exc:
            # Keep whatever earlier stages produced, so a retry or the rep can build on it.
            events.failed(str(exc))
            outcome.state = RunState.FAILED
            outcome.problems.append(str(exc))
    events.finished(outcome.state)
    return outcome


class _Events:
    def __init__(self, sink: Callable[[StageEvent], None] | None) -> None:
        self._sink = sink
        self._stage = "run"

    def _send(self, stage: str, status: EventStatus, summary: str) -> None:
        if self._sink is not None:
            self._sink(StageEvent(stage, status, summary))

    def started(self, stage: str) -> None:
        self._stage = stage
        self._send(stage, "started", "")

    def done(self, summary: str) -> None:
        self._send(self._stage, "done", summary)

    def failed(self, reason: str) -> None:
        self._send(self._stage, "failed", reason)

    def finished(self, state: RunState) -> None:
        self._send("run", "finished", state.value)


async def _stages(
    outcome: RunOutcome,
    events: _Events,
    prospect: ProspectInput,
    brief: MergedBrief,
    deps: PipelineDeps,
    rules: DraftRules,
    today: date,
    budget: Budget,
    pinned: Contact | None,
    max_hook_candidates: int,
) -> None:
    events.started("identity")
    identity = outcome.identity = (
        Identity(IdentityStatus.CONFIRMED, contact=pinned)
        if pinned
        else await deps.resolver.resolve(prospect, brief)
    )
    contact = identity.contact
    if identity.status is IdentityStatus.NOT_FOUND:
        outcome.notes.append("person_not_found")
        contact = Contact(
            company_name=prospect.company_name, company_domain=prospect.company_domain
        )
    events.done(_describe_identity(identity))
    if identity.status in _PAUSES:
        outcome.state = _PAUSES[identity.status]
        return
    assert contact is not None, "a confirmed identity always carries its contact"

    events.started("research")
    target = ResearchTarget(
        company_name=contact.company_name,
        company_domain=contact.company_domain,
        person_name=contact.person_name,
        title=contact.title,
        objective=brief.objective,
        pains=tuple(brief.pains),
        priorities=tuple(c for c, p in brief.signal_priorities.items() if p is Priority.HIGH),
    )
    research = outcome.research = await run_research(target, deps.research, budget)
    events.done(
        f"{len(research.ledger)} verified items from {research.pages_used} pages in "
        f"{research.rounds} round(s); stopped: {research.stop_reason}"
    )

    events.started("verify")
    shortlist = _shortlist(research.ledger, brief, today, max_hook_candidates)
    ledger = research.ledger = await _verify(research.ledger, shortlist, deps.entailment)
    unsupported = sum(e.entailment is Entailment.UNSUPPORTED for e in ledger)
    events.done(f"{len(shortlist)} checked, {unsupported} unsupported")

    events.started("score")
    picked = {e.id for e in shortlist}
    eligible = [e for e in ledger if e.id in picked and veto_reason(e) is None]
    samples = await _score(eligible, deps.scorer, brief)
    ranking = outcome.ranking = rank_hooks(ledger, samples, weights=brief.hook_weights)
    events.done(
        f"top hook {ranking.ranked[0].total:.2f}: {ranking.ranked[0].evidence.claim}"
        if ranking.ranked
        else "no usable hook"
    )
    if ranking.outcome != "ok":
        outcome.state = _NO_HOOK[ranking.outcome]
        return

    events.started("draft")
    top = ranking.top()
    request = DraftRequest(
        prospect=prospect,
        contact=contact,
        hook=top[0],
        alternates=tuple(top[1:]),
        brief=brief,
        rules=_rules_for(rules, top[0].evidence, ledger, brief, today),
        today=today,
    )
    outcome.rules = request.rules
    draft = await _best_draft(deps.writer, request)
    events.done(f"best of {DRAFT_VARIANTS} variants: {len(draft.body.split())} words")

    events.started("fact_check")
    outcome.draft, outcome.problems = await _fact_check(draft, request, deps)
    events.done(f"{len(outcome.problems)} problem(s) remain" if outcome.problems else "all clear")
    outcome.state = RunState.DRAFT_HELD if outcome.problems else RunState.DRAFT_READY


def _describe_identity(identity: Identity) -> str:
    c = identity.contact
    who = f"{c.person_name or 'company only'} at {c.company_name}" if c else ""
    if identity.candidates:
        who = f"{len(identity.candidates)} candidates"
    return f"{identity.status.value}: {who}" if who else identity.status.value
