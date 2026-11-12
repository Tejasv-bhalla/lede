"""Decide whether a signal is recent enough to be described as recent (SYSTEM_DESIGN.md §5)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from app.domain.models import SignalCategory as Cat

# Default windows in days; seller profiles may override per category.
DEFAULT_WINDOWS_DAYS: dict[Cat, int] = {
    Cat.ROLE_CHANGE: 120,
    Cat.FUNDING_MNA: 180,
    Cat.HIRING_PATTERN: 60,
    Cat.PRODUCT_LAUNCH: 180,
    Cat.EXPANSION: 180,
    Cat.OWN_CONTENT: 365,
    Cat.PRESS_QUOTE: 365,
}
FALLBACK_WINDOW_DAYS = 180


class Freshness(StrEnum):
    RECENT = "recent"
    STALE = "stale"
    UNDATED = "undated"  # usable only with timeless wording, never "recently"


@dataclass(frozen=True, slots=True)
class Recency:
    freshness: Freshness


def assess_recency(
    category: Cat,
    *,
    published_at: date | None,
    today: date,
    event_date: date | None = None,
    overrides: Mapping[Cat, int] | None = None,
) -> Recency:
    # When the event itself is dated, that date wins: a fresh page about old news is old news.
    when = event_date or published_at
    if when is None:
        return Recency(Freshness.UNDATED)
    window = (overrides or {}).get(category) or DEFAULT_WINDOWS_DAYS.get(
        category, FALLBACK_WINDOW_DAYS
    )
    age = (today - when).days
    return Recency(Freshness.RECENT if age <= window else Freshness.STALE)
