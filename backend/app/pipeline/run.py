"""Run one prospect end to end and decide its final state (SYSTEM_DESIGN.md §2).

Identity → research → verify → score → draft → fact-check. Each stage can end the run early with
an honest state (moved, ambiguous, low signal, sensitive) instead of forcing a weak email.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
from urllib.parse import urlsplit

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
    EmailFinder,
    EmailLookupFailed,
    EntailmentChecker,
    FactChecker,
    FoundEmail,
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
MAX_PROGRESS_ITEMS = 6  # newest facts shown per research round in the live view
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
    email_finder: EmailFinder | None = None  # e.g. Hunter; None = published addresses only


EventStatus = Literal["started", "progress", "done", "failed", "finished"]


@dataclass(frozen=True, slots=True)
class StageEvent:
    stage: str  # identity | research | verify | score | draft | fact_check | run
    status: EventStatus
    summary: str  # one line for the live view; the final state for the "run" event
    items: tuple[str, ...] = ()  # e.g. the facts a research round just verified


@dataclass(slots=True)
class RunOutcome:
    state: RunState
    identity: Identity | None = None
    research: ResearchResult | None = None
    ranking: HookRanking | None = None
    draft: Draft | None = None
    rules: DraftRules | None = None  # the per-run rules the draft was checked against
    claims: list[ClaimVerdict] = field(default_factory=list)  # last fact-check, claim by claim
    problems: list[str] = field(default_factory=list)  # what blocks approval of a held draft
    notes: list[str] = field(default_factory=list)
    email: FoundEmail | None = None  # where to send it, when known


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


def _same_fact(claim: str) -> str:
    """Claims that differ only in case, spacing or punctuation are the same fact."""
    return " ".join(re.sub(r"[^\w\s]", " ", claim.casefold()).split())


def _shortlist(
    ledger: list[Evidence], brief: MergedBrief, today: date, limit: int
) -> list[Evidence]:
    """Pick the facts worth spending AI calls on, using only what code already knows: campaign
    priority, freshness within the signal's window, person before company, source strength,
    then age; at most MAX_PER_PAGE from any one page, and each fact only once."""

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
    seen: set[str] = set()
    for e in sorted((e for e in ledger if veto_reason(e) is None), key=key):
        if per_page.get(e.url, 0) >= MAX_PER_PAGE or _same_fact(e.claim) in seen:
            continue
        per_page[e.url] = per_page.get(e.url, 0) + 1
        seen.add(_same_fact(e.claim))
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
    rules: DraftRules,
    hook: Evidence,
    ledger: list[Evidence],
    brief: MergedBrief,
    today: date,
    contact: Contact,
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
        greet=contact.person_name.split()[0] if contact.person_name else None,
    )


async def _best_draft(writer: Writer, request: DraftRequest) -> Draft:
    """S6: draft DRAFT_VARIANTS variants; keep the one with the fewest rule violations. A variant
    that fails (busy models) is skipped as long as one succeeds."""
    results = await asyncio.gather(
        *(writer.draft(replace(request, variant=i)) for i in range(DRAFT_VARIANTS)),
        return_exceptions=True,
    )
    drafts = [r for r in results if isinstance(r, Draft)]
    if not drafts:  # every variant failed: surface the first reason
        raise next(r for r in results if isinstance(r, BaseException))
    return min(drafts, key=lambda d: len(check_draft(d.body, request.rules)))


def _problems(draft: Draft, verdicts: list[ClaimVerdict], rules: DraftRules) -> list[str]:
    unsupported = [
        f"Unsupported claim: {v.claim}" + (f" ({v.reason})" if v.reason else "")
        for v in verdicts
        if v.verdict is not Entailment.SUPPORTED
    ]
    return unsupported + [f"Rule {v.kind}: {v.detail}" for v in check_draft(draft.body, rules)]


UNCHECKED = (
    "The fact-check could not match any sentence to the evidence. Check the opening line "
    "against the sources yourself before approving."
)


NOT_CHECKED = (
    "This draft was not fact-checked because the free AI models were busy. Check each claim "
    "against the sources before approving."
)


def _grounded(verdicts: list[ClaimVerdict]) -> bool:
    return any(v.evidence_id and v.verdict is Entailment.SUPPORTED for v in verdicts)


@dataclass(slots=True)
class _Checked:
    draft: Draft
    problems: list[str]
    verdicts: list[ClaimVerdict]
    busy: bool = False  # models were too busy to finish checking or fixing


async def _fact_check(draft: Draft, request: DraftRequest, deps: PipelineDeps) -> _Checked:
    """S7: check claim by claim; send problems back for a minimal fix, at most MAX_REVISIONS.

    A draft is never thrown away because models are busy: if checking or fixing can't run, the
    draft is returned with its known problems (or a "not fact-checked" warning) for the rep.
    """
    for attempt in range(MAX_REVISIONS + 1):
        try:
            verdicts = await deps.fact_checker.check(draft, request)
            problems = _problems(draft, verdicts, request.rules)
            if not problems and not _grounded(verdicts):
                # A check that tied nothing to evidence is not a pass: ask once more, then say so.
                verdicts = await deps.fact_checker.check(draft, request)
                problems = _problems(draft, verdicts, request.rules)
                if not problems and not _grounded(verdicts):
                    problems = [UNCHECKED]
                return _Checked(draft, problems, verdicts)
        except LLMUnavailable:
            rules = [f"Rule {v.kind}: {v.detail}" for v in check_draft(draft.body, request.rules)]
            return _Checked(draft, [NOT_CHECKED, *rules], [], busy=True)
        if not problems or attempt == MAX_REVISIONS:
            return _Checked(draft, problems, verdicts)
        try:
            draft = await deps.writer.revise(draft, problems, request)
        except LLMUnavailable:
            return _Checked(draft, problems, verdicts, busy=True)
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

    def _send(
        self, stage: str, status: EventStatus, summary: str, items: tuple[str, ...] = ()
    ) -> None:
        if self._sink is not None:
            self._sink(StageEvent(stage, status, summary, items))

    def started(self, stage: str) -> None:
        self._stage = stage
        self._send(stage, "started", "")

    def progress(self, summary: str, items: tuple[str, ...] = ()) -> None:
        self._send(self._stage, "progress", summary, items)

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
        # Never write to someone we can't confirm: ask the rep. They can pick a suggested
        # person who does work there, name someone else, or write to this name anyway.
        named = prospect.person_name
        outcome.notes.append("person_not_found" if named else "no_contact_found")
        outcome.state = RunState.NEEDS_CLARIFICATION
        events.done(_describe_identity(identity, named=named, company=prospect.company_name))
        return
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
    research = outcome.research = await run_research(
        target,
        deps.research,
        budget,
        on_round=lambda r: events.progress(
            f"Round {r.number + 1}: {r.searches_used} searches, {r.pages_used} pages read, "
            f"{r.verified} verified facts so far",
            r.new_claims[:MAX_PROGRESS_ITEMS],
        ),
    )
    events.done(
        f"{_count(len(research.ledger), 'verified fact')} from "
        f"{_count(research.pages_used, 'page')} in {_count(research.rounds, 'round')}; "
        f"{STOP_REASONS.get(research.stop_reason, research.stop_reason)}"
    )

    events.started("verify")
    shortlist = _shortlist(research.ledger, brief, today, max_hook_candidates)
    ledger = research.ledger = await _verify(research.ledger, shortlist, deps.entailment)
    unsupported = sum(e.entailment is Entailment.UNSUPPORTED for e in ledger)
    events.done(
        f"{_count(len(shortlist), 'claim')} checked; "
        + (f"{unsupported} not supported by their quote" if unsupported else "all supported")
    )

    events.started("score")
    picked = {e.id for e in shortlist}
    eligible = [e for e in ledger if e.id in picked and veto_reason(e) is None]
    samples = await _score(eligible, deps.scorer, brief)
    ranking = outcome.ranking = rank_hooks(ledger, samples, weights=brief.hook_weights)
    events.done(
        f"Best opener scores {_one_decimal(ranking.ranked[0].total)} of 5: "
        f"{ranking.ranked[0].evidence.claim}"
        if ranking.ranked
        else "Nothing usable as an opener"
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
        rules=_rules_for(rules, top[0].evidence, ledger, brief, today, contact),
        today=today,
    )
    outcome.rules = request.rules
    draft = await _best_draft(deps.writer, request)
    events.done(f"Kept the better of {DRAFT_VARIANTS} drafts ({len(draft.body.split())} words)")

    events.started("fact_check")
    checked = await _fact_check(draft, request, deps)
    outcome.draft, outcome.problems, outcome.claims = (
        checked.draft,
        checked.problems,
        checked.verdicts,
    )
    if checked.busy:
        outcome.notes.append("models_busy")
    events.done(
        f"{_count(len(outcome.problems), 'problem')} left to fix"
        if outcome.problems
        else "Every claim is backed by evidence"
    )
    outcome.state = RunState.DRAFT_HELD if outcome.problems else RunState.DRAFT_READY
    try:
        outcome.email = await _find_email(events, prospect, contact, research, deps.email_finder)
    except EmailLookupFailed as exc:
        outcome.notes.append("email_lookup_failed")
        events.done(f"The email finder did not answer ({exc}); add the address yourself")


async def _find_email(
    events: _Events,
    prospect: ProspectInput,
    contact: Contact,
    research: ResearchResult,
    finder: EmailFinder | None,
) -> FoundEmail | None:
    """The contact's address: the rep's if they gave one for this person; otherwise the pages
    research already read, then the finder."""
    events.started("email")
    if prospect.email and _same_person(prospect.person_name, contact.person_name):
        events.done(f"{prospect.email}, as you gave it")
        return FoundEmail(prospect.email, "rep")
    if research.emails:
        seen = research.emails[0]
        events.done(f"{seen.address}, published on {_host(seen.url)}")
        return FoundEmail(seen.address, "page", url=seen.url)
    found = await finder.find(contact) if finder else None
    if found:
        events.done(f"{found.address}, from the email finder ({found.confidence}% confident)")
        return found
    events.done("No address found")
    return None


def _same_person(given: str | None, writing_to: str | None) -> bool:
    """False when the rep picked someone else after a pause: their address is not this one's."""
    return not given or " ".join(given.casefold().split()) == " ".join(
        (writing_to or "").casefold().split()
    )


