from app.policy.quotes import verify_quote

PAGE = (
    "Acme Corp today announced its Series B funding round of $40 million, led by Example "
    "Ventures. The company plans to expand its finance operations team in London."
)


def test_exact_quote_on_page_is_verified():
    result = verify_quote("announced its Series B funding round of $40 million", PAGE)
    assert result.verified is True


def test_quote_matches_despite_whitespace_and_line_breaks_on_page():
    page = "Acme Corp today announced its Series B\n   funding round\tof $40 million."
    assert verify_quote("its Series B funding round of $40 million", page).verified is True


def test_quote_matches_despite_typographic_punctuation_and_capitalisation():
    page = "Our CFO said: “We’re scaling the finance team — fast — across three regions.”"
    quote = "we're scaling the finance team - fast - across three regions"
    assert verify_quote(quote, page).verified is True


def test_quote_wrapped_in_quotation_marks_or_ellipsis_still_matches():
    assert verify_quote('"expand its finance operations team in London..."', PAGE).verified is True


def test_long_quote_with_a_one_letter_slip_is_still_verified():
    quote = "The company plans to expand its finance operation team in London"
    assert verify_quote(quote, PAGE).verified is True


def test_near_match_with_a_changed_number_is_rejected():
    quote = "announced its Series B funding round of $45 million, led by Example Ventures"
    result = verify_quote(quote, PAGE)
    assert (result.verified, result.reason) == (False, "number_mismatch")


def test_fabricated_quote_is_rejected():
    result = verify_quote("Acme is replacing its accounts payable team with automation", PAGE)
    assert (result.verified, result.reason) == (False, "not_found")


def test_too_short_quote_is_rejected_even_if_present():
    result = verify_quote("Series B", PAGE)
    assert (result.verified, result.reason) == (False, "too_short")
