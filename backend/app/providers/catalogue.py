"""Model providers a user can bring their own key for (the free defaults live in llm_roles)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.providers.llm_roles import GEMINI_URL, GROQ_URL
from app.providers.llm_router import Kind

ProviderId = Literal["anthropic", "openai", "gemini", "groq", "openrouter", "custom", "claude_code"]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    id: ProviderId
    label: str
    kind: Kind
    base_url: str  # "" = the SDK's default; custom endpoints supply their own
    suggested_models: tuple[str, ...] = ()
    needs_base_url: bool = False
    key_optional: bool = False  # e.g. a local Ollama
    local: bool = False  # uses this computer's own login; no key, local demos only


PROVIDERS: dict[ProviderId, ProviderSpec] = {
    p.id: p
    for p in (
        ProviderSpec(
            "anthropic",
            "Anthropic (Claude)",
            "anthropic",
            "",
            ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"),
        ),
        ProviderSpec("openai", "OpenAI", "openai", "https://api.openai.com/v1"),
        ProviderSpec(
            "gemini",
            "Google Gemini",
            "openai",
            GEMINI_URL,
            (
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ),
        ),
        ProviderSpec(
            "groq", "Groq", "openai", GROQ_URL, ("openai/gpt-oss-120b", "qwen/qwen3.8-27b")
        ),
        ProviderSpec("openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1"),
        ProviderSpec(
            "claude_code",
            "Claude Code on this computer",
            "claude_code",
            "",
            ("opus", "sonnet", "haiku"),
            local=True,
        ),
        ProviderSpec(
            "custom",
            "Other OpenAI-compatible endpoint (e.g. Ollama)",
            "openai",
            "",
            needs_base_url=True,
            key_optional=True,
        ),
    )
}
