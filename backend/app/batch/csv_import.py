"""Read a prospect CSV: map columns, normalise, validate and de-duplicate (SYSTEM_DESIGN.md §9.2).

Pure and free (no AI, no network), so the rep sees every problem before any quota is spent.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.domain.models import ProspectInput

MAX_ROWS = 500

# Accepted header spellings per field (compared case- and punctuation-insensitively).
COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "person_name": ("name", "full name", "person", "contact", "contact name", "prospect"),
    "company_name": ("company", "company name", "organisation", "organization", "account"),
    "company_domain": ("domain", "website", "company website", "url", "company domain"),
    "title": ("title", "job title", "role", "position"),
    "linkedin_url": ("linkedin", "linkedin url", "linkedin profile"),
    "rep_notes": ("notes", "rep notes", "context", "comments"),
}


class CsvFormatError(ValueError):
    """The file can't be read as a prospect list at all."""


@dataclass(frozen=True, slots=True)
class RowError:
    row: int  # spreadsheet row number (the header is row 1)
    reason: str


@dataclass(slots=True)
class CsvPreview:
    rows: list[ProspectInput] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)


def _key(header: str) -> str:
    return re.sub(r"[^a-z]+", " ", header.casefold()).strip()


def normalise_domain(value: str | None) -> str | None:
    """'https://www.Acme.com/about' -> 'acme.com'."""
    if not value or not value.strip():
        return None
    raw = value.strip()
    host = urlsplit(raw if "//" in raw else f"//{raw}").hostname or ""
    return host.removeprefix("www.") or None


def dedupe_key(p: ProspectInput) -> tuple[str, str]:
    company = p.company_domain or p.company_name.strip().casefold()
    return ((p.person_name or "").strip().casefold(), company)


def _map_columns(headers: list[str]) -> tuple[dict[str, str], list[str]]:
    lookup = {alias: name for name, aliases in COLUMN_ALIASES.items() for alias in aliases}
    mapping: dict[str, str] = {}
    unmapped: list[str] = []
    for header in headers:
        target = lookup.get(_key(header))
        if target and target not in mapping.values():
            mapping[header] = target
        else:
            unmapped.append(header)
    if "company_name" not in mapping.values():
        accepted = ", ".join(COLUMN_ALIASES["company_name"])
        raise CsvFormatError(f"No company column found. Name one of: {accepted}.")
    return mapping, unmapped


def read_prospects(text: str, existing: Iterable[ProspectInput] = ()) -> CsvPreview:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    mapping, unmapped = _map_columns(list(reader.fieldnames or []))
    preview = CsvPreview(unmapped_columns=unmapped)
    seen = {dedupe_key(p): 0 for p in existing}  # 0 = already saved in the campaign

    for number, raw in enumerate(reader, start=2):
        if number - 1 > MAX_ROWS:
            raise CsvFormatError(f"Too many rows; the limit is {MAX_ROWS} per upload.")
        values = {
            target: (raw.get(header) or "").strip() or None for header, target in mapping.items()
        }
        if not values.get("company_name"):
            preview.errors.append(RowError(number, "missing company name"))
            continue
        values["company_domain"] = normalise_domain(values.get("company_domain"))
        try:
            prospect = ProspectInput.model_validate(values)
        except ValidationError as exc:
            preview.errors.append(RowError(number, exc.errors()[0]["msg"]))
            continue
        first = seen.setdefault(dedupe_key(prospect), number)
        if first != number:
            reason = "already in this campaign" if first == 0 else f"duplicate of row {first}"
            preview.errors.append(RowError(number, reason))
            continue
        preview.rows.append(prospect)
    return preview
