"""Role-based AI model router (SYSTEM_DESIGN.md §10.0).

Stages ask for a *role* (judge, writer, reader, checker), never a model. Every provider speaks the
OpenAI chat-completions format, so one SDK covers them all. Answers are validated against a
Pydantic schema: invalid JSON gets one corrective retry on the same provider; rate limits, outages
or repeated invalid output move the request to the next provider in the role's chain.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import httpx2
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, RateLimitError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, ValidationError

JSON_RETRIES = 1  # corrective retries per provider before falling back
RATE_LIMIT_COOLDOWN_S = 60.0  # skip a provider this long after it rate-limits us


class LLMUnavailable(RuntimeError):
    """Every provider for a role failed."""


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True, slots=True)
class UsageRecord:
    role: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass(frozen=True, slots=True)
class Structured[M: BaseModel]:
    value: M
    provider: str
    model: str


def _system_prompt(schema: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object and nothing else. It must match this JSON schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


class LLMRouter:
    def __init__(
        self,
        routes: Mapping[str, Sequence[Provider]],
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._routes = routes
        self._clients = {
            p.name: AsyncOpenAI(
                api_key=p.api_key, base_url=p.base_url, max_retries=0, http_client=http_client
            )
            for providers in routes.values()
            for p in providers
        }
        self._cooldown_until: dict[str, float] = {}
        self._usage_sinks: list[Callable[[UsageRecord], None]] = []
        self.clock: Callable[[], float] = time.monotonic

    def on_usage(self, sink: Callable[[UsageRecord], None]) -> None:
        self._usage_sinks.append(sink)

    async def structured[M: BaseModel](
        self, role: str, prompt: str, schema: type[M]
    ) -> Structured[M]:
        failures: list[str] = []
        for provider in self._routes[role]:
            if self._cooldown_until.get(provider.name, 0.0) > self.clock():
                failures.append(f"{provider.name}: cooling down after a rate limit")
                continue
            try:
                return await self._ask(role, provider, prompt, schema)
            except RateLimitError:
                self._cooldown_until[provider.name] = self.clock() + RATE_LIMIT_COOLDOWN_S
                failures.append(f"{provider.name}: rate limited")
            except (APIStatusError, APIConnectionError) as exc:
                failures.append(f"{provider.name}: {type(exc).__name__}")
            except ValidationError:
                failures.append(f"{provider.name}: invalid JSON")
        raise LLMUnavailable(f"All providers failed for role '{role}': {'; '.join(failures)}")

    async def _ask[M: BaseModel](
        self, role: str, provider: Provider, prompt: str, schema: type[M]
    ) -> Structured[M]:
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": _system_prompt(schema)},
            {"role": "user", "content": prompt},
        ]
        for attempt in range(JSON_RETRIES + 1):
            started = time.perf_counter()
            response = await self._clients[provider.name].chat.completions.create(
                model=provider.model,
                messages=messages,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or ""
            self._report(role, provider, response.usage, started)
            try:
                return Structured(
                    schema.model_validate_json(content), provider.name, provider.model
                )
            except ValidationError as exc:
                if attempt == JSON_RETRIES:
                    raise
                messages += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Your previous answer did not match the required schema: "
                        f"{exc.errors(include_url=False)}. Reply with corrected JSON only.",
                    },
                ]
        raise AssertionError("unreachable")

    def _report(self, role: str, provider: Provider, usage: Any, started: float) -> None:
        record = UsageRecord(
            role=role,
            provider=provider.name,
            model=provider.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        for sink in self._usage_sinks:
            sink(record)
