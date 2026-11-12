"""Which free models serve which role (SYSTEM_DESIGN.md §10.0).

Order = preference; the router falls back down the chain on rate limits, outages or invalid JSON.
Providers without an API key in `.env` are left out. Model IDs and the writer's primary are
confirmed by the Phase-0 bake-off; change them here, not in calling code.
"""

from __future__ import annotations

from typing import Literal

from app.config import Settings
from app.providers.llm_router import Provider

Role = Literal["judge", "writer", "reader", "checker"]

GROQ_URL = "https://api.groq.com/openai/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
MISTRAL_URL = "https://api.mistral.ai/v1"

# (provider key, model id) per role, best first.
ROLE_CHAINS: dict[Role, list[tuple[str, str]]] = {
    "judge": [
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3.8-flash"),
        ("mistral", "mistral-medium-latest"),
    ],
    "writer": [
        ("gemini", "gemini-3.8-flash"),
        ("groq", "openai/gpt-oss-120b"),
        ("mistral", "mistral-medium-latest"),
    ],
    "reader": [
        ("gemini", "gemini-3.5-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
        ("mistral", "mistral-small-latest"),
    ],
    "checker": [  # a different model family from the writer
        ("groq", "qwen/qwen3.8-27b"),
        ("gemini", "gemini-3.5-flash-lite"),
        ("mistral", "mistral-small-latest"),
    ],
}


def build_routes(settings: Settings) -> dict[str, list[Provider]]:
    endpoints = {
        "groq": (GROQ_URL, settings.groq_api_key),
        "gemini": (GEMINI_URL, settings.gemini_api_key),
        "mistral": (MISTRAL_URL, settings.mistral_api_key),
    }
    routes: dict[str, list[Provider]] = {}
    for role, chain in ROLE_CHAINS.items():
        providers = []
        for key, model in chain:
            url, secret = endpoints[key]
            if secret is None:
                continue
            # One entry per model: free-tier limits (and our cooldowns) are per model.
            providers.append(
                Provider(
                    name=f"{key}:{model}",
                    base_url=url,
                    api_key=secret.get_secret_value(),
                    model=model,
                )
            )
        routes[role] = providers
    return routes
