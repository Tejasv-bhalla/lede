"""Rule-based floor for sensitive signals. Anything flagged here can never become a hook.

The AI sensitivity classifier is a second layer on top; this screen guarantees the obvious cases
are caught even when the model mislabels a story's category.
"""

import re

from app.domain.models import NEGATIVE_CATEGORIES, Sensitivity, SignalCategory


def _pattern(*terms: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(terms) + r")\b", re.IGNORECASE)


_NEGATIVE = _pattern(
    r"lay(?:s|ing)? off",
    r"laid off",
    r"layoffs?",
    r"redundanc(?:y|ies)",
    r"job cuts?",
    r"downsiz\w*",
    r"lawsuits?",
    r"class action",
    r"su(?:ed|ing)",
    r"litigation",
    r"data breach",
    r"breach(?:ed)?",
    r"hack(?:ed)?",
    r"ransomware",
    r"bankrupt\w*",
    r"insolven\w*",
    r"passed away",
    r"died",
    r"death",
    r"funeral",
    r"scandal",
    r"fraud",
    r"investigation",
    r"fined",
)
_PERSONAL = _pattern(
    r"maternity",
    r"paternity",
    r"parental leave",
    r"pregnan\w*",
    r"birth of",
    r"wedding",
    r"married",
    r"divorce\w*",
    r"illness",
    r"diagnos\w*",
    r"cancer",
    r"surgery",
    r"my (?:wife|husband|partner|son|daughter|kids|children|family)",
    r"(?:his|her|their) (?:wife|husband|partner|son|daughter|kids|children)",
)


def screen_sensitivity(category: SignalCategory, text: str) -> Sensitivity:
    if category in NEGATIVE_CATEGORIES or _NEGATIVE.search(text):
        return Sensitivity.NEGATIVE_NEWS
    if _PERSONAL.search(text):
        return Sensitivity.PERSONAL
    return Sensitivity.NONE
