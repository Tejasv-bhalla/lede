"""Classify where a piece of evidence came from, so source quality can be ranked."""

from urllib.parse import urlsplit

from app.domain.models import SourceType

_KNOWN_HOSTS: dict[str, SourceType] = {
    # job boards
    "greenhouse.io": SourceType.JOB_BOARD,
    "lever.co": SourceType.JOB_BOARD,
    "ashbyhq.com": SourceType.JOB_BOARD,
    "workable.com": SourceType.JOB_BOARD,
    "smartrecruiters.com": SourceType.JOB_BOARD,
    # filings
    "sec.gov": SourceType.FILING,
    "companieshouse.gov.uk": SourceType.FILING,
    # aggregators: useful leads, weakest evidence
    "crunchbase.com": SourceType.AGGREGATOR,
    "zoominfo.com": SourceType.AGGREGATOR,
    "rocketreach.co": SourceType.AGGREGATOR,
    "apollo.io": SourceType.AGGREGATOR,
    "owler.com": SourceType.AGGREGATOR,
    "craft.co": SourceType.AGGREGATOR,
    "cbinsights.com": SourceType.AGGREGATOR,
    "pitchbook.com": SourceType.AGGREGATOR,
    # talks and podcasts
    "youtube.com": SourceType.PODCAST_VIDEO,
    "youtu.be": SourceType.PODCAST_VIDEO,
    "podcasts.apple.com": SourceType.PODCAST_VIDEO,
    "open.spotify.com": SourceType.PODCAST_VIDEO,
    # social: leads only, never scraped
    "linkedin.com": SourceType.SOCIAL,
    "x.com": SourceType.SOCIAL,
    "twitter.com": SourceType.SOCIAL,
}


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def classify_source(
    url: str, company_domain: str | None, *, hint: SourceType | None = None
) -> SourceType:
    """Known hosts win; otherwise trust the connector's hint (e.g. a news feed means press)."""
    host = _host(url)
    if company_domain and _on_domain(host, company_domain.removeprefix("www.")):
        return SourceType.FIRST_PARTY
    for known, source_type in _KNOWN_HOSTS.items():
        if _on_domain(host, known):
            return source_type
    return hint or SourceType.UNKNOWN
