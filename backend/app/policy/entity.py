"""Does this page really talk about our prospect / their company? (SYSTEM_DESIGN.md §4)"""

import re

from app.domain.models import About, EntityMatch, SourceType

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", text).casefold()


def _mentions(text: str, name: str) -> bool:
    return re.search(r"\b" + re.escape(_norm(name)) + r"\b", text) is not None


def match_entity(
    about: About,
    page_text: str,
    source_type: SourceType,
    *,
    company_name: str,
    person_name: str | None,
) -> EntityMatch:
    text = _norm(page_text)
    if about is About.PERSON:
        if not person_name:
            return EntityMatch.AMBIGUOUS
        if _mentions(text, person_name):
            return EntityMatch.CONFIRMED
        surname = person_name.split()[-1]
        return EntityMatch.PROBABLE if _mentions(text, surname) else EntityMatch.AMBIGUOUS
    if about is About.COMPANY:
        if source_type is SourceType.FIRST_PARTY or _mentions(text, company_name):
            return EntityMatch.CONFIRMED
        return EntityMatch.AMBIGUOUS
    return EntityMatch.PROBABLE
