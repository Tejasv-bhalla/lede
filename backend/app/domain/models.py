"""Core domain vocabulary shared by every stage (see SYSTEM_DESIGN.md §3.2, §9, §10.3)."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Enumerations ────────────────────────────────────────────────────────────────


class SignalCategory(StrEnum):
    # person-level
    ROLE_CHANGE = "role_change"
    OWN_CONTENT = "own_content"
    PRESS_QUOTE = "press_quote"
    AWARD_OR_SPEAKING = "award_or_speaking"
    # company-level
    FUNDING_MNA = "funding_mna"
    LEADERSHIP_HIRE = "leadership_hire"
    HIRING_PATTERN = "hiring_pattern"
    PRODUCT_LAUNCH = "product_launch"
    EXPANSION = "expansion"
    PARTNERSHIP = "partnership"
    TECH_STACK_CHANGE = "tech_stack_change"
    STRATEGY_EARNINGS = "strategy_earnings"
    REGULATORY = "regulatory"
    # negative news: collected, never usable as a hook
    LAYOFFS = "layoffs"
    LITIGATION = "litigation"
    BREACH = "breach"
    DEATH_OR_TRAGEDY = "death_or_tragedy"
    SCANDAL = "scandal"


NEGATIVE_CATEGORIES: frozenset[SignalCategory] = frozenset(
    {
        SignalCategory.LAYOFFS,
        SignalCategory.LITIGATION,
        SignalCategory.BREACH,
        SignalCategory.DEATH_OR_TRAGEDY,
        SignalCategory.SCANDAL,
    }
)


class About(StrEnum):
    PERSON = "person"
    COMPANY = "company"
    MARKET = "market"


class SourceType(StrEnum):
    FIRST_PARTY = "first_party"
    FILING = "filing"
    PRESS = "press"
    JOB_BOARD = "job_board"
    PODCAST_VIDEO = "podcast_video"
    SOCIAL = "social"
    AGGREGATOR = "aggregator"
    REP_SUPPLIED = "rep_supplied"
    UNKNOWN = "unknown"


class EntityMatch(StrEnum):
    CONFIRMED = "confirmed"
    PROBABLE = "probable"
    AMBIGUOUS = "ambiguous"
    MISMATCH = "mismatch"


class Entailment(StrEnum):
    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class Sensitivity(StrEnum):
    NONE = "none"
    NEGATIVE_NEWS = "negative_news"
    PERSONAL = "personal"
    PRIVATE_INTENT = "private_intent"


class Tier(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class RunState(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DRAFT_READY = "DRAFT_READY"
    CONTACT_MOVED = "CONTACT_MOVED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    LOW_SIGNAL = "LOW_SIGNAL"
    NOT_A_FIT = "NOT_A_FIT"
    NEEDS_REVIEW_SENSITIVE = "NEEDS_REVIEW_SENSITIVE"
    BLOCKED_SUPPRESSED = "BLOCKED_SUPPRESSED"
    DUPLICATE = "DUPLICATE"
    RECENTLY_CONTACTED = "RECENTLY_CONTACTED"
    INVALID_INPUT = "INVALID_INPUT"
    DRAFT_HELD = "DRAFT_HELD"
    FAILED = "FAILED"


class ReviewState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPROVED_WITH_EDITS = "APPROVED_WITH_EDITS"
    REJECTED = "REJECTED"


class Priority(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Seniority(StrEnum):
    IC = "ic"
    MANAGER = "manager"
    DIRECTOR = "director"
    VP = "vp"
    C_LEVEL = "c_level"


class HookPreference(StrEnum):
    COMPANY = "company"
    INDIVIDUAL = "individual"


class _Model(BaseModel):
    model_config = ConfigDict(frozen=False, extra="forbid")


# ── Seller profile (who we are) ────────────────────────────────────────────────


class CompanyInfo(_Model):
    name: str
    domain: str
    one_liner: str = ""


class Offer(_Model):
    product: str
    problem_solved: str
    how_it_works: str = ""


class ICP(_Model):
    industries: list[str] = Field(default_factory=list)
    employee_min: int | None = None
    employee_max: int | None = None
    regions: list[str] = Field(default_factory=list)
    exclusions: list[str] = Field(default_factory=list)


class Persona(_Model):
    id: str
    title_patterns: list[str]
    seniority: Seniority
    pains: list[str] = Field(default_factory=list)
    hook_preference: HookPreference = HookPreference.COMPANY


class ApprovedClaim(_Model):
    id: str
    text: str
    proof_url: str | None = None


class Tone(_Model):
    voice: str = "plain, warm, specific"
    max_words: int = 100
    cta_style: str = "soft"
    banned_phrases: list[str] = Field(default_factory=list)


class SellerProfile(_Model):
    company: CompanyInfo
    offer: Offer
    icp: ICP = Field(default_factory=ICP)
    personas: list[Persona] = Field(default_factory=list)
    signal_to_pain: dict[SignalCategory, list[str]] = Field(default_factory=dict)
    approved_claims: list[ApprovedClaim] = Field(default_factory=list)
    never_claims: list[str] = Field(default_factory=list)
    tone: Tone = Field(default_factory=Tone)
    recency_windows_days: dict[SignalCategory, int] = Field(default_factory=dict)
    hook_weights: dict[str, float] = Field(default_factory=dict)
    footer: str = ""


# ── Campaign (why now) ─────────────────────────────────────────────────────────


class Segment(_Model):
    industries: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    stages: list[str] = Field(default_factory=list)


class Campaign(_Model):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    name: str
    objective: str

    @field_validator("name", "objective")
    @classmethod
    def _trimmed(cls, value: str) -> str:
        return value.strip()  # a pasted tab or space must not make two names look alike

    persona_id: str
    segment: Segment = Field(default_factory=Segment)
    angle: str = ""
    cta: str = ""
    signal_priorities: dict[SignalCategory, Priority] = Field(default_factory=dict)
    claims_to_emphasise: list[str] = Field(default_factory=list)
    extra_never_claims: list[str] = Field(default_factory=list)
    tone_adjustment: str = ""
    hook_weight_overrides: dict[str, float] = Field(default_factory=dict)


# ── Prospect input ─────────────────────────────────────────────────────────────


class ProspectInput(_Model):
    company_name: str
    person_name: str | None = None
    company_domain: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    rep_notes: str | None = None
    email: str | None = None  # when the rep already knows it; Lede then searches for none

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        value = (value or "").strip().casefold()
        if not value:
            return None
        local, _, host = value.partition("@")
        if not local or "." not in host or " " in value:
            raise ValueError("is not an email address")
        return value


# ── Evidence ledger ────────────────────────────────────────────────────────────


class Evidence(_Model):
    id: str
    category: SignalCategory
    about: About
    claim: str
    verbatim_quote: str
    url: str
    publisher: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    published_at: date | None = None
    event_date: date | None = None
    retrieved_at: datetime
    entity_match: EntityMatch = EntityMatch.PROBABLE
    quote_verified: bool = False
    entailment: Entailment | None = None
    sensitivity: Sensitivity = Sensitivity.NONE
    round_found: int = 0
