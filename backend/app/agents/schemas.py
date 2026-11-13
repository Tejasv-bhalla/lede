"""What each AI role must answer with. The router validates every answer against these."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.models import About, Entailment, SignalCategory


class _Out(BaseModel):
    model_config = {"extra": "ignore"}  # tolerate harmless extra keys some models add


# ── research ─────────────────────────────────────────────────────────────────


class QueryOut(_Out):
    category: SignalCategory
    query: str = Field(min_length=3, max_length=200)
    goal: str = ""


class QueryPlanOut(_Out):
    queries: list[QueryOut] = Field(max_length=12)


class SignalOut(_Out):
    category: SignalCategory
    about: About
    claim: str = Field(description="One factual sentence about the prospect or their company.")
    quote: str = Field(description="Copied character for character from the page.")
    event_date: date | None = Field(None, description="When it happened, if the page says.")


class ReadOut(_Out):
    signals: list[SignalOut] = Field(default_factory=list, max_length=8)


class ReflectionOut(_Out):
    is_sufficient: bool
    missing: list[SignalCategory] = Field(default_factory=list)
    follow_up: list[QueryOut] = Field(default_factory=list, max_length=6)
    rationale: str = ""


# ── identity ─────────────────────────────────────────────────────────────────


class PersonOut(_Out):
    person_name: str
    company_name: str
    title: str | None = None
    result: int = Field(description="Number of the search result that shows this.")
    quote: str = Field(description="Copied character for character from that result.")


class IdentityOut(_Out):
    status: Literal["confirmed", "moved", "ambiguous", "not_found"]
    company_domain: str | None = Field(None, description="The company's own website domain.")
    match: PersonOut | None = Field(None, description="Confirmed person, or their new role.")
    candidates: list[PersonOut] = Field(default_factory=list, max_length=3)
    reason: str = ""


class SuggestionOut(_Out):
    company_domain: str | None = None
    suggestions: list[PersonOut] = Field(default_factory=list, max_length=3)
    reason: str = ""


# ── judging ──────────────────────────────────────────────────────────────────


class EntailmentOut(_Out):
    verdict: Entailment
    reason: str = ""


class DimensionOut(_Out):
    score: int = Field(ge=1, le=5)
    reason: str


class HookScoreOut(_Out):
    offer_relevance: DimensionOut
    specificity: DimensionOut
    recency: DimensionOut
    persona_fit: DimensionOut
    source_strength: DimensionOut
    closeness: DimensionOut


class ClaimCheckOut(_Out):
    claim: str
    kind: Literal["prospect_fact", "seller_claim", "other"]
    evidence_id: str | None = None
    verdict: Entailment
    reason: str = ""


class FactCheckOut(_Out):
    claims: list[ClaimCheckOut]


# ── writing ──────────────────────────────────────────────────────────────────


class DraftOut(_Out):
    subject: str = Field(max_length=80)
    body: str
    citations: list[str] = Field(default_factory=list, description="Evidence ids relied on.")
