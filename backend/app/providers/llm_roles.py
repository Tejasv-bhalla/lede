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
# Each Groq model has its own free allowance (1K requests/day, 8K tokens/min, measured 13 Nov
# 2026), so different Groq models in one chain add capacity. Gemini Flash is often overloaded
# for free users; Flash-Lite answers reliably.
# Each Gemini model has its own free daily allowance (gemini-3.8-flash and gemini-3.7-flash: 20
# requests a day each), so several Gemini models give far more free capacity than one. Checked
# against a free key on 13 Nov 2026: Pro, 4 Argon/Carbon are paid only (limit 0); Gemma models
# fail with structured replies; gemini-flash-latest is an alias of an already-listed model.
ROLE_CHAINS: dict[Role, list[tuple[str, str]]] = {
    "judge": [
        ("groq", "openai/gpt-oss-120b"),
        ("groq", "qwen/qwen3.8-27b"),
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.7-flash"),
        ("gemini", "gemini-3.6-flash"),
        ("gemini", "gemini-3.5-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
        ("gemini", "gemini-3.1-flash-lite"),
        ("mistral", "mistral-medium-latest"),
    ],
    "writer": [  # last resorts keep a run alive; the fact-check still guards every claim
        ("gemini", "gemini-3.8-flash"),
        ("gemini", "gemini-3.7-flash"),
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3.6-flash"),
        ("groq", "qwen/qwen3.8-27b"),
        ("mistral", "mistral-medium-latest"),
        ("gemini", "gemini-3.5-flash"),  # slow (about a minute when busy), so kept late
        ("gemini", "gemini-3.5-flash-lite"),
        ("gemini", "gemini-3.1-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
    ],
    "reader": [  # the busiest role (one call per page): fast models on separate allowances
        ("gemini", "gemini-3.5-flash-lite"),
        ("gemini", "gemini-3.1-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
        ("groq", "qwen/qwen3.8-27b"),
        ("mistral", "mistral-small-latest"),
    ],
    "checker": [  # checks quotes and drafts; ideally a different family from the writer
        ("groq", "qwen/qwen3.8-27b"),
        ("gemini", "gemini-3.5-flash-lite"),
        # Backups on separate free allowances: with only two models, both resting at once
        # failed a whole run (13 Nov 2026).
        ("gemini", "gemini-3.1-flash-lite"),
        ("groq", "openai/gpt-oss-20b"),
        ("groq", "openai/gpt-oss-120b"),
        ("gemini", "gemini-3.6-flash"),
        ("gemini", "gemini-3.8-flash"),
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
