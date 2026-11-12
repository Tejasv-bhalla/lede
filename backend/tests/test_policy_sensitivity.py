from app.domain.models import Sensitivity
from app.domain.models import SignalCategory as Cat
from app.policy.sensitivity import screen_sensitivity


def test_negative_news_category_is_always_sensitive():
    assert screen_sensitivity(Cat.LAYOFFS, "Acme restructures its team") is (
        Sensitivity.NEGATIVE_NEWS
    )


def test_mislabelled_negative_story_is_caught_by_its_wording():
    text = "Acme announced it will lay off 120 employees as part of a strategic reset."
    assert screen_sensitivity(Cat.STRATEGY_EARNINGS, text) is Sensitivity.NEGATIVE_NEWS
    assert screen_sensitivity(Cat.REGULATORY, "Acme faces a class action lawsuit") is (
        Sensitivity.NEGATIVE_NEWS
    )


def test_personal_life_details_are_sensitive():
    text = "Priya shared that she is on maternity leave after the birth of her daughter."
    assert screen_sensitivity(Cat.OWN_CONTENT, text) is Sensitivity.PERSONAL


def test_ordinary_business_news_is_not_sensitive():
    text = "Acme raised a $40 million Series B to expand its finance operations."
    assert screen_sensitivity(Cat.FUNDING_MNA, text) is Sensitivity.NONE
