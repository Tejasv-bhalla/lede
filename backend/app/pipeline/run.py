"""Run one prospect end to end and decide its final state (SYSTEM_DESIGN.md §2).

Identity → research → verify → score → draft → fact-check. Each stage can end the run early with
an honest state (moved, ambiguous, low signal, sensitive) instead of forcing a weak email.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.context.merge import MergedBrief
from app.domain.models import ProspectInput, RunState
from app.pipeline.hooks import DimensionScores, HookRanking, rank_hooks
from app.pipeline.ports import (
    Draft,
    DraftRequest,
    EntailmentChecker,
    FactChecker,
    HookScorer,
    Identity,
    Resolver,
    Writer,
)
from app.policy.draft_rules import DraftRules
from app.research.loop import Budget, ResearchDeps, ResearchResult, run_research
from app.research.ports import ResearchTarget


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


async def run_prospect(
    prospect: ProspectInput,
    brief: MergedBrief,
    deps: PipelineDeps,
    *,
    rules: DraftRules,
    today: date,
    budget: Budget | None = None,
) -> RunOutcome:
    identity = await deps.resolver.resolve(prospect)
    contact = identity.contact
    assert contact is not None
    outcome = RunOutcome(RunState.RUNNING, identity=identity)

    target = ResearchTarget(
        company_name=contact.company_name,
        company_domain=contact.company_domain,
        person_name=contact.person_name,
        title=contact.title,
        objective=brief.objective,
        pains=tuple(brief.pains),
    )
    outcome.research = await run_research(target, deps.research, budget or Budget())
    ledger = outcome.research.ledger

    samples: dict[str, list[DimensionScores]] = {
        e.id: [await deps.scorer.score(e, brief)] for e in ledger
    }
    outcome.ranking = rank_hooks(ledger, samples, weights=brief.hook_weights)

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
