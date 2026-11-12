"""Rank candidate hooks: vetoes first, then a weighted total of the AI's per-dimension scores.

The AI scores each dimension (1-5) with a reason; code computes the total so the weights are
explicit and tunable (SYSTEM_DESIGN.md §6). Vetoes are absolute: no score can outrank them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.domain.models import Entailment, EntityMatch, Evidence, Sensitivity

VetoReason = Literal[
    "sensitive", "entity_not_confirmed", "quote_not_verified", "claim_not_supported", "unscored"
]


@dataclass(frozen=True, slots=True)
class DimensionScores:
    scores: Mapping[str, float]
    reasons: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class RankedHook:
    evidence: Evidence
    total: float
    dimension_scores: Mapping[str, float]
    reasons: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class VetoedHook:
    evidence: Evidence
    reason: VetoReason


Outcome = Literal["ok", "low_signal", "only_sensitive"]
DEFAULT_MIN_TOTAL = 3.0  # on the 1-5 scale; tuned with evals


@dataclass(slots=True)
class HookRanking:
    ranked: list[RankedHook] = field(default_factory=list)
    vetoed: list[VetoedHook] = field(default_factory=list)
    outcome: Outcome = "low_signal"

    def top(self, n: int = 3) -> list[RankedHook]:
        return self.ranked[:n]


def veto_reason(e: Evidence) -> VetoReason | None:
    if e.sensitivity is not Sensitivity.NONE:
        return "sensitive"
    if e.entity_match is not EntityMatch.CONFIRMED:
        return "entity_not_confirmed"
    if not e.quote_verified:
        return "quote_not_verified"
    if e.entailment is Entailment.UNSUPPORTED:
        return "claim_not_supported"
    return None


def _weighted_total(scores: Mapping[str, float], weights: Mapping[str, float]) -> float:
    weight_sum = sum(weights.values()) or 1.0
    return round(sum(scores.get(dim, 0.0) * w for dim, w in weights.items()) / weight_sum, 3)


def _average(samples: Sequence[DimensionScores]) -> dict[str, float]:
    dims = {d for s in samples for d in s.scores}
    return {d: round(sum(s.scores.get(d, 0.0) for s in samples) / len(samples), 3) for d in dims}


def rank_hooks(
    evidence: Sequence[Evidence],
    samples: Mapping[str, Sequence[DimensionScores]],
    *,
    weights: Mapping[str, float],
    min_total: float = DEFAULT_MIN_TOTAL,
) -> HookRanking:
    result = HookRanking()
    for e in evidence:
        reason = veto_reason(e) or (None if samples.get(e.id) else "unscored")
        if reason is not None:
            result.vetoed.append(VetoedHook(e, reason))
            continue
        averaged = _average(samples[e.id])
        result.ranked.append(
            RankedHook(
                evidence=e,
                total=_weighted_total(averaged, weights),
                dimension_scores=averaged,
                reasons=samples[e.id][-1].reasons,
            )
        )
    result.ranked.sort(key=lambda h: h.total, reverse=True)
    result.outcome = _outcome(result, min_total)
    return result


def _outcome(ranking: HookRanking, min_total: float) -> Outcome:
    if ranking.ranked and ranking.ranked[0].total >= min_total:
        return "ok"
    if not ranking.ranked and any(v.reason == "sensitive" for v in ranking.vetoed):
        return "only_sensitive"
    return "low_signal"
