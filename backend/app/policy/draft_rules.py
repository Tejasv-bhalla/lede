"""Code-side checks every draft must pass before a rep sees it (SYSTEM_DESIGN.md §7)."""

import re
from collections.abc import Iterable
from dataclasses import dataclass

_WORD = re.compile(r"\b[\w'-]+\b")

DEFAULT_BANNED_PHRASES: tuple[str, ...] = (
    "i hope this finds you well",
    "i hope this email finds you well",
    "just checking in",
    "touching base",
    "circle back",
    "synergy",
    "game-changer",
    "revolutionary",
    "i loved your post",
    "quick question",
)


_URL = re.compile(r"https?://[^\s)>\]]+")
_RECENCY = re.compile(
    r"\b(?:recent(?:ly)?|just (?:announced|launched|raised|joined|hired|released)|"
    r"this (?:week|month)|last week|newly|fresh(?:ly)?|congrat\w*)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class DraftRules:
    max_words: int = 100
    banned_phrases: tuple[str, ...] = DEFAULT_BANNED_PHRASES
    never_claims: tuple[str, ...] = ()
    recency_allowed: bool = True  # False when the hook's evidence is stale or undated
    allowed_urls: frozenset[str] | None = None  # None = links not checked
    footer: str | None = None


@dataclass(frozen=True, slots=True)
class Violation:
    kind: str
    detail: str


def _found(phrases: Iterable[str], text: str) -> list[str]:
    lowered = text.casefold()
    return [p for p in phrases if p.casefold() in lowered]


def check_draft(body: str, rules: DraftRules) -> list[Violation]:
    violations: list[Violation] = []
    words = len(_WORD.findall(body))
    if words > rules.max_words:
        violations.append(Violation("too_long", f"{words} words; limit is {rules.max_words}"))
    violations += [Violation("banned_phrase", p) for p in _found(rules.banned_phrases, body)]
    violations += [Violation("never_claim", p) for p in _found(rules.never_claims, body)]
    if not rules.recency_allowed:
        violations += [
            Violation("unsupported_recency", m.group(0)) for m in _RECENCY.finditer(body)
        ]
    if rules.allowed_urls is not None:
        for url in _URL.findall(body):
            if url.rstrip(".,;:!?") not in rules.allowed_urls:
                violations.append(Violation("unknown_link", url))
    if rules.footer and rules.footer.strip() not in body:
        violations.append(Violation("missing_footer", rules.footer))
    return violations
