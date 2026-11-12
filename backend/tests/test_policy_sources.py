from app.domain.models import SourceType
from app.policy.sources import classify_source


def test_page_on_the_companys_own_domain_is_first_party():
    assert classify_source("https://www.acme.com/blog/launch", "acme.com") is SourceType.FIRST_PARTY


def test_lookalike_domains_are_not_first_party():
    assert classify_source("https://notacme.com/news", "acme.com") is not SourceType.FIRST_PARTY
    assert classify_source("https://acme.com.evil.io/x", "acme.com") is not SourceType.FIRST_PARTY


def test_unknown_domain_uses_the_connectors_hint():
    url = "https://www.fintechtimes.example/acme-raises"
    assert classify_source(url, "acme.com", hint=SourceType.PRESS) is SourceType.PRESS
    assert classify_source(url, "acme.com") is SourceType.UNKNOWN


def test_video_podcast_and_social_hosts_are_recognised():
    assert classify_source("https://www.youtube.com/watch?v=x", None) is SourceType.PODCAST_VIDEO
    assert classify_source("https://podcasts.apple.com/p/1", None) is SourceType.PODCAST_VIDEO
    assert classify_source("https://www.linkedin.com/posts/x", None) is SourceType.SOCIAL


def test_known_job_boards_filings_and_aggregators_are_recognised():
    assert classify_source("https://boards.greenhouse.io/acme/jobs/1", "acme.com") is (
        SourceType.JOB_BOARD
    )
    assert classify_source("https://www.sec.gov/Archives/x.htm", "acme.com") is SourceType.FILING
    assert classify_source("https://www.crunchbase.com/organization/acme", "acme.com") is (
        SourceType.AGGREGATOR
    )
