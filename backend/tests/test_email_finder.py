"""Hunter's email finder, against a scripted Hunter API."""

import httpx
import pytest

from app.pipeline.ports import Contact, EmailLookupFailed, FoundEmail
from app.providers.email_finder import HunterEmailFinder

KEY = "hunter-test-key-1234"
PRIYA = Contact(company_name="Acme", company_domain="acme.example", person_name="Priya Shah")
FOUND = {
    "data": {
        "email": "Priya.Shah@acme.example",
        "score": 94,
        "sources": [{"uri": "https://acme.example/team", "still_on_page": True}],
        "verification": {"date": "2026-11-01", "status": "valid"},
    }
}


class Hunter:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


def finder(hunter: Hunter) -> HunterEmailFinder:
    return HunterEmailFinder(httpx.AsyncClient(transport=httpx.MockTransport(hunter)), KEY)


async def test_a_found_address_comes_back_with_its_score_and_a_page_that_shows_it():
    hunter = Hunter(httpx.Response(200, json=FOUND))
    found = await finder(hunter).find(PRIYA)

    assert found == FoundEmail(
        "priya.shah@acme.example",
        "finder",
        url="https://acme.example/team",
        confidence=94,
        status="valid",
    )
    sent = hunter.requests[0]
    assert sent.url.path == "/v2/email-finder"
    assert dict(sent.url.params) == {
        "domain": "acme.example",
        "first_name": "Priya",
        "last_name": "Shah",
    }
    assert sent.headers["X-API-KEY"] == KEY
    assert KEY not in str(sent.url)  # the key stays out of URLs, and so out of logs


async def test_without_a_domain_the_company_name_is_used():
    hunter = Hunter(httpx.Response(200, json=FOUND))
    await finder(hunter).find(Contact(company_name="Acme", person_name="Priya Shah"))

    assert hunter.requests[0].url.params["company"] == "Acme"
    assert "domain" not in hunter.requests[0].url.params


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"data": {"email": None, "score": None, "sources": []}}),
        # The person asked Hunter to stop sharing their address: it must not be used.
        httpx.Response(451, json={"errors": [{"id": "claimed_email", "code": 451}]}),
    ],
    ids=["not found", "claimed by the person"],
)
async def test_no_address_is_returned_when_hunter_has_none_it_may_share(response):
    assert await finder(Hunter(response)).find(PRIYA) is None


async def test_a_one_word_name_is_not_looked_up():
    hunter = Hunter(httpx.Response(200, json=FOUND))
    assert await finder(hunter).find(Contact(company_name="Acme", person_name="Priya")) is None
    assert hunter.requests == []


@pytest.mark.parametrize(
    ("status", "says"),
    [(429, "monthly limit"), (401, "key"), (500, "500")],
)
async def test_hunter_errors_are_reported_as_a_failed_lookup(status, says):
    with pytest.raises(EmailLookupFailed, match=says):
        await finder(Hunter(httpx.Response(status, json={"errors": []}))).find(PRIYA)


async def test_a_network_failure_is_a_failed_lookup():
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    lookup = HunterEmailFinder(httpx.AsyncClient(transport=httpx.MockTransport(down)), KEY)
    with pytest.raises(EmailLookupFailed):
        await lookup.find(PRIYA)
