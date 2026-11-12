from app.context.merge import merge_brief
from app.domain.models import (
    ICP,
    ApprovedClaim,
    Campaign,
    CompanyInfo,
    Offer,
    Persona,
    Priority,
    Segment,
    SellerProfile,
    Seniority,
)
from app.domain.models import SignalCategory as Cat


def profile(**overrides) -> SellerProfile:
    base = dict(
        company=CompanyInfo(name="Ledgerly", domain="ledgerly.example"),
        offer=Offer(product="AP automation", problem_solved="manual invoice processing"),
        icp=ICP(industries=["fintech", "saas"], regions=["US", "UK"]),
        personas=[
            Persona(
                id="vp_finance",
                title_patterns=["VP Finance", "Head of Finance"],
                seniority=Seniority.VP,
                pains=["AP team can't keep up with invoice volume"],
            )
        ],
        approved_claims=[
            ApprovedClaim(id="c1", text="Matches invoices to POs automatically"),
            ApprovedClaim(id="c2", text="Flags duplicate invoices before payment"),
        ],
        never_claims=["guaranteed ROI"],
    )
    base.update(overrides)
    return SellerProfile(**base)


def campaign(**overrides) -> Campaign:
    base = dict(
        id="q1",
        name="Q1 fintech demos",
        objective="Book demos with finance leaders at scaling fintechs",
        persona_id="vp_finance",
        segment=Segment(industries=["fintech"], regions=["UK"]),
        angle="Scaling headcount without scaling the AP team",
        cta="Worth a quick look?",
    )
    base.update(overrides)
    return Campaign(**base)


def test_consistent_profile_and_campaign_merge_without_issues():
    brief = merge_brief(profile(), campaign())
    assert brief.ok is True
    assert brief.persona.id == "vp_finance"
    assert brief.objective == "Book demos with finance leaders at scaling fintechs"


def codes(brief) -> set[str]:
    return {i.code for i in brief.issues}


def test_campaign_targeting_an_undefined_persona_is_an_error():
    brief = merge_brief(profile(), campaign(persona_id="cto"))
    assert brief.ok is False
    assert "unknown_persona" in codes(brief)


def test_campaign_can_only_emphasise_claims_the_profile_approves():
    brief = merge_brief(profile(), campaign(claims_to_emphasise=["c2", "c9"]))
    assert [c.id for c in brief.claims] == ["c2"]
    assert "unknown_claim" in codes(brief)
    assert brief.ok is False


def test_never_claims_combine_profile_and_campaign_restrictions():
    brief = merge_brief(profile(), campaign(extra_never_claims=["competitor names"]))
    assert set(brief.never_claims) == {"guaranteed ROI", "competitor names"}


def test_segment_outside_the_ideal_customer_is_a_warning_not_a_block():
    brief = merge_brief(profile(), campaign(segment=Segment(industries=["healthcare"])))
    assert "outside_icp" in codes(brief)
    assert brief.ok is True


def test_pains_combine_persona_pains_with_the_campaign_angle_and_record_provenance():
    brief = merge_brief(profile(), campaign())
    assert brief.pains == [
        "AP team can't keep up with invoice volume",
        "Scaling headcount without scaling the AP team",
    ]
    assert brief.provenance["pains"] == "profile+campaign"
    assert brief.provenance["objective"] == "campaign"


def test_research_priorities_default_to_signals_the_profile_maps_to_pains():
    p = profile(signal_to_pain={Cat.HIRING_PATTERN: ["AP backlog"], Cat.FUNDING_MNA: ["growth"]})
    brief = merge_brief(p, campaign(signal_priorities={Cat.HIRING_PATTERN: Priority.HIGH}))
    assert brief.signal_priorities == {
        Cat.HIRING_PATTERN: Priority.HIGH,
        Cat.FUNDING_MNA: Priority.MEDIUM,
    }


def test_campaign_cannot_prioritise_negative_news():
    brief = merge_brief(profile(), campaign(signal_priorities={Cat.LAYOFFS: Priority.HIGH}))
    assert "sensitive_priority" in codes(brief)
    assert Cat.LAYOFFS not in brief.signal_priorities
    assert brief.ok is False


def test_hook_weights_layer_defaults_then_profile_then_campaign():
    p = profile(hook_weights={"recency": 2.0})
    brief = merge_brief(p, campaign(hook_weight_overrides={"offer_relevance": 3.0}))
    assert brief.hook_weights["recency"] == 2.0
    assert brief.hook_weights["offer_relevance"] == 3.0
    assert brief.hook_weights["specificity"] == 1.0  # untouched default


def test_negative_hook_weight_is_rejected():
    brief = merge_brief(profile(), campaign(hook_weight_overrides={"recency": -1.0}))
    assert "invalid_weight" in codes(brief)
    assert brief.hook_weights["recency"] == 1.0


def test_without_emphasis_all_approved_claims_are_available():
    brief = merge_brief(profile(), campaign())
    assert [c.id for c in brief.claims] == ["c1", "c2"]
