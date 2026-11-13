"""Run one prospect end to end and decide its final state (SYSTEM_DESIGN.md §2).

Identity → research → verify → score → draft → fact-check. Each stage can end the run early with
an honest state (moved, ambiguous, low signal, sensitive) instead of forcing a weak email.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date

from app.context.merge import MergedBrief
from app.domain.models import Evidence, ProspectInput, RunState
from app.pipeline.hooks import DimensionScores, HookRanking, rank_hooks, veto_reason
from app.pipeline.ports import (
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
from app.policy.draft_rules import DraftRules
from app.research.loop import Budget, ResearchDeps, ResearchResult, run_research
from app.research.ports import ResearchTarget

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
        rules=rules,
        today=today,
    )
    outcome.draft = await deps.writer.draft(request)
    outcome.state = RunState.DRAFT_READY
    return outcome
