"""Run one prospect end to end and decide its final state (SYSTEM_DESIGN.md §2).

Identity → research → verify → score → draft → fact-check. Each stage can end the run early with
an honest state (moved, ambiguous, low signal, sensitive) instead of forcing a weak email.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from datetime import date

from app.context.merge import MergedBrief
from app.domain.models import Entailment, Evidence, ProspectInput, RunState
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
from app.research.loop import Budget, ResearchDeps, ResearchResult, run_research
from app.research.ports import ResearchTarget

DRAFT_VARIANTS = 2  # best-of-N drafting
MAX_REVISIONS = 2  # fact-check fix rounds before the draft is held for the rep
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


@dataclass(slots=True)
class RunOutcome:
    state: RunState
    identity: Identity | None = None
    research: ResearchResult | None = None
    ranking: HookRanking | None = None
    draft: Draft | None = None
    problems: list[str] = field(default_factory=list)  # what blocks approval of a held draft
    notes: list[str] = field(default_factory=list)


async def _verify(ledger: list[Evidence], checker: EntailmentChecker) -> list[Evidence]:
    """S4: ask whether each hook-eligible item's quote supports its claim (one call per item)."""
    eligible = [e for e in ledger if veto_reason(e) is None]
    verdicts = await asyncio.gather(*(checker.entails(e) for e in eligible))
    checked = {
        e.id: e.model_copy(update={"entailment": v})
        for e, v in zip(eligible, verdicts, strict=True)
    }
    return [checked.get(e.id, e) for e in ledger]


async def _score(
    ledger: list[Evidence], scorer: HookScorer, brief: MergedBrief
) -> dict[str, list[DimensionScores]]:
    """S5: score each veto-free item SCORE_SAMPLES times; rank_hooks averages the samples."""
    eligible = [e for e in ledger if veto_reason(e) is None]
    results = await asyncio.gather(
        *(scorer.score(e, brief) for e in eligible for _ in range(SCORE_SAMPLES))
    )
    return {
        e.id: list(results[i * SCORE_SAMPLES : (i + 1) * SCORE_SAMPLES])
        for i, e in enumerate(eligible)
    }


def _rules_for(
    rules: DraftRules, hook: Evidence, ledger: list[Evidence], brief: MergedBrief, today: date
) -> DraftRules:
    """Tighten the workspace rules for this run: recency words only for a recent hook, and
    links only to pages we hold as evidence or to the seller's approved proof."""
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
    evidence = [request.hook.evidence, *(h.evidence for h in request.alternates)]
    for attempt in range(MAX_REVISIONS + 1):
        verdicts = await deps.fact_checker.check(draft, evidence)
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
) -> RunOutcome:
    """`pinned` is the contact the rep confirmed after a pause; identity is not resolved again."""
    identity = (
        Identity(IdentityStatus.CONFIRMED, contact=pinned)
        if pinned
        else await deps.resolver.resolve(prospect)
    )
    outcome = RunOutcome(RunState.RUNNING, identity=identity)
    if identity.status in _PAUSES:
        outcome.state = _PAUSES[identity.status]
        return outcome
    contact = identity.contact
    if identity.status is IdentityStatus.NOT_FOUND:
        outcome.notes.append("person_not_found")
        contact = Contact(
            company_name=prospect.company_name, company_domain=prospect.company_domain
        )
    assert contact is not None, "a confirmed identity always carries its contact"

    target = ResearchTarget(
        company_name=contact.company_name,
        company_domain=contact.company_domain,
        person_name=contact.person_name,
        title=contact.title,
        objective=brief.objective,
        pains=tuple(brief.pains),
    )
    outcome.research = await run_research(target, deps.research, budget or Budget())
    ledger = outcome.research.ledger = await _verify(outcome.research.ledger, deps.entailment)

    samples = await _score(ledger, deps.scorer, brief)
    outcome.ranking = rank_hooks(ledger, samples, weights=brief.hook_weights)
    if outcome.ranking.outcome != "ok":
        outcome.state = _NO_HOOK[outcome.ranking.outcome]
        return outcome

    top = outcome.ranking.top()
    request = DraftRequest(
        prospect=prospect,
        contact=contact,
        hook=top[0],
        alternates=tuple(top[1:]),
        brief=brief,
        rules=_rules_for(rules, top[0].evidence, ledger, brief, today),
        today=today,
    )
    draft = await _best_draft(deps.writer, request)
    outcome.draft, outcome.problems = await _fact_check(draft, request, deps)
    outcome.state = RunState.DRAFT_HELD if outcome.problems else RunState.DRAFT_READY
    return outcome
