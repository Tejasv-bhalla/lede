from datetime import UTC, datetime

from app.domain.hook_dimensions import DEFAULT_HOOK_WEIGHTS
from app.domain.models import About, Entailment, EntityMatch, Evidence, Sensitivity
from app.domain.models import SignalCategory as Cat
from app.pipeline.hooks import DimensionScores, rank_hooks


def ev(eid: str, **overrides) -> Evidence:
    base = dict(
        id=eid,
        category=Cat.HIRING_PATTERN,
        about=About.COMPANY,
        claim=f"claim {eid}",
        verbatim_quote="Acme is hiring three accounts payable specialists in London",
        url=f"https://acme.example/{eid}",
        retrieved_at=datetime(2026, 11, 12, tzinfo=UTC),
        entity_match=EntityMatch.CONFIRMED,
        quote_verified=True,
    )
    base.update(overrides)
    return Evidence(**base)


def scores(value: float) -> DimensionScores:
    return DimensionScores(scores=dict.fromkeys(DEFAULT_HOOK_WEIGHTS, value), reasons={})


def test_highest_scoring_eligible_evidence_ranks_first():
    ranking = rank_hooks(
        [ev("e1"), ev("e2")],
        {"e1": [scores(3.0)], "e2": [scores(4.5)]},
        weights=DEFAULT_HOOK_WEIGHTS,
    )
    assert [h.evidence.id for h in ranking.ranked] == ["e2", "e1"]


def test_multiple_score_samples_are_averaged_per_dimension():
    ranking = rank_hooks(
        [ev("noisy"), ev("steady")],
        {"noisy": [scores(2.0), scores(4.4)], "steady": [scores(3.5), scores(3.5)]},
        weights=DEFAULT_HOOK_WEIGHTS,
    )
    assert [h.evidence.id for h in ranking.ranked] == ["steady", "noisy"]
    assert ranking.ranked[1].dimension_scores["recency"] == 3.2


def test_evidence_the_scorer_skipped_is_set_aside_not_ranked():
    ranking = rank_hooks([ev("e1"), ev("e2")], {"e1": [scores(4.0)]}, weights=DEFAULT_HOOK_WEIGHTS)
    assert [h.evidence.id for h in ranking.ranked] == ["e1"]
    assert [(v.evidence.id, v.reason) for v in ranking.vetoed] == [("e2", "unscored")]


def test_outcome_is_ok_and_top_three_are_offered_when_a_hook_clears_the_bar():
    cands = [ev(f"e{i}") for i in range(5)]
    samples = {c.id: [scores(2.5 + i * 0.5)] for i, c in enumerate(cands)}
    ranking = rank_hooks(cands, samples, weights=DEFAULT_HOOK_WEIGHTS, min_total=3.0)
    assert ranking.outcome == "ok"
    assert [h.evidence.id for h in ranking.top(3)] == ["e4", "e3", "e2"]


def test_outcome_is_low_signal_when_nothing_clears_the_bar():
    ranking = rank_hooks(
        [ev("weak")], {"weak": [scores(2.4)]}, weights=DEFAULT_HOOK_WEIGHTS, min_total=3.0
    )
    assert ranking.outcome == "low_signal"


def test_outcome_is_only_sensitive_when_sensitive_news_is_all_we_found():
    ranking = rank_hooks(
        [ev("layoffs", sensitivity=Sensitivity.NEGATIVE_NEWS)],
        {"layoffs": [scores(5.0)]},
        weights=DEFAULT_HOOK_WEIGHTS,
    )
    assert ranking.outcome == "only_sensitive"


def test_vetoed_evidence_never_ranks_even_with_top_scores():
    candidates = [
        ev("ok"),
        ev("sensitive", sensitivity=Sensitivity.NEGATIVE_NEWS),
        ev("wrong_entity", entity_match=EntityMatch.MISMATCH),
        ev("unverified", quote_verified=False),
        ev("unsupported", entailment=Entailment.UNSUPPORTED),
    ]
    samples = {c.id: [scores(5.0 if c.id != "ok" else 3.5)] for c in candidates}
    ranking = rank_hooks(candidates, samples, weights=DEFAULT_HOOK_WEIGHTS)
    assert [h.evidence.id for h in ranking.ranked] == ["ok"]
    assert {v.evidence.id: v.reason for v in ranking.vetoed} == {
        "sensitive": "sensitive",
        "wrong_entity": "entity_not_confirmed",
        "unverified": "quote_not_verified",
        "unsupported": "claim_not_supported",
    }
