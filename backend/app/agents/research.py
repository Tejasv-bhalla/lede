"""AI roles of the research loop: planner, reader and reflector (SYSTEM_DESIGN.md §3.1)."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from rank_bm25 import BM25Okapi

from app.agents.schemas import QueryOut, QueryPlanOut, ReadOut, ReflectionOut
from app.domain.models import NEGATIVE_CATEGORIES, SignalCategory
from app.providers.llm_router import LLMRouter
from app.research.ports import (
    Candidate,
    LedgerView,
    Page,
    PlannedQuery,
    Reflection,
    ResearchTarget,
)

PROMPT_VERSION = "research-v1"
MAX_PASSAGE_CHARS = 6000  # ~1.5K tokens: fits every reader model's free per-minute budget
HOOK_CATEGORIES = ", ".join(c.value for c in SignalCategory if c not in NEGATIVE_CATEGORIES)
NEGATIVE = ", ".join(c.value for c in NEGATIVE_CATEGORIES)


def _who(t: ResearchTarget) -> str:
    person = f"{t.person_name} ({t.title or 'title unknown'}) at " if t.person_name else ""
    domain = f" (website: {t.company_domain})" if t.company_domain else ""
    return f"{person}{t.company_name}{domain}"


def _context(t: ResearchTarget) -> str:
    lines = [f"Prospect: {_who(t)}", f"Seller's objective: {t.objective}"]
    if t.pains:
        lines.append("Problems the seller solves: " + "; ".join(t.pains))
    if t.priorities:
        lines.append("Signals the campaign cares most about: " + ", ".join(t.priorities))
    return "\n".join(lines)


def _queries(items: list[QueryOut]) -> tuple[PlannedQuery, ...]:
    return tuple(PlannedQuery(q.category, q.query, q.goal) for q in items)


def select_passages(text: str, target: ResearchTarget, max_chars: int = MAX_PASSAGE_CHARS) -> str:
    """Keep the paragraphs most about this prospect (BM25), in page order, within budget.

    Quotes are verified against the full page later, so trimming never weakens verification;
    it only keeps long pages inside free-tier token limits.
    """
    if len(text) <= max_chars:
        return text
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    terms = " ".join(
        filter(None, [target.company_name, target.person_name, target.title, *target.pains])
    )
    query = re.findall(r"\w+", terms.casefold())
    scores = BM25Okapi([re.findall(r"\w+", p.casefold()) or [""] for p in paragraphs]).get_scores(
        query
    )
    chosen: set[int] = set()
    used = 0
    for i in sorted(range(len(paragraphs)), key=lambda i: scores[i], reverse=True):
        if used + len(paragraphs[i]) > max_chars:
            continue
        chosen.add(i)
        used += len(paragraphs[i]) + 1
    return "\n".join(paragraphs[i] for i in sorted(chosen))


class LLMPlanner:
    def __init__(self, router: LLMRouter, today: Callable[[], date] = date.today) -> None:
        self._router, self._today = router, today

    async def plan(self, target: ResearchTarget) -> list[PlannedQuery]:
        prompt = f"""You plan web searches to find recent, specific, verifiable facts about a sales
prospect that a salesperson could honestly mention in a first email. Today is {self._today()}.

{_context(target)}

Write 6 to 9 search queries for a web search engine. Rules:
- Cover the campaign's priority signals first, then a spread of: the person's own words
  (podcasts, interviews, talks, posts on the company blog), role changes, funding or
  acquisitions, product launches, hiring for teams relevant to the seller, expansion, partnerships.
- Each query names the company (and the person, for person-level queries); keep queries short
  and specific, the way a skilled researcher types them. Use quotes around full names.
- One query may use site:{target.company_domain or "<company domain>"} to search the company's
  own site.
- Category must be one of: {HOOK_CATEGORIES}.
- Do not search for gossip, family, health or other private matters."""
        out = await self._router.structured("judge", prompt, QueryPlanOut)
        return list(_queries(out.value.queries))


class LLMReader:
    def __init__(self, router: LLMRouter, today: Callable[[], date] = date.today) -> None:
        self._router, self._today = router, today

    async def read(self, page: Page, passages: str, target: ResearchTarget) -> list[Candidate]:
        excerpt = select_passages(passages, target)
        prompt = f"""You extract facts about a sales prospect from one web page.
Today is {self._today()}.

{_context(target)}

Page: {page.url}
Title: {page.title or "unknown"}
Published: {page.published_at or "unknown"}
---
{excerpt}
---

List up to 8 facts from this page that are about the prospect (the person, or the company).
Rules:
- quote: copy the supporting text from the page EXACTLY, character for character, 20-300
  characters. Never paraphrase inside the quote, never join separate sentences.
- claim: one plain sentence stating only what the quote says. No guesses, no adjectives the
  page doesn't use, no implications.
- about: "person" if it is about {target.person_name or "the named person"} specifically,
  "company" if about {target.company_name}, "market" if about the industry.
- event_date: when the event happened, only if the page states it (YYYY-MM-DD); else null.
- category: one of {HOOK_CATEGORIES}; if the fact is bad news use one of: {NEGATIVE}.
- Skip facts about other companies or people with a similar name.
- If the page has nothing about the prospect, return an empty list."""
        out = await self._router.structured("reader", prompt, ReadOut)
        return [
            Candidate(s.category, s.about, s.claim, s.quote, event_date=s.event_date)
            for s in out.value.signals
        ]


class LLMReflector:
    def __init__(self, router: LLMRouter, today: Callable[[], date] = date.today) -> None:
        self._router, self._today = router, today

    async def reflect(
        self, target: ResearchTarget, ledger: LedgerView, rounds_left: int
    ) -> Reflection:
        found = "\n".join(f"- [{c.value}, {a.value}] {claim}" for _, c, a, claim in ledger.items)
        prompt = f"""You lead research on a sales prospect. Today is {self._today()}.

{_context(target)}

Verified facts found so far:
{found or "(none yet)"}

Decide whether this is enough to write a specific, honest first email: at least one fact
about the person or a recent, specific company event that connects to the seller's problems.
If not, propose up to {min(4, 2 + rounds_left)} NEW search queries that target what is missing
(different wording or sources than before; e.g. the person's interviews or podcasts, the
company's blog or newsroom, job posts). {rounds_left} search round(s) remain.
Category must be one of: {HOOK_CATEGORIES}."""
        out = await self._router.structured("judge", prompt, ReflectionOut)
        r = out.value
        return Reflection(
            is_sufficient=r.is_sufficient,
            follow_up=_queries(r.follow_up),
            missing=tuple(r.missing),
            rationale=r.rationale,
        )
