"""Thin adapters from each search API to `SearchHit` (fused in `fusion.py`).

News-type signals (funding, launches, hires...) use each engine's news mode, which also returns
publish dates. Page text is never requested here: we fetch and verify pages ourselves, which is
cheaper and keeps quote verification against the page we actually read.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import Any

from dateutil import parser as dateparser
from ddgs import DDGS
from exa_py import AsyncExa
from tavily import AsyncTavilyClient

from app.domain.models import SignalCategory as Cat
from app.domain.models import SourceType
from app.research.ports import PlannedQuery, ResearchTarget, SearchHit

NEWS_CATEGORIES = frozenset(
    {
        Cat.FUNDING_MNA,
        Cat.LEADERSHIP_HIRE,
        Cat.PRODUCT_LAUNCH,
        Cat.EXPANSION,
        Cat.PARTNERSHIP,
        Cat.STRATEGY_EARNINGS,
        Cat.REGULATORY,
        Cat.ROLE_CHANGE,
        Cat.PRESS_QUOTE,
        Cat.AWARD_OR_SPEAKING,
    }
)
RESULTS_PER_ENGINE = 8


def parse_date(value: Any) -> date | None:
    """Every engine formats dates differently; anything unparseable is treated as undated."""
    if not value:
        return None
    try:
        parsed: datetime = dateparser.parse(str(value))
    except (ValueError, OverflowError):
        return None
    return parsed.date()


def _is_news(query: PlannedQuery) -> bool:
    return query.category in NEWS_CATEGORIES


class TavilyEngine:
    name = "tavily"

    def __init__(self, api_key: str) -> None:
        self._client = AsyncTavilyClient(api_key=api_key)

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        news = _is_news(query)
        response = await self._client.search(
            query.query,
            topic="news" if news else "general",
            time_range="year" if news else None,
            search_depth="basic",  # 1 credit; "advanced" costs 2
            max_results=RESULTS_PER_ENGINE,
        )
        return [
            SearchHit(
                url=r["url"],
                title=r.get("title") or "",
                snippet=r.get("content") or "",
                published_at=parse_date(r.get("published_date")),
                source_hint=SourceType.PRESS if news else None,
                provider=self.name,
            )
            for r in response.get("results", [])
        ]


class ExaEngine:
    name = "exa"

    def __init__(self, api_key: str) -> None:
        self._client = AsyncExa(api_key=api_key)

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        response = await self._client.search(
            query.query,
            num_results=RESULTS_PER_ENGINE,
            contents=False,  # text is fetched by us, not bought from Exa
            category="news" if _is_news(query) else None,
        )
        return [
            SearchHit(
                url=r.url,
                title=r.title or "",
                published_at=parse_date(r.published_date),
                provider=self.name,
            )
            for r in response.results
        ]


class DuckDuckGoEngine:
    """Free and keyless. The library is synchronous, so it runs in a worker thread."""

    name = "ddg"

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        if _is_news(query):
            rows = await asyncio.to_thread(
                DDGS().news, query.query, max_results=RESULTS_PER_ENGINE, timelimit="y"
            )
            return [
                SearchHit(
                    url=r["url"],
                    title=r.get("title") or "",
                    snippet=r.get("body") or "",
                    published_at=parse_date(r.get("date")),
                    source_hint=SourceType.PRESS,
                    provider=self.name,
                )
                for r in rows
            ]
        rows = await asyncio.to_thread(DDGS().text, query.query, max_results=RESULTS_PER_ENGINE)
        return [
            SearchHit(
                url=r["href"],
                title=r.get("title") or "",
                snippet=r.get("body") or "",
                provider=self.name,
            )
            for r in rows
        ]
