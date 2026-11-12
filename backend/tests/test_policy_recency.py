from datetime import date

from app.domain.models import SignalCategory as Cat
from app.policy.recency import Freshness, assess_recency

TODAY = date(2026, 11, 12)


def test_funding_announced_a_month_ago_is_recent():
    result = assess_recency(Cat.FUNDING_MNA, published_at=date(2026, 10, 13), today=TODAY)
    assert result.freshness is Freshness.RECENT


def test_funding_announced_over_a_year_ago_is_stale():
    result = assess_recency(Cat.FUNDING_MNA, published_at=date(2025, 9, 1), today=TODAY)
    assert result.freshness is Freshness.STALE


def test_signal_without_any_date_is_undated():
    result = assess_recency(Cat.PRODUCT_LAUNCH, published_at=None, today=TODAY)
    assert result.freshness is Freshness.UNDATED


def test_old_event_republished_recently_is_stale():
    result = assess_recency(
        Cat.FUNDING_MNA,
        published_at=date(2026, 11, 1),
        event_date=date(2024, 3, 15),
        today=TODAY,
    )
    assert result.freshness is Freshness.STALE


def test_profile_window_override_replaces_the_default():
    # 60 days is inside the 120-day default but outside the seller's 30-day override.
    result = assess_recency(
        Cat.ROLE_CHANGE,
        published_at=date(2026, 9, 13),
        today=TODAY,
        overrides={Cat.ROLE_CHANGE: 30},
    )
    assert result.freshness is Freshness.STALE
