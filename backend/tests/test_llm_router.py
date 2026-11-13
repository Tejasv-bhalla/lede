import asyncio
import json

import httpx2 as httpx  # the HTTP library the openai SDK is built on
import pytest
from pydantic import BaseModel

from app.providers.llm_router import (
    MAX_IN_FLIGHT,
    OVERLOAD_COOLDOWN_S,
    LLMRouter,
    LLMUnavailable,
    Provider,
)


class Verdict(BaseModel):
    supported: bool
    reason: str


GROQ = Provider(name="groq", base_url="https://groq.test/v1", api_key="k1", model="big")
GEMINI = Provider(name="gemini", base_url="https://gemini.test/v1", api_key="k2", model="lite")


def completion(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "c1",
            "object": "chat.completion",
            "created": 0,
            "model": "m",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content},
                }
            ],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        },
    )


def router_with(handler, routes) -> LLMRouter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LLMRouter(routes, http_client=client)


VALID = json.dumps({"supported": True, "reason": "quote says so"})


class FakeTime:
    """A clock and a sleep that advance together, so waiting costs no real time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def paced(handler, routes) -> tuple[LLMRouter, FakeTime]:
    router = router_with(handler, routes)
    t = FakeTime()
    router.clock, router.sleep = t.clock, t.sleep
    return router, t


async def test_returns_a_validated_object_from_the_first_provider():
    router = router_with(lambda req: completion(VALID), {"checker": [GROQ, GEMINI]})
    result = await router.structured("checker", "Is the claim supported?", Verdict)
    assert result.value == Verdict(supported=True, reason="quote says so")
    assert result.provider == "groq"


def by_host(responses: dict[str, httpx.Response]):
    return lambda req: responses[req.url.host]


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_falls_back_to_the_next_provider_on_rate_limit_or_outage(status):
    router = router_with(
        by_host(
            {
                "groq.test": httpx.Response(status, json={"error": {"message": "x"}}),
                "gemini.test": completion(VALID),
            }
        ),
        {"checker": [GROQ, GEMINI]},
    )
    result = await router.structured("checker", "Is the claim supported?", Verdict)
    assert result.provider == "gemini"


async def test_invalid_json_is_retried_once_on_the_same_provider_with_feedback():
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.content.decode())
        return completion('{"supported": "maybe"}') if len(seen) == 1 else completion(VALID)

    router = router_with(handler, {"checker": [GROQ, GEMINI]})
    result = await router.structured("checker", "Is the claim supported?", Verdict)
    assert (result.provider, result.value.supported) == ("groq", True)
    assert "did not match the required schema" in seen[1]


async def test_provider_that_keeps_returning_invalid_json_is_skipped():
    router = router_with(
        by_host({"groq.test": completion("not json at all"), "gemini.test": completion(VALID)}),
        {"checker": [GROQ, GEMINI]},
    )
    result = await router.structured("checker", "Is the claim supported?", Verdict)
    assert result.provider == "gemini"


async def test_raises_when_every_provider_fails():
    router, _ = paced(lambda req: httpx.Response(429, json={}), {"checker": [GROQ, GEMINI]})
    with pytest.raises(LLMUnavailable):
        await router.structured("checker", "Is the claim supported?", Verdict)


async def test_each_successful_call_reports_its_usage():
    records = []
    router = router_with(lambda req: completion(VALID), {"checker": [GROQ]})
    router.on_usage(records.append)
    await router.structured("checker", "Is the claim supported?", Verdict)
    (record,) = records
    assert (record.role, record.provider, record.model) == ("checker", "groq", "big")
    assert (record.prompt_tokens, record.completion_tokens) == (120, 30)
    assert record.latency_ms >= 0


async def test_rate_limited_provider_is_skipped_until_its_cooldown_ends():
    calls: list[str] = []
    clock = [1000.0]

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if req.url.host == "groq.test":
            return httpx.Response(429, json={})
        return completion(VALID)

    router = router_with(handler, {"checker": [GROQ, GEMINI]})
    router.clock = lambda: clock[0]
    await router.structured("checker", "q1", Verdict)  # groq 429 -> gemini
    await router.structured("checker", "q2", Verdict)  # groq cooling down -> gemini only
    clock[0] += 120
    await router.structured("checker", "q3", Verdict)  # cooldown over -> groq tried again
    assert calls == ["groq.test", "gemini.test", "gemini.test", "groq.test", "gemini.test"]


def test_a_role_without_any_configured_provider_is_reported_missing():
    router = LLMRouter({"checker": [GROQ], "writer": []})
    assert router.has_role("checker")
    assert not router.has_role("writer")
    assert not router.has_role("judge")


# ── pacing under free-tier limits ─────────────────────────────────────────────


async def test_when_every_provider_is_rate_limited_the_router_waits_for_the_soonest_one():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if len(calls) == 1:
            return httpx.Response(429, json={}, headers={"retry-after": "3"})
        return completion(VALID)

    router, t = paced(handler, {"checker": [GROQ]})
    result = await router.structured("checker", "q", Verdict)

    assert result.provider == "groq"
    assert t.slept == [3.0]  # the provider's own Retry-After, not a fixed penalty
    assert calls == ["groq.test", "groq.test"]


async def test_the_router_gives_up_when_the_wait_would_be_too_long():
    router, t = paced(
        lambda req: httpx.Response(429, json={}, headers={"retry-after": "600"}),
        {"checker": [GROQ]},
    )
    with pytest.raises(LLMUnavailable):
        await router.structured("checker", "q", Verdict)
    assert t.slept == []


async def test_an_overloaded_model_is_rested_briefly_instead_of_retried_on_every_call():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if req.url.host == "gemini.test":
            return httpx.Response(503, json={"error": {"message": "high demand"}})
        return completion(VALID)

    router, t = paced(handler, {"writer": [GEMINI, GROQ]})
    await router.structured("writer", "q1", Verdict)
    await router.structured("writer", "q2", Verdict)  # gemini resting: straight to groq
    t.now += OVERLOAD_COOLDOWN_S + 1
    await router.structured("writer", "q3", Verdict)
    assert calls == ["gemini.test", "groq.test", "groq.test", "gemini.test", "groq.test"]


async def test_each_model_has_a_cap_on_calls_in_flight():
    in_flight = 0
    peak = 0

    async def slow_handler(req: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return completion(VALID)

    router = router_with(slow_handler, {"checker": [GROQ]})
    await asyncio.gather(*(router.structured("checker", f"q{i}", Verdict) for i in range(10)))
    assert peak == MAX_IN_FLIGHT


async def test_a_model_that_hangs_is_rested_like_an_overloaded_one():
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.host)
        if req.url.host == "gemini.test":
            raise httpx.ReadTimeout("no answer", request=req)
        return completion(VALID)

    router, _ = paced(handler, {"writer": [GEMINI, GROQ]})
    await router.structured("writer", "q1", Verdict)
    await router.structured("writer", "q2", Verdict)
    assert calls == ["gemini.test", "groq.test", "groq.test"]
