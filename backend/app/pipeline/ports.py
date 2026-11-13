"""AI-role boundaries the pipeline talks to (identity, entailment, scoring, writing, fact-check).

Real adapters call the LLM router; tests plug in fakes here and nowhere else.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from app.domain.models import Entailment, Evidence, ProspectInput

if TYPE_CHECKING:
    from app.context.merge import MergedBrief
    from app.pipeline.hooks import DimensionScores, RankedHook
    from app.policy.draft_rules import DraftRules


class IdentityStatus(StrEnum):
    CONFIRMED = "confirmed"  # person (or company, for company-only input) matched
    AMBIGUOUS = "ambiguous"  # several plausible people or companies: the rep must pick
    SUGGESTED = "suggested"  # company-only input: proposed contacts await the rep's confirmation
    MOVED = "moved"  # credible evidence the person now works elsewhere
    NOT_FOUND = "not_found"  # person not found: company-level research only


@dataclass(frozen=True, slots=True)
class Contact:
    company_name: str
    company_domain: str | None = None
    person_name: str | None = None
    title: str | None = None
    evidence_url: str | None = None
    evidence_quote: str | None = None


@dataclass(frozen=True, slots=True)
class Identity:
    status: IdentityStatus
    contact: Contact | None = None  # the resolved (or new, when MOVED) contact
    candidates: tuple[Contact, ...] = ()  # options for the rep when AMBIGUOUS or SUGGESTED


@dataclass(frozen=True, slots=True)
class Draft:
    subject: str
    body: str
    citations: tuple[str, ...] = ()  # evidence ids the draft relies on


@dataclass(frozen=True, slots=True)
class ClaimVerdict:
    claim: str
    verdict: Entailment
    evidence_id: str | None = None
    reason: str = ""


@dataclass(frozen=True, slots=True)
class DraftRequest:
    prospect: ProspectInput
    contact: Contact
    hook: RankedHook
    alternates: tuple[RankedHook, ...]
    brief: MergedBrief
    rules: DraftRules
    today: date
    variant: int = 0  # best-of-N: adapters vary sampling or framing per variant


class Resolver(Protocol):
    async def resolve(self, prospect: ProspectInput) -> Identity: ...


class EntailmentChecker(Protocol):
    async def entails(self, evidence: Evidence) -> Entailment: ...


class HookScorer(Protocol):
    async def score(self, evidence: Evidence, brief: MergedBrief) -> DimensionScores: ...


class Writer(Protocol):
    async def draft(self, request: DraftRequest) -> Draft: ...

    async def revise(
        self, draft: Draft, problems: Sequence[str], request: DraftRequest
    ) -> Draft: ...


class FactChecker(Protocol):
    async def check(self, draft: Draft, evidence: Sequence[Evidence]) -> list[ClaimVerdict]: ...
