"""Role-based AI model router (SYSTEM_DESIGN.md §10.0).

Stages ask for a *role* (judge, writer, reader, checker), never a model. Each role has a chain of
providers, best first. Answers are validated against a Pydantic schema: invalid JSON gets one
corrective retry on the same provider; rate limits, outages or repeated invalid output move the
request to the next provider in the role's chain.

Providers differ only behind a small adapter (`model_client.ModelClient`), so the same fallback
and cooldown rules apply to OpenAI-compatible endpoints, Anthropic, or anything added later.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import httpx2
from pydantic import BaseModel, ValidationError

from app.providers.model_client import (
    MalformedJson,
    Message,
    ModelClient,
    Overloaded,
    RateLimited,
    Rejected,
)

JSON_RETRIES = 1  # corrective retries per provider before falling back
RATE_LIMIT_COOLDOWN_S = 60.0  # rest after a rate limit when the provider doesn't say how long
OVERLOAD_COOLDOWN_S = 30.0  # rest after "overloaded" (503/529): usually brief demand spikes
MAX_WAIT_S = 65.0  # when a whole chain is resting, wait up to one per-minute window for a model
MAX_IN_FLIGHT = 3  # concurrent calls per model: bursts are what trip per-minute free limits

Kind = Literal["openai", "anthropic", "claude_code"]


class LLMUnavailable(RuntimeError):
    """Every provider for a role failed."""


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str
    kind: Kind = "openai"


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


def make_client(provider: Provider, http_client: httpx2.AsyncClient | None) -> ModelClient:
    if provider.kind == "claude_code":  # base_url carries the command to run
        from app.providers.claude_code import ClaudeCodeClient

        return ClaudeCodeClient(command=provider.base_url)
    if provider.kind == "anthropic":
        from app.providers.anthropic_client import AnthropicClient

        return AnthropicClient(
            api_key=provider.api_key, base_url=provider.base_url or None, http_client=http_client
        )
    from app.providers.openai_compat import OpenAICompatClient

    return OpenAICompatClient(
        base_url=provider.base_url, api_key=provider.api_key, http_client=http_client
    )


class LLMRouter:
    def __init__(
        self,
        routes: Mapping[str, Sequence[Provider]],
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._http = http_client
        self._clients: dict[str, ModelClient] = {}
        self._slots: dict[str, asyncio.Semaphore] = {}
        self._cooldown_until: dict[str, float] = {}
        self._usage_sinks: list[Callable[[UsageRecord], None]] = []
        self.clock: Callable[[], float] = time.monotonic
        self.sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
        self.set_routes(routes)

    def set_routes(self, routes: Mapping[str, Sequence[Provider]]) -> None:
        """Swap the chains (e.g. after the user changes model settings). Cooldowns and
        in-flight limits carry over for providers that stay."""
        self._routes = {role: list(chain) for role, chain in routes.items()}
        for p in (p for chain in self._routes.values() for p in chain):
            # A changed key or model under the same name gets a fresh client.
            key = _client_key(p)
            if key not in self._clients:
                self._clients[key] = make_client(p, self._http)
            self._slots.setdefault(p.name, asyncio.Semaphore(MAX_IN_FLIGHT))

    def routes(self) -> Mapping[str, Sequence[Provider]]:
        return self._routes

    def has_role(self, role: str) -> bool:
        return bool(self._routes.get(role))

    def on_usage(self, sink: Callable[[UsageRecord], None]) -> None:
        self._usage_sinks.append(sink)

    async def structured[M: BaseModel](
        self, role: str, prompt: str, schema: type[M]
    ) -> Structured[M]:
        """Ask the role's providers in order. If they are all resting after rate limits or
        overloads, wait for the soonest one (up to MAX_WAIT_S) rather than failing the run."""
        deadline = self.clock() + MAX_WAIT_S
        while True:
            chain = self._routes.get(role, [])
            failures: list[str] = []
            for provider in chain:
                if self._cooldown_until.get(provider.name, 0.0) > self.clock():
                    failures.append(f"{provider.name}: resting after a rate limit or overload")
                    continue
                try:
                    async with self._slots[provider.name]:
                        return await self._ask(role, provider, prompt, schema)
                except RateLimited as exc:
                    self._rest(provider, exc.retry_after or RATE_LIMIT_COOLDOWN_S)
                    failures.append(f"{provider.name}: rate limited")
                except Overloaded as exc:
                    self._rest(provider, OVERLOAD_COOLDOWN_S)
                    failures.append(f"{provider.name}: overloaded {exc}".rstrip())
                except (Rejected, MalformedJson) as exc:
                    failures.append(f"{provider.name}: {type(exc).__name__} {exc}".rstrip())
                except ValidationError:
                    failures.append(f"{provider.name}: invalid JSON")
            soonest = min((self._cooldown_until.get(p.name, 0.0) for p in chain), default=0.0)
            if not (self.clock() < soonest <= deadline):
                raise LLMUnavailable(
                    f"All providers failed for role '{role}': {'; '.join(failures)}"
                )
            await self.sleep(soonest - self.clock())

    def _rest(self, provider: Provider, seconds: float) -> None:
        self._cooldown_until[provider.name] = self.clock() + seconds

    async def _ask[M: BaseModel](
        self, role: str, provider: Provider, prompt: str, schema: type[M]
    ) -> Structured[M]:
        client = self._clients[_client_key(provider)]
        messages: list[Message] = [{"role": "user", "content": prompt}]
        for attempt in range(JSON_RETRIES + 1):
            started = time.perf_counter()
            try:
                reply = await client.reply(provider.model, "", messages, schema)
            except MalformedJson:
                if attempt == JSON_RETRIES:
                    raise
                content, problem = "", "it was not valid JSON"
            else:
                content = reply.content
                self._report(role, provider, reply.prompt_tokens, reply.completion_tokens, started)
                try:
                    return Structured(
                        schema.model_validate_json(content), provider.name, provider.model
                    )
                except ValidationError as exc:
                    if attempt == JSON_RETRIES:
                        raise
                    problem = str(exc.errors(include_url=False))
            if content:
                messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": "Your previous answer did not match the required schema: "
                    f"{problem}. Reply with corrected JSON only.",
                }
            )
        raise AssertionError("unreachable")

    def _report(
        self, role: str, provider: Provider, prompt: int, completion: int, started: float
    ) -> None:
        record = UsageRecord(
            role=role,
            provider=provider.name,
            model=provider.model,
            prompt_tokens=prompt,
            completion_tokens=completion,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        for sink in self._usage_sinks:
            sink(record)


def _client_key(p: Provider) -> str:
    return f"{p.kind}|{p.base_url}|{hash(p.api_key)}"