def _host(url: str) -> str:
    return urlsplit(url).hostname or url


def _describe_identity(identity: Identity, *, named: str | None = None, company: str = "") -> str:
    c = identity.contact
    if identity.status is IdentityStatus.NOT_FOUND:
        found = _count(len(identity.candidates), "person", "people")
        if named:
            return f"Couldn't confirm {named} at {company}; {found} who do work there"
        return f"Nobody found in the buyer's roles; {found} suggested"
    if identity.status is IdentityStatus.CONFIRMED and c:
        return f"Confirmed {c.person_name or 'the company'} at {c.company_name}"
    if identity.status is IdentityStatus.MOVED and c:
        return f"Now at {c.company_name}"
    if identity.status is IdentityStatus.AMBIGUOUS:
        return f"{_count(len(identity.candidates), 'possible match', 'possible matches')} found"
    if identity.status is IdentityStatus.SUGGESTED:
        return f"Suggested {_count(len(identity.candidates), 'contact')} to choose from"
    return "Identity checked"


def _one_decimal(x: float) -> str:
    """Round the way the web app's toFixed(1) does (exact value, ties up), so the timeline and
    the scoreboard never disagree: 4.25 is 4.3 in both, not 4.2 here and 4.3 there."""
    return str(Decimal(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _count(n: int, singular: str, plural: str | None = None) -> str:
    return f"{n} {singular if n == 1 else plural or singular + 's'}"


STOP_REASONS = {
    "coverage_met": "every signal type covered",
    "sufficient": "no more searching needed",
    "budget": "search budget reached",
    "max_rounds": "round limit reached",
    "diminishing_returns": "nothing new was turning up",
    "no_new_queries": "no new leads to search",
}
