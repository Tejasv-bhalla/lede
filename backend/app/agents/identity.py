"""Identity resolution (SYSTEM_DESIGN.md §4): is this the right person, still at this company?

The model only proposes; code keeps the guardrails. Every person it names must be backed by a
quote that really appears in the numbered search result it cites, and a "moved" verdict without
such proof falls back to "confirmed" rather than stopping a run on a hunch.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from app.agents.schemas import IdentityOut, PersonOut, SuggestionOut
from app.context.merge import MergedBrief
from app.domain.models import ProspectInput
from app.domain.models import SignalCategory as Cat
from app.pipeline.ports import Contact, Identity, IdentityStatus
from app.policy.quotes import verify_quote
from app.providers.llm_router import LLMRouter
from app.research.ports import PlannedQuery, ResearchTarget, Searcher, SearchHit

PROMPT_VERSION = "identity-v4"
MAX_RESULTS = 12
TITLES_PER_QUERY = 4
MAX_TITLE_QUERIES = 2
# When nobody in the buyer's roles shows up, the top leader can still route the email.
LEADER_TITLES = ("CEO", "President", "Founder")


def suggestion_queries(company: str, titles: list[str]) -> list[str]:
    """Every buyer title, a few per query, then one search for the company's leaders. Plain
    words, not OR: the engines treat OR loosely and drift into unrelated news."""
    chunks = [titles[i : i + TITLES_PER_QUERY] for i in range(0, len(titles), TITLES_PER_QUERY)]
    queries = [f'"{company}" {" ".join(c)}' for c in chunks[:MAX_TITLE_QUERIES]]
    return [*queries, f'"{company}" leadership team {" ".join(LEADER_TITLES)}']


def _numbered(hits: list[SearchHit]) -> str:
    return "\n".join(
        f"[{i}] {h.title}\n    {h.url}\n    {h.snippet[:400]}" for i, h in enumerate(hits, 1)
    )


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


class SearchResolver:
    def __init__(self, router: LLMRouter, searcher: Searcher) -> None:
        self._router, self._searcher = router, searcher

    async def _search(
        self, queries: list[str], target: ResearchTarget, *, news: bool | None = None
    ) -> list[SearchHit]:
        results = await asyncio.gather(
            *(
                self._searcher.search(PlannedQuery(Cat.ROLE_CHANGE, q, news=news), target)
                for q in queries
            ),
            return_exceptions=True,
        )
        # Interleave so every query gets a share of the result slots, not just the first one.
        lists = [r for r in results if not isinstance(r, BaseException)]
        hits: dict[str, SearchHit] = {}
        for rank in range(max((len(r) for r in lists), default=0)):
            for r in lists:
                if rank < len(r):
                    hits.setdefault(r[rank].url, r[rank])
        return list(hits.values())[:MAX_RESULTS]

    def _proven(self, person: PersonOut | None, hits: list[SearchHit]) -> Contact | None:
        """A contact only if the cited result really contains the cited quote."""
        if person is None or not 1 <= person.result <= len(hits):
            return None
        hit = hits[person.result - 1]
        if not verify_quote(person.quote, f"{hit.title} {hit.snippet}").verified:
            return None
        return Contact(
            company_name=person.company_name,
            person_name=person.person_name,
            title=person.title,
            evidence_url=hit.url,
            evidence_quote=person.quote,
        )

    def _domain(self, proposed: str | None, given: str | None, hits: list[SearchHit]) -> str | None:
        if given:
            return given
        proposed = (proposed or "").removeprefix("www.").strip("/ ").casefold()
        return proposed if proposed and any(_host(h.url) == proposed for h in hits) else None

    async def resolve(self, prospect: ProspectInput, brief: MergedBrief) -> Identity:
        target = ResearchTarget(
            company_name=prospect.company_name,
            company_domain=prospect.company_domain,
            person_name=prospect.person_name,
            title=prospect.title,
            objective=brief.objective,
        )
        if prospect.person_name:
            return await self._person(prospect, target, brief)
        people = await self._people_at(prospect, target, brief)
        if not people:
            return Identity(IdentityStatus.NOT_FOUND)
        return Identity(IdentityStatus.SUGGESTED, candidates=people)

    async def _not_found(
        self, prospect: ProspectInput, target: ResearchTarget, brief: MergedBrief
    ) -> Identity:
        """The named person can't be confirmed: offer people who do work there instead."""
        return Identity(
            IdentityStatus.NOT_FOUND, candidates=await self._people_at(prospect, target, brief)
        )

    async def _person(
        self, prospect: ProspectInput, target: ResearchTarget, brief: MergedBrief
    ) -> Identity:
        name, company = prospect.person_name, prospect.company_name
        hits = await self._search(
            [
                f'"{name}" "{company}"',
                f'"{name}" {prospect.title or ""} {company}'.replace("  ", " "),
            ],
            target,
        )
        if not hits:
            return await self._not_found(prospect, target, brief)
        prompt = f"""Check a sales prospect's identity from web search results.

Prospect as given by the salesperson: {name}, {prospect.title or "title unknown"}, at {company}
{f"LinkedIn URL given (identifier only): {prospect.linkedin_url}" if prospect.linkedin_url else ""}

Search results:
{_numbered(hits)}

Decide:
- "confirmed": results show {name} works at {company} now. Put them in `match`.
- "moved": a recent result clearly shows {name} now works at a DIFFERENT company. Put the new
  role in `match` (company_name = the new company).
- "ambiguous": several different people named {name} could fit and the results don't say which
  one is at {company}. List up to 3 in `candidates`; give each one's company as the result shows
  it, or "{company}" if the result doesn't say.
- "not_found": nothing reliable about this person.
For every person you name: `result` is the number of the result that shows it, and `quote` is
copied EXACTLY from that result's title or text. Also give the company's own website domain
(like "acme.com") if a result shows it."""
        out = (await self._router.structured("judge", prompt, IdentityOut)).value
        domain = self._domain(out.company_domain, prospect.company_domain, hits)
        match = self._proven(out.match, hits)
        if out.status == "ambiguous":
            candidates = tuple(c for c in (self._proven(p, hits) for p in out.candidates) if c)
            if len(candidates) > 1:
                return Identity(IdentityStatus.AMBIGUOUS, candidates=candidates)
        if out.status == "moved" and match and match.company_name != company:
            return Identity(IdentityStatus.MOVED, contact=match)
        if out.status == "not_found" or match is None:
            # "Confirmed" needs a quote that really shows them there; otherwise we don't know.
            return await self._not_found(prospect, target, brief)
        return Identity(
            IdentityStatus.CONFIRMED,
            contact=Contact(
                company_name=company,
                company_domain=domain,
                person_name=name,
                title=prospect.title or (match.title if match else None),
                evidence_url=match.evidence_url if match else None,
                evidence_quote=match.evidence_quote if match else None,
            ),
        )

    async def _people_at(
        self, prospect: ProspectInput, target: ResearchTarget, brief: MergedBrief
    ) -> tuple[Contact, ...]:
        company = prospect.company_name
        titles = (brief.persona.title_patterns if brief.persona else []) or ["Head of"]
        hits = await self._search(suggestion_queries(company, titles), target, news=False)
        if not hits:
            return ()
        prompt = f"""A salesperson wants to reach someone at {company}. Find who at {company}
matches the roles they want to reach: {", ".join(titles)}.

Search results:
{_numbered(hits)}

Suggest up to 3 people who CURRENTLY work at {company} in or near those roles, best first. If
nobody in those roles is shown, suggest {company}'s top leader ({", ".join(LEADER_TITLES)}) when
a result shows one. Only people the results actually show; never invent a name. For each:
`title` is their job title as the result states it, `result` is the number of the result that
shows it, `quote` copied EXACTLY from that result's
title or text. If nobody fits, return no suggestions. Also give {company}'s own website domain
if a result shows it."""
        out = (await self._router.structured("judge", prompt, SuggestionOut)).value
        domain = self._domain(out.company_domain, prospect.company_domain, hits)
        people = tuple(
            Contact(
                company_name=company,
                company_domain=domain,
                person_name=c.person_name,
                title=c.title,
                evidence_url=c.evidence_url,
                evidence_quote=c.evidence_quote,
            )
            for c in (self._proven(p, hits) for p in out.suggestions)
            if c
        )
        return people
