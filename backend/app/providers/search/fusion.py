"""Merge several search providers into one ranked list (SYSTEM_DESIGN.md §3.3).

Reciprocal rank fusion: a page's score is the sum of 1 / (k + rank) over the providers that
found it, so agreement between independent engines beats any single engine's ordering, and no
provider's raw scores need to be comparable. One slow or failing provider never sinks a search.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.research.ports import PlannedQuery, ResearchTarget, SearchHit

RRF_K = 60  # the standard constant; dampens the gap between rank 1 and rank 2

# Hosts we must not read (terms of service) or cannot read without a login.
BLOCKED_HOSTS = (
    "linkedin.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "x.com",
    "twitter.com",
)
UNREADABLE_SUFFIXES = (".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".zip")
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "cmpid")


class SearchProvider(Protocol):
    name: str

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]: ...


class SearchUnavailable(RuntimeError):
    """Every provider failed for this query."""


@dataclass(frozen=True, slots=True)
class ProviderFailure:
    provider: str
    reason: str


def clean_url(url: str) -> str:
    """Drop tracking parameters and the fragment; keep everything that names the page."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(_TRACKING)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def page_key(url: str) -> str:
    """Identity of a page across providers: no scheme, no www, no trailing slash, any case host."""
    parts = urlsplit(clean_url(url))
    host = (parts.hostname or "").removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}?{parts.query}".rstrip("?")


def _readable(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    if any(host == h or host.endswith("." + h) for h in BLOCKED_HOSTS):
        return False
    return not parts.path.lower().endswith(UNREADABLE_SUFFIXES)


def _merge(kept: SearchHit, other: SearchHit) -> SearchHit:
    """Keep the first URL; fill in details the first provider didn't have."""
    return replace(
        kept,
        title=kept.title or other.title,
        snippet=kept.snippet or other.snippet,
        published_at=kept.published_at or other.published_at,
        source_hint=kept.source_hint or other.source_hint,
        provider=f"{kept.provider}+{other.provider}",
    )


class FusedSearcher:
    """Implements the research loop's `Searcher` port on top of several providers."""

    def __init__(
        self,
        providers: Sequence[SearchProvider],
        *,
        max_results: int = 8,
        timeout_s: float = 10.0,  # Tavily and Exa answer in 1-5 s; DuckDuckGo sometimes hangs
    ) -> None:
        self._providers = list(providers)
        self._max_results = max_results
        self._timeout_s = timeout_s
        self.last_failures: list[ProviderFailure] = []

    async def search(self, query: PlannedQuery, target: ResearchTarget) -> list[SearchHit]:
        outcomes = await asyncio.gather(
            *(asyncio.wait_for(p.search(query, target), self._timeout_s) for p in self._providers),
            return_exceptions=True,
        )
        self.last_failures = []
        lists: list[list[SearchHit]] = []
        for provider, outcome in zip(self._providers, outcomes, strict=True):
            if isinstance(outcome, BaseException):
                reason = "timed out" if isinstance(outcome, TimeoutError) else repr(outcome)
                self.last_failures.append(ProviderFailure(provider.name, reason))
            else:
                lists.append(outcome)
        if not lists:
            raise SearchUnavailable(
                "; ".join(f"{f.provider}: {f.reason}" for f in self.last_failures)
            )
        return self._fuse(lists)

    def _fuse(self, lists: list[list[SearchHit]]) -> list[SearchHit]:
        scores: dict[str, float] = {}
        best: dict[str, SearchHit] = {}
        for hits in lists:
            seen_here: set[str] = set()
            for rank, hit in enumerate((h for h in hits if _readable(h.url)), start=1):
                key = page_key(hit.url)
                if key in seen_here:  # a provider listing a page twice gets no extra credit
                    continue
                seen_here.add(key)
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
                if key in best:
                    best[key] = _merge(best[key], hit)
                else:
                    best[key] = replace(hit, url=clean_url(hit.url))
        ranked = sorted(scores, key=lambda k: scores[k], reverse=True)  # stable on ties
        return [best[k] for k in ranked[: self._max_results]]
