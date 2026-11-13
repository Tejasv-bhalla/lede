"""Judging roles: does a quote support its claim (S4), how good is a hook (S5), and is every
sentence of a draft backed by evidence (S7)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from datetime import date

from app.agents.schemas import (
    EntailmentBatchOut,
    FactCheckOut,
    HookScoreBatchOut,
    HookScoreOut,
)
from app.context.merge import MergedBrief
from app.domain.hook_dimensions import HOOK_DIMENSIONS
from app.domain.models import Entailment, Evidence
from app.pipeline.hooks import DimensionScores
from app.pipeline.ports import ClaimVerdict, Draft, DraftRequest
from app.providers.llm_router import LLMRouter

PROMPT_VERSION = "judging-v4"


BATCH = 12  # items per call: one call covers a Standard shortlist; instructions sent once


def _chunks[T](items: Sequence[T]) -> list[Sequence[T]]:
    return [items[i : i + BATCH] for i in range(0, len(items), BATCH)]


class LLMEntailment:
    """Uses the checker role: a different model family from the reader that wrote the claims."""

    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def entails(self, items: Sequence[Evidence]) -> list[Entailment | None]:
        parts = await asyncio.gather(*(self._batch(chunk) for chunk in _chunks(items)))
        return [v for part in parts for v in part]

    async def _batch(self, items: Sequence[Evidence]) -> list[Entailment | None]:
        verdicts = await self._ask(items)
        missing = [e for e in items if e.id not in verdicts]
        if missing:  # the model skipped some: ask once more for just those
            verdicts |= await self._ask(missing)
        return [verdicts.get(e.id) for e in items]

    async def _ask(self, items: Sequence[Evidence]) -> dict[str, Entailment]:
        listed = "\n".join(
            f'[{e.id}] CLAIM: {e.claim}\n      QUOTE: "{e.verbatim_quote}"' for e in items
        )
        prompt = f"""For each item, does the QUOTE fully support the CLAIM? Judge each one only from
its own quote, not from the other items or anything you know.

{listed}

- "supported": everything the claim says is stated in the quote.
- "partial": the quote supports part of it, but the claim adds something (a number, a date, a
  cause, an exaggeration).
- "unsupported": the quote doesn't say this.
Answer for every id, using the id exactly as written (e.g. "{items[0].id}")."""
        out = (await self._router.structured("checker", prompt, EntailmentBatchOut)).value
        return {normalise_id(v.id): v.verdict for v in out.verdicts}


class LLMScorer:
    def __init__(self, router: LLMRouter, today: Callable[[], date] = date.today) -> None:
        self._router, self._today = router, today

    async def score(self, items: Sequence[Evidence], brief: MergedBrief) -> list[DimensionScores]:
        parts = await asyncio.gather(*(self._batch(chunk, brief) for chunk in _chunks(items)))
        return [s for part in parts for s in part]

    def _fact(self, e: Evidence, brief: MergedBrief) -> str:
        when = e.event_date or e.published_at
        age = f"{(self._today() - when).days} days ago" if when else "undated"
        priority = brief.signal_priorities.get(e.category, "not set")
        return (
            f"[{e.id}] ({e.category.value}, about the {e.about.value}; campaign priority "
            f'{priority}) {e.claim}\n      quote: "{e.verbatim_quote[:220]}"\n'
            f"      source: {e.url} ({e.source_type.value}); happened/published {age}"
        )

    async def _batch(self, items: Sequence[Evidence], brief: MergedBrief) -> list[DimensionScores]:
        scored = await self._ask(items, brief)
        missing = [e for e in items if e.id not in scored]
        if missing:  # the model skipped some: ask once more for just those
            scored |= await self._ask(missing, brief)
        return [_dimensions(scored.get(e.id)) for e in items]

    async def _ask(self, items: Sequence[Evidence], brief: MergedBrief) -> dict[str, HookScoreOut]:
        persona = brief.persona
        facts = "\n".join(self._fact(e, brief) for e in items)
        prompt = f"""Score each fact as the opening hook of a cold email. Be strict: 3 is ordinary,
5 is rare. Use the same scale across all facts.

Seller's objective: {brief.objective}
Problems the seller solves: {"; ".join(brief.pains) or "not stated"}
Recipient persona: {persona.title_patterns if persona else "unknown"}, seniority \
{persona.seniority.value if persona else "unknown"}, prefers \
{persona.hook_preference.value if persona else "company"}-level hooks.

FACTS:
{facts}

For every id, score each dimension from 1 to 5, then give ONE short reason for the fact:
- offer_relevance: can one honest sentence link this to a problem the seller solves?
- specificity: is it about THIS person/company, not the industry? Would the email fail if
  sent to someone else?
- recency: fresh and still relevant (5) vs old news (1); undated is at most 2.
- persona_fit: does this kind of hook suit the recipient's seniority and preference?
- source_strength: primary source (company site, filing, the person's own words) = 5;
  reputable press = 4; job boards = 3; aggregators or unknown blogs = 1-2.
- closeness: did the person do/say it (5), their team (4), or just the company (2-3)?"""
        out = (await self._router.structured("judge", prompt, HookScoreBatchOut)).value
        return {normalise_id(item.id): item for item in out.items}


def normalise_id(raw: str) -> str:
    """Models write ids as "e2", "[e2]", "E2" or just "2"; all mean evidence e2."""
    cleaned = raw.strip().strip("[]()").strip().lower()
    return f"e{cleaned}" if cleaned.isdigit() else cleaned


def _dimensions(item: HookScoreOut | None) -> DimensionScores:
    if item is None:  # the model skipped it: lowest scores, so it can't win by omission
        return DimensionScores(
            scores=dict.fromkeys(HOOK_DIMENSIONS, 1.0), reasons={"overall": "not scored"}
        )
    return DimensionScores(
        scores={d: float(getattr(item, d)) for d in HOOK_DIMENSIONS},
        reasons={"overall": item.reason},
    )


class LLMFactChecker:
    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def check(self, draft: Draft, request: DraftRequest) -> list[ClaimVerdict]:
        evidence = [request.hook.evidence, *(h.evidence for h in request.alternates)]
        sources = "\n".join(
            f'[{e.id}] {e.claim}\n     quote: "{e.verbatim_quote}"\n'
            f"     dated: {e.event_date or e.published_at or 'undated'}"
            for e in evidence
        )
        approved = "\n".join(f"- {c.text}" for c in request.brief.claims) or "(none)"
        prompt = f"""Fact-check a sales email sentence by sentence. You did not write it.

EMAIL SUBJECT: {draft.subject}
EMAIL BODY:
{draft.body}

EVIDENCE about the prospect (the only facts the email may state about them):
{sources}

APPROVED CLAIMS about the seller's product (the only product claims allowed):
{approved}

Split the email into atomic claims. For each:
- kind "prospect_fact": states something about the prospect or their company. Give the
  evidence_id that supports it; "supported" only if that evidence quote says it, including any
  numbers, dates and names exactly; "partial" if it stretches or adds; "unsupported" if no
  evidence says it. Today is {request.today.isoformat()}: a time phrase such as "In March" or
  "Last November" is supported when it matches the evidence's date.
- kind "seller_claim": states something about the seller's product. "supported" only if it
  matches an approved claim.
- kind "other": greetings, questions, the ask; verdict "supported".
Quote each claim using the email's own words."""
        out = (await self._router.structured("checker", prompt, FactCheckOut)).value
        return [
            ClaimVerdict(c.claim, c.verdict, c.evidence_id, c.reason)
            for c in out.claims
            if c.kind != "other"
        ]
