"""Adapter for Claude through Anthropic's official Python SDK.

Uses structured outputs (`messages.parse` with the Pydantic schema), so Claude's answer is
constrained to the schema rather than asked for in the prompt. The router still validates the
returned JSON itself, like every other provider's.
"""

from __future__ import annotations

import anthropic
import httpx2
from pydantic import BaseModel

from app.providers.model_client import Message, Overloaded, RateLimited, Rejected, Reply

MAX_TOKENS = 16_000  # room for adaptive thinking plus the JSON answer
TIMEOUT_S = 120.0  # thinking takes longer than the free models' typical reply


class AnthropicClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            max_retries=0,
            timeout=TIMEOUT_S,
            http_client=http_client,
        )

    async def reply(
        self, model: str, system: str, messages: list[Message], schema: type[BaseModel]
    ) -> Reply:
        try:
            response = await self._client.messages.parse(
                model=model,
                max_tokens=MAX_TOKENS,
                messages=messages,  # type: ignore[arg-type]
                output_format=schema,
                system=system or anthropic.omit,
            )
        except anthropic.RateLimitError as exc:
            raise RateLimited(_retry_after(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code in (503, 529) or exc.status_code >= 500:
                raise Overloaded(f"{exc.status_code}") from exc
            raise Rejected(f"{exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:  # includes timeouts
            raise Overloaded(type(exc).__name__) from exc
        text = next((b.text for b in response.content if b.type == "text"), "")
        return Reply(
            content=text,
            prompt_tokens=response.usage.input_tokens,
            completion_tokens=response.usage.output_tokens,
        )


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    try:
        return float(exc.response.headers.get("retry-after", ""))
    except ValueError:
        return None
