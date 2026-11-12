from app.policy.draft_rules import DraftRules, check_draft

GOOD = (
    "Hi Priya, I saw Acme is hiring three accounts payable specialists in London. "
    "Teams scaling AP that quickly often look at automating invoice matching first. "
    "Worth a quick look at how others handled it?"
)


def kinds(body: str, rules: DraftRules) -> set[str]:
    return {v.kind for v in check_draft(body, rules)}


def test_a_short_compliant_draft_has_no_violations():
    assert check_draft(GOOD, DraftRules()) == []


def test_draft_over_the_word_limit_is_flagged():
    assert "too_long" in kinds(GOOD, DraftRules(max_words=20))


def test_default_cliche_is_flagged_regardless_of_case():
    assert "banned_phrase" in kinds("I Hope This Finds You Well. " + GOOD, DraftRules())


def test_recency_wording_is_flagged_when_the_hook_is_not_recent():
    body = "Hi Priya, congrats on the funding you just announced. " + GOOD
    assert "unsupported_recency" in kinds(body, DraftRules(recency_allowed=False))
    assert "unsupported_recency" not in kinds(body, DraftRules(recency_allowed=True))


def test_link_not_in_the_evidence_is_flagged():
    body = GOOD + " See https://made-up.example/report for details."
    rules = DraftRules(allowed_urls=frozenset({"https://acme.com/careers"}))
    assert "unknown_link" in kinds(body, rules)
    assert "unknown_link" not in kinds(GOOD + " https://acme.com/careers", rules)


def test_missing_required_footer_is_flagged():
    footer = "Reply 'stop' to opt out."
    assert "missing_footer" in kinds(GOOD, DraftRules(footer=footer))
    assert "missing_footer" not in kinds(GOOD + "\n\n" + footer, DraftRules(footer=footer))


def test_sellers_never_claim_is_flagged():
    body = GOOD + " We guarantee ROI within 30 days."
    assert "never_claim" in kinds(body, DraftRules(never_claims=("guarantee ROI",)))
