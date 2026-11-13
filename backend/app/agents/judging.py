"""Judging roles: does a quote support its claim (S4), how good is a hook (S5), and is every
sentence of a draft backed by evidence (S7)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.agents.schemas import EntailmentOut, FactCheckOut, HookScoreOut
from app.context.merge import MergedBrief
from app.domain.hook_dimensions import HOOK_DIMENSIONS
from app.domain.models import Entailment, Evidence
from app.pipeline.hooks import DimensionScores
from app.pipeline.ports import ClaimVerdict, Draft, DraftRequest
from app.providers.llm_router import LLMRouter

PROMPT_VERSION = "judging-v1"


class LLMEntailment:
    """Uses the checker role: a different model family from the reader that wrote the claim."""

    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def entails(self, evidence: Evidence) -> Entailment:
        prompt = f"""Does the QUOTE fully support the CLAIM? Judge only from the quote, not from
anything you know.

CLAIM: {evidence.claim}
QUOTE: "{evidence.verbatim_quote}"
(Source: {evidence.url})

- "supported": everything the claim says is stated in the quote.
- "partial": the quote supports part of it, but the claim adds something (a number, a date, a
  cause, an exaggeration).
- "unsupported": the quote doesn't say this."""
        out = await self._router.structured("checker", prompt, EntailmentOut)
        return out.value.verdict


class LLMScorer:
    def __init__(self, router: LLMRouter, today: Callable[[], date] = date.today) -> None:
        self._router, self._today = router, today

    async def score(self, evidence: Evidence, brief: MergedBrief) -> DimensionScores:
        persona = brief.persona
        when = evidence.event_date or evidence.published_at
        age = f"{(self._today() - when).days} days ago" if when else "undated"
        prompt = f"""Score one fact as the opening hook of a cold email. Be strict: 3 is ordinary,
5 is rare.

Seller's objective: {brief.objective}
Problems the seller solves: {"; ".join(brief.pains) or "not stated"}
Recipient persona: {persona.title_patterns if persona else "unknown"}, seniority \
{persona.seniority.value if persona else "unknown"}, prefers \
{persona.hook_preference.value if persona else "company"}-level hooks.
Campaign priority for this kind of signal: \
{brief.signal_priorities.get(evidence.category, "not set")}

FACT [{evidence.category.value}, about the {evidence.about.value}]: {evidence.claim}
Quote: "{evidence.verbatim_quote}"
Source: {evidence.url} ({evidence.source_type.value}); happened/published: {age}

Score each from 1 to 5 with a one-line reason:
- offer_relevance: can one honest sentence link this to a problem the seller solves?
- specificity: is it about THIS person/company, not the industry? Would the email fail if
  sent to someone else?
- recency: fresh and still relevant (5) vs old news (1); undated is at most 2.
- persona_fit: does this kind of hook suit the recipient's seniority and preference?
- source_strength: primary source (company site, filing, the person's own words) = 5;
  reputable press = 4; job boards = 3; aggregators or unknown blogs = 1-2.
- closeness: did the person do/say it (5), their team (4), or just the company (2-3)?"""
        out = (await self._router.structured("judge", prompt, HookScoreOut)).value
        dims = {d: getattr(out, d) for d in HOOK_DIMENSIONS}
        return DimensionScores(
            scores={d: float(v.score) for d, v in dims.items()},
            reasons={d: v.reason for d, v in dims.items()},
        )


class LLMFactChecker:
    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def check(self, draft: Draft, request: DraftRequest) -> list[ClaimVerdict]:
        evidence = [request.hook.evidence, *(h.evidence for h in request.alternates)]
        sources = "\n".join(
            f'[{e.id}] {e.claim}\n     quote: "{e.verbatim_quote}"' for e in evidence
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
  evidence says it.
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
