"""Fetch a web page and keep only what matters: main text, title, publisher and publish date.

Good-citizen rules (SYSTEM_DESIGN.md §3.4): we identify ourselves honestly, obey robots.txt, and
take a refusal (401/403/429/451) as final. The renderer (Jina Reader) is used only for pages that
loaded fine but build their content with JavaScript, never to get around a refusal.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from typing import Any
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from htmldate import find_date
from trafilatura import bare_extraction

from app.research.ports import Page

REFUSALS = frozenset({401, 403, 429, 451})
HTML_TYPES = ("text/html", "application/xhtml+xml")
JINA_URL = "https://r.jina.ai/"


class FetchBlocked(RuntimeError):
    """The site declined (status code or robots.txt). Recorded, never retried another way."""


class FetchFailed(RuntimeError):
    """A network or server error; the research loop records it and moves on."""


@dataclass(frozen=True, slots=True)
class _Extracted:
    text: str
    title: str
    publisher: str
    published_at: date | None


def extract(html: str, url: str) -> _Extracted:
    """CPU-bound: trafilatura for the main text and metadata, htmldate (strict) for the date.

    Strict dating returns None rather than a guess from a copyright line or URL: a wrong date is
    worse than none, because it could license the word "recently" in a draft.
    """
    doc = bare_extraction(html, url=url, with_metadata=True)
    meta: dict[str, Any] = {} if doc is None else doc if isinstance(doc, dict) else doc.as_dict()
    found = find_date(html, url=url, original_date=True, extensive_search=False)
    return _Extracted(
        text=(meta.get("text") or "").strip(),
        title=meta.get("title") or "",
        publisher=meta.get("sitename") or "",
        published_at=date.fromisoformat(found) if found else None,
    )


class PageFetcher:
    """Implements the research loop's `Fetcher` port."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        user_agent: str,
        jina_api_key: str | None = None,
        max_bytes: int = 8_000_000,  # some careers pages ship megabytes of inline script
        min_text_chars: int = 300,
        timeout_s: float = 15.0,
    ) -> None:
        self._client = client
        self._ua = user_agent
        self._jina_key = jina_api_key
        self._max_bytes = max_bytes
        self._min_text = min_text_chars
        self._timeout = timeout_s
        self._robots: dict[str, RobotFileParser | None] = {}

    async def fetch(self, url: str) -> Page | None:
        if not await self._allowed(url):
            raise FetchBlocked(f"robots.txt disallows {url}")
        html = await self._download(url, {"User-Agent": self._ua})
        if html is None:
            return None
        page = await asyncio.to_thread(extract, html, url)
        if len(page.text) < self._min_text:
            page = await self._render(url) or page  # built by JavaScript: let the renderer run it
        if len(page.text) < self._min_text:
            return None
        return Page(
            url=url,
            text=page.text,
            title=page.title,
            published_at=page.published_at,
            publisher=page.publisher,
        )

    async def _download(self, url: str, headers: dict[str, str]) -> str | None:
        try:
            async with self._client.stream(
                "GET", url, headers=headers, follow_redirects=True, timeout=self._timeout
            ) as response:
                if response.status_code in REFUSALS:
                    raise FetchBlocked(f"{response.status_code} from {urlsplit(url).hostname}")
                if response.status_code in (404, 410):
                    return None
                if response.status_code >= 400:
                    raise FetchFailed(f"{response.status_code} from {urlsplit(url).hostname}")
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith(HTML_TYPES):
                    return None
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > self._max_bytes:
                        return None
                return body.decode(response.encoding or "utf-8", errors="replace")
        except httpx.HTTPError as exc:
            raise FetchFailed(f"{type(exc).__name__} fetching {url}") from exc

    async def _render(self, url: str) -> _Extracted | None:
        headers = {"X-Return-Format": "html"}
        if self._jina_key:
            headers["Authorization"] = f"Bearer {self._jina_key}"
        try:
            html = await self._download(JINA_URL + url, headers)
        except (FetchBlocked, FetchFailed):
            return None  # the renderer is a bonus; its failure leaves the plain result
        return await asyncio.to_thread(extract, html, url) if html else None

    async def _allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.netloc
        if host not in self._robots:
            self._robots[host] = await self._load_robots(f"{parts.scheme}://{host}/robots.txt")
        rules = self._robots[host]
        return rules is None or rules.can_fetch(self._ua, url)

    async def _load_robots(self, robots_url: str) -> RobotFileParser | None:
        """None means no usable robots.txt, which by convention allows everything."""
        try:
            response = await self._client.get(
                robots_url, headers={"User-Agent": self._ua}, timeout=self._timeout
            )
        except httpx.HTTPError:
            return None
        if response.status_code != 200:
            return None
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        return rules
