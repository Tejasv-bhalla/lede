"""Deterministic check that a quoted passage really appears in the stored page text.

The AI reader returns a verbatim quote for every signal; this module is the code-side proof.
It tolerates formatting noise (whitespace, curly quotes, dashes, case, wrapping punctuation) and a
stray letter in a long quote, but never a different number.
"""

import re
from dataclasses import dataclass
from typing import Literal

from rapidfuzz import fuzz

MIN_QUOTE_CHARS = 20
FUZZY_MIN_SCORE = 95.0  # tolerate a stray letter in a long quote, not a paraphrase

_WS = re.compile(r"\s+")
_NUMBERS = re.compile(r"\d+(?:[.,]\d+)*")
_ELLIPSIS = chr(0x2026)
_EDGE_NOISE = " \"'.,;:" + _ELLIPSIS
# Typographic punctuation an LLM commonly rewrites to ASCII (code points keep this unambiguous).
_PUNCT = str.maketrans(
    {
        0x2018: "'",  # left single quote
        0x2019: "'",  # right single quote / apostrophe
        0x201A: "'",  # low single quote
        0x201C: '"',  # left double quote
        0x201D: '"',  # right double quote
        0x201E: '"',  # low double quote
        0x2013: "-",  # en dash
        0x2014: "-",  # em dash
        0x2212: "-",  # minus sign
        0x00A0: " ",  # non-breaking space
        0x2026: "...",  # ellipsis
    }
)

FailureReason = Literal["too_short", "not_found", "number_mismatch"]


@dataclass(frozen=True, slots=True)
class QuoteCheck:
    verified: bool
    reason: FailureReason | None = None


def _normalise(text: str) -> str:
    return _WS.sub(" ", text.translate(_PUNCT)).strip().casefold()


def verify_quote(quote: str, page_text: str) -> QuoteCheck:
    needle = _normalise(quote).strip(_EDGE_NOISE)
    if len(needle) < MIN_QUOTE_CHARS:
        return QuoteCheck(False, "too_short")

    haystack = _normalise(page_text)
    if needle in haystack:
        return QuoteCheck(True)

    match = fuzz.partial_ratio_alignment(needle, haystack, score_cutoff=FUZZY_MIN_SCORE)
    if match is None:
        return QuoteCheck(False, "not_found")
    # A near match may tolerate a stray letter, never a different figure.
    aligned = haystack[match.dest_start : match.dest_end]
    if _NUMBERS.findall(needle) != _NUMBERS.findall(aligned):
        return QuoteCheck(False, "number_mismatch")
    return QuoteCheck(True)
