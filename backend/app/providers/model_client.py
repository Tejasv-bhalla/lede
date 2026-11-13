"""What the model router needs from any provider: one structured reply, with failures sorted
into the few kinds the router reacts to differently.

Each provider family (OpenAI-compatible endpoints, Anthropic, ...) gets a small adapter that maps
its own SDK's errors onto these, so the router's fallback and cooldown rules work the same for
all of them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True, slots=True)
class Reply:
    content: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


Message = dict[str, str]  # {"role": "user" | "assistant", "content": ...}


class ModelClient(Protocol):
    async def reply(
        self, model: str, system: str, messages: list[Message], schema: type[BaseModel]
    ) -> Reply:
        """One answer as JSON text matching `schema`. Raises a ProviderFailure on failure."""
        ...


class ProviderFailure(Exception):
    """The provider could not answer this time; the router may try another."""


class RateLimited(ProviderFailure):
    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("rate limited")
        self.retry_after = retry_after


class Overloaded(ProviderFailure):
    """Busy (503/529) or not answering in time: usually a short demand spike."""


class MalformedJson(ProviderFailure):
    """The provider rejected its own model's output as invalid JSON: worth a corrective retry."""


class Rejected(ProviderFailure):
    """Any other error (bad key, unknown model, bad request): skip this provider for the call."""
