"""Adapter for every provider that speaks the OpenAI chat-completions format: Groq, Gemini's
OpenAI endpoint, Mistral, OpenAI, OpenRouter, or a local Ollama."""

from __future__ import annotations

import json
from typing import cast

import httpx2
from openai import APIConnectionError, APIStatusError, AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from app.providers.model_client import (
    MalformedJson,
    Message,
    Overloaded,
    RateLimited,
    Rejected,
    Reply,
)


def schema_instruction(schema: type[BaseModel]) -> str:
    return (
        "Reply with a single JSON object and nothing else. It must match this JSON schema:\n"
        + json.dumps(schema.model_json_schema(), separators=(",", ":"))
    )


class OpenAICompatClient:
    def __init__(
        self, *, base_url: str, api_key: str, http_client: httpx2.AsyncClient | None = None
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key, base_url=base_url, max_retries=0, http_client=http_client
        )

    async def reply(
        self, model: str, system: str, messages: list[Message], schema: type[BaseModel]
    ) -> Reply:
        instruction = f"{system}\n\n{schema_instruction(schema)}".strip()
        full = cast(
            list[ChatCompletionMessageParam],
            [{"role": "system", "content": instruction}, *messages],
        )
        try:
            response = await self._client.chat.completions.create(
                model=model, messages=full, response_format={"type": "json_object"}
            )
        except BadRequestError as exc:
            if _malformed_json(exc):
                raise MalformedJson from exc
            raise Rejected(f"{exc.status_code}") from exc
        except APIStatusError as exc:
            if exc.status_code == 429:
                raise RateLimited(_retry_after(exc)) from exc
            if exc.status_code in (503, 529):
                raise Overloaded from exc
            raise Rejected(f"{exc.status_code}") from exc
        except APIConnectionError as exc:  # includes timeouts: an overloaded model hangs
            raise Overloaded(type(exc).__name__) from exc
        usage = response.usage
        return Reply(
            content=response.choices[0].message.content or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


def _retry_after(exc: APIStatusError) -> float | None:
    """Seconds the provider asked us to wait, if it said."""
    try:
        return float(exc.response.headers.get("retry-after", ""))
    except ValueError:
        return None


def _malformed_json(exc: BadRequestError) -> bool:
    """Groq rejects its own model's output with 400 json_validate_failed; that is a bad answer
    worth one corrective retry, not a bad request."""
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error", body)
    return isinstance(error, dict) and error.get("code") == "json_validate_failed"
