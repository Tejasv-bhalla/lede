"""The writer role: one short, specific, honest first email, and minimal fixes (S6, S7)."""

from __future__ import annotations

from collections.abc import Sequence

from app.agents.schemas import DraftOut
from app.pipeline.hooks import RankedHook
from app.pipeline.ports import Draft, DraftRequest
from app.providers.llm_router import LLMRouter

PROMPT_VERSION = "writer-v2"

RECENT_OK = "You may say it is recent."
NOT_RECENT = (
    "Do NOT call it recent, new or just announced, and don't congratulate on timing: "
    "it is not recent enough."
)

# Best-of-N variants differ in framing, not just sampling, so the two drafts genuinely compete.
VARIANT_STYLE = (
    "Open with the specific observation itself, stated plainly.",
    "Open with what the observation likely means for their work, then name the observation.",
)


def _evidence(hook: RankedHook) -> str:
    e = hook.evidence
    when = e.event_date or e.published_at
    return (
        f'[{e.id}] {e.claim}\n     quote: "{e.verbatim_quote}"\n'
        f"     source: {e.url} ({e.source_type.value}), dated {when or 'undated'}"
    )


def _brief(r: DraftRequest) -> str:
    b, c = r.brief, r.contact
    greeting = "" if c.person_name else ' (no named person: start with "Hi,")'
    claims = "\n".join(f"- {cl.text}" for cl in b.claims) or "- (none: make no product claims)"
    never = "; ".join(r.rules.never_claims) or "none"
    banned = "; ".join(r.rules.banned_phrases)
    return f"""RECIPIENT: {c.person_name or "(no named person: write to the role)"}, \
{c.title or "title unknown"}, at {c.company_name}
SELLER'S OBJECTIVE: {b.objective}
PROBLEMS THE SELLER SOLVES: {"; ".join(b.pains) or "not stated"}
APPROVED PRODUCT CLAIMS (use at most one, in your own words, nothing beyond it):
{claims}

HOOK (the reason for writing; cite its id):
{_evidence(r.hook)}
OTHER VERIFIED FACTS (optional, cite if used):
{chr(10).join(_evidence(h) for h in r.alternates) or "(none)"}

RULES:
- You are writing TO the recipient. Start with their first name and a comma{greeting}. Refer
  to their company as "you", "your team" or by name, never as a third party they might not
  know about (not "{c.company_name} announced...", but "your team announced...").
- At most {r.rules.max_words} words, 3-4 short sentences, plain and warm. No buzzwords.
- Structure: the observation; why it made you think of them; one line linking to the seller's
  product using an approved claim; a low-pressure question as the ask.
- The ask must match the seller's objective exactly. Don't invent extras (other attendees,
  events, resources, discounts). Don't assume their problems: say what is common for teams
  like theirs, or ask.
- State only what the cited quotes say. Do not invent numbers, results, customers or dates.
- {RECENT_OK if r.rules.recency_allowed else NOT_RECENT}
- Never mention family, health or private matters. No links. No "I hope this finds you well".
- Never say: {never}. Avoid these phrases: {banned}.
- Subject: 2-6 plain words, no numbers, no hype."""


class LLMWriter:
    def __init__(self, router: LLMRouter) -> None:
        self._router = router

    async def draft(self, request: DraftRequest) -> Draft:
        style = VARIANT_STYLE[request.variant % len(VARIANT_STYLE)]
        prompt = f"""Write the first cold email to a prospect.

{_brief(request)}
- {style}

Return the subject, the body (no signature, no footer), and the evidence ids you relied on."""
        return self._as_draft((await self._router.structured("writer", prompt, DraftOut)).value)

    async def revise(self, draft: Draft, problems: Sequence[str], request: DraftRequest) -> Draft:
        listed = "\n".join(f"- {p}" for p in problems)
        prompt = f"""Fix this cold email with the SMALLEST possible edit. Change or delete only the
parts with problems; keep everything else word for word.

SUBJECT: {draft.subject}
BODY:
{draft.body}

PROBLEMS:
{listed}

{_brief(request)}"""
        return self._as_draft((await self._router.structured("writer", prompt, DraftOut)).value)

    @staticmethod
    def _as_draft(out: DraftOut) -> Draft:
        return Draft(
            subject=out.subject.strip(), body=out.body.strip(), citations=tuple(out.citations)
        )
