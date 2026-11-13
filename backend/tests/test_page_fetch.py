import gzip
from datetime import date
from pathlib import Path

import httpx
import pytest

from app.providers.fetch import FetchBlocked, PageFetcher

FIXTURES = Path(__file__).parent / "fixtures" / "pages"
UA = "Lede/test"
ARTICLE = "https://www.prnewswire.com/news-releases/ramp-raises-series-f-at-44-billion-valuation-302791103.html"
JOBS = "https://jobs.ashbyhq.com/ramp"


def fixture(name: str) -> str:
    with gzip.open(FIXTURES / f"{name}.html.gz", "rt", encoding="utf-8") as f:
        return f.read()


class Web:
    """A tiny scripted internet: pages by URL, robots.txt by host, and Jina's renderer."""

    def __init__(self, pages: dict[str, httpx.Response], robots: dict[str, str] | None = None):
        self.pages, self.robots = pages, robots or {}
        self.requested: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested.append(url)
        if request.url.path == "/robots.txt":
            body = self.robots.get(request.url.host)
            return httpx.Response(200, text=body) if body else httpx.Response(404)
        if request.url.host == "r.jina.ai":
            assert request.headers["X-Return-Format"] == "html"
            return self.pages.get(
                f"jina:{url.removeprefix('https://r.jina.ai/')}", httpx.Response(502)
            )
        assert request.headers["User-Agent"] == UA  # we never pretend to be a browser
        return self.pages.get(url, httpx.Response(404))


def html(body: str, status: int = 200, content_type: str = "text/html; charset=utf-8"):
    return httpx.Response(status, text=body, headers={"content-type": content_type})


def fetcher(web: Web, **kwargs) -> PageFetcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(web))
    return PageFetcher(client, user_agent=UA, **kwargs)


async def test_an_article_yields_its_main_text_title_publisher_and_publish_date():
    page = await fetcher(Web({ARTICLE: html(fixture("prnewswire_article"))})).fetch(ARTICLE)

    assert page is not None
    assert "Ramp announced a $750 million primary financing round led by ICONIQ" in page.text
    assert "Browse News Releases" not in page.text  # site navigation is stripped
    assert "Cookie" not in page.text
    assert page.title == "Ramp Raises Series F at $44 Billion Valuation"
    assert page.publisher == "Cision PR Newswire"
    assert page.published_at == date(2026, 6, 4)


async def test_a_javascript_rendered_page_is_read_through_the_renderer():
    web = Web({JOBS: html(fixture("ashby_shell")), f"jina:{JOBS}": html(fixture("ashby_rendered"))})
    page = await fetcher(web).fetch(JOBS)

    assert page is not None
    assert "Compliance" in page.text and "New York, NY (HQ)" in page.text
    assert page.published_at is None  # a job board has no publish date; we never guess one


@pytest.mark.parametrize("status", [401, 403, 429, 451])
async def test_a_site_that_refuses_us_is_respected_not_routed_around(status):
    web = Web({ARTICLE: html("<h1>Access denied</h1>", status)})
    with pytest.raises(FetchBlocked, match=str(status)):
        await fetcher(web).fetch(ARTICLE)
    assert not any("r.jina.ai" in u for u in web.requested)


async def test_robots_txt_that_disallows_us_means_the_page_is_never_requested():
    web = Web(
        {ARTICLE: html(fixture("prnewswire_article"))},
        robots={"www.prnewswire.com": "User-agent: *\nDisallow: /news-releases/\n"},
    )
    with pytest.raises(FetchBlocked, match="robots"):
        await fetcher(web).fetch(ARTICLE)
    assert ARTICLE not in web.requested


async def test_documents_that_are_not_web_pages_are_skipped():
    pdf = "https://acme.example/report"
    web = Web({pdf: html("%PDF-1.7 ...", content_type="application/pdf")})
    assert await fetcher(web).fetch(pdf) is None
    assert not any("r.jina.ai" in u for u in web.requested)


async def test_oversized_pages_are_not_downloaded_in_full():
    huge = "https://acme.example/huge"
    web = Web({huge: html("<p>" + "x" * 50_000 + "</p>")})
    assert await fetcher(web, max_bytes=10_000).fetch(huge) is None
