import json

import httpx2 as httpx  # the HTTP library the openai SDK is built on
import pytest
from pydantic import BaseModel

from app.providers.llm_router import LLMRouter, LLMUnavailable, Provider


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
    router = router_with(lambda req: httpx.Response(429, json={}), {"checker": [GROQ, GEMINI]})
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
