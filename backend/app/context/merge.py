"""Merge the seller profile (who we are) with a campaign (why now) into one brief per run.

Rule (SYSTEM_DESIGN.md §9.1): the profile is the source of truth for facts and limits; a campaign
may narrow, focus and add restrictions, never contradict the profile or loosen a safeguard.
Conflicts are reported as issues with a suggested fix; nothing is silently overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.domain.hook_dimensions import DEFAULT_HOOK_WEIGHTS
from app.domain.models import (
    NEGATIVE_CATEGORIES,
    ApprovedClaim,
    Campaign,
    Persona,
    Priority,
    SellerProfile,
    SignalCategory,
)

Severity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class BriefIssue:
    code: str
    severity: Severity
    message: str
    fix: str


@dataclass(slots=True)
class MergedBrief:
    persona: Persona | None
    objective: str
    claims: list[ApprovedClaim] = field(default_factory=list)
    never_claims: list[str] = field(default_factory=list)
    pains: list[str] = field(default_factory=list)
    signal_priorities: dict[SignalCategory, Priority] = field(default_factory=dict)
    hook_weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_HOOK_WEIGHTS))
    provenance: dict[str, str] = field(default_factory=dict)
    issues: list[BriefIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)


def _norm(values: list[str]) -> set[str]:
    return {v.strip().casefold() for v in values}


def _resolve_persona(
    profile: SellerProfile, campaign: Campaign, issues: list[BriefIssue]
) -> Persona | None:
    persona = next((p for p in profile.personas if p.id == campaign.persona_id), None)
    if persona is None:
        known = ", ".join(p.id for p in profile.personas) or "none defined"
        issues.append(
            BriefIssue(
                "unknown_persona",
                "error",
                f"The campaign targets persona '{campaign.persona_id}', "
                "which the seller profile doesn't define.",
                f"Pick one of: {known}, or add this persona to the seller profile.",
            )
        )
    return persona


def _resolve_claims(
    profile: SellerProfile, campaign: Campaign, issues: list[BriefIssue]
) -> list[ApprovedClaim]:
    if not campaign.claims_to_emphasise:
        return list(profile.approved_claims)
    approved = {c.id: c for c in profile.approved_claims}
    for cid in campaign.claims_to_emphasise:
        if cid not in approved:
            issues.append(
                BriefIssue(
                    "unknown_claim",
                    "error",
                    f"The campaign emphasises claim '{cid}', which isn't an approved claim.",
                    "Add it to the seller profile's approved claims first, or remove it.",
                )
            )
    return [approved[cid] for cid in campaign.claims_to_emphasise if cid in approved]


def _check_segment(profile: SellerProfile, campaign: Campaign, issues: list[BriefIssue]) -> None:
    icp, seg = profile.icp, campaign.segment
    outside = sorted(
        (_norm(seg.industries) - _norm(icp.industries) if icp.industries else set())
        | (_norm(seg.regions) - _norm(icp.regions) if icp.regions else set())
    )
    if outside:
        issues.append(
            BriefIssue(
                "outside_icp",
                "warning",
                f"The campaign targets {', '.join(outside)}, outside the seller's ideal customer.",
                "Confirm this is an intentional test of a new segment, or narrow the campaign.",
            )
        )


def _resolve_priorities(
    profile: SellerProfile, campaign: Campaign, issues: list[BriefIssue]
) -> dict[SignalCategory, Priority]:
    priorities = {cat: Priority.MEDIUM for cat in profile.signal_to_pain}
    for cat, priority in campaign.signal_priorities.items():
        if cat in NEGATIVE_CATEGORIES:
            issues.append(
                BriefIssue(
                    "sensitive_priority",
                    "error",
                    f"'{cat.value}' is negative news; it can't be a research priority or a hook.",
                    "Remove it from the campaign's signal priorities.",
                )
            )
            continue
        priorities[cat] = priority
    return priorities


def _resolve_weights(
    profile: SellerProfile, campaign: Campaign, issues: list[BriefIssue]
) -> dict[str, float]:
    weights = dict(DEFAULT_HOOK_WEIGHTS)
    for source, overrides in (
        ("profile", profile.hook_weights),
        ("campaign", campaign.hook_weight_overrides),
    ):
        for dim, value in overrides.items():
            if dim not in weights or value < 0:
                issues.append(
                    BriefIssue(
                        "invalid_weight",
                        "error",
                        f"The {source} sets weight {value} for '{dim}'.",
                        f"Use a known dimension ({', '.join(DEFAULT_HOOK_WEIGHTS)}) "
                        "with a weight of 0 or more.",
                    )
                )
                continue
            weights[dim] = value
    return weights


def merge_brief(profile: SellerProfile, campaign: Campaign) -> MergedBrief:
    issues: list[BriefIssue] = []
    persona = _resolve_persona(profile, campaign, issues)
    claims = _resolve_claims(profile, campaign, issues)
    _check_segment(profile, campaign, issues)
    # Restrictions only ever add up: a campaign can't remove a profile never-claim.
    never_claims = list(dict.fromkeys([*profile.never_claims, *campaign.extra_never_claims]))
    pains = [*(persona.pains if persona else []), *([campaign.angle] if campaign.angle else [])]
    priorities = _resolve_priorities(profile, campaign, issues)
    weights = _resolve_weights(profile, campaign, issues)
    return MergedBrief(
        persona=persona,
        objective=campaign.objective,
        claims=claims,
        never_claims=never_claims,
        pains=pains,
        signal_priorities=priorities,
        hook_weights=weights,
        provenance={
            "persona": "profile",
            "objective": "campaign",
            "claims": "campaign" if campaign.claims_to_emphasise else "profile",
            "never_claims": "profile+campaign" if campaign.extra_never_claims else "profile",
            "pains": "profile+campaign" if campaign.angle else "profile",
            "signal_priorities": "profile+campaign" if campaign.signal_priorities else "profile",
        },
        issues=issues,
    )
