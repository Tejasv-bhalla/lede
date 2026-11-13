"""Model settings: which model does each job, with whose key.

Every job (role) starts on the free chain from `llm_roles`. A user may save keys for other
providers and pick one model per job; that model goes first in the job's chain and the free
models stay behind it, so a bad key, an exhausted quota or an outage never fails a run.

Keys are encrypted with SETTINGS_SECRET before they are stored and are never returned by the API
(only their last four characters, so a user can tell which key is saved).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, get_args

import httpx2
from pydantic import BaseModel

from app.config import Settings
from app.db.store import Store
from app.providers.catalogue import PROVIDERS, ProviderId, ProviderSpec
from app.providers.llm_roles import Role, build_routes
from app.providers.llm_router import LLMRouter, LLMUnavailable, Provider
from app.providers.model_client import ProviderFailure
from app.services.sealing import Sealer

SETTING_KEY = "models"
ROLES: tuple[Role, ...] = get_args(Role)
NO_KEY = "not-needed"  # sent to keyless local endpoints, which ignore it


class NeedsSecret(RuntimeError):
    """SETTINGS_SECRET is not set, so keys cannot be stored safely."""


class NoKey(RuntimeError):
    """A job was pointed at a provider that has no saved key."""


class Choice(BaseModel):
    provider: ProviderId
    model: str


class _Ping(BaseModel):
    ok: bool


@dataclass(frozen=True, slots=True)
class TestResult:
    ok: bool
    latency_ms: int
    error: str | None = None


class ModelService:
    def __init__(
        self,
        store: Store,
        settings: Settings,
        router: LLMRouter,
        *,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._store, self._settings, self._router, self._http = store, settings, router, http_client
        secret = settings.settings_secret
        self._sealer = Sealer(secret.get_secret_value()) if secret else None
        self._data: dict[str, Any] = {"keys": {}, "roles": {}}

    def _specs(self) -> list[ProviderSpec]:
        return [p for p in PROVIDERS.values() if not p.local or self._settings.claude_code_local]

    def _available(self, provider: str) -> bool:
        spec = PROVIDERS.get(provider)  # type: ignore[call-overload]
        if spec is None or spec not in self._specs():
            return False
        return spec.local or provider in self._data["keys"]

    # ── startup ───────────────────────────────────────────────────────────────

    async def load(self) -> None:
        """Apply saved choices to the router (call once at startup)."""
        self._data = await self._store.get_setting(SETTING_KEY) or {"keys": {}, "roles": {}}
        self._apply()

    # ── reading ───────────────────────────────────────────────────────────────

    def view(self) -> dict[str, Any]:
        free = build_routes(self._settings)
        keys = self._data["keys"]
        return {
            "can_save_keys": self._sealer is not None,
            "providers": [
                {
                    "id": spec.id,
                    "label": spec.label,
                    "suggested_models": list(spec.suggested_models),
                    "needs_base_url": spec.needs_base_url,
                    "key_optional": spec.key_optional,
                    "local": spec.local,
                    "has_key": spec.local or spec.id in keys,
                    "key_hint": keys.get(spec.id, {}).get("hint"),
                    "base_url": keys.get(spec.id, {}).get("base_url"),
                }
                for spec in self._specs()
            ],
            "roles": {role: self._data["roles"].get(role) for role in ROLES},
            "free": {role: [p.model for p in free.get(role, [])] for role in ROLES},
        }

    # ── changing ──────────────────────────────────────────────────────────────

    async def save_key(self, provider: ProviderId, api_key: str, base_url: str | None) -> None:
        if self._sealer is None:
            raise NeedsSecret("Saving keys needs SETTINGS_SECRET in .env (any long random string).")
        spec = PROVIDERS[provider]
        if spec.local:
            raise ValueError(f"{spec.label} needs no key.")
        api_key = api_key.strip() or (NO_KEY if spec.key_optional else "")
        if not api_key:
            raise ValueError("Enter the API key.")
        if spec.needs_base_url and not (base_url or "").strip():
            raise ValueError("Enter the endpoint URL, e.g. http://localhost:11434/v1.")
        self._data["keys"][provider] = {
            "sealed": self._sealer.seal(api_key),
            "hint": None if api_key == NO_KEY else api_key[-4:],
            "base_url": (base_url or "").strip() or None,
        }
        await self._save()

    async def delete_key(self, provider: ProviderId) -> None:
        self._data["keys"].pop(provider, None)
        self._data["roles"] = {
            r: c for r, c in self._data["roles"].items() if c and c["provider"] != provider
        }
        await self._save()

    async def choose(self, choices: dict[Role, Choice | None]) -> None:
        for role, choice in choices.items():
            if choice is None:
                self._data["roles"].pop(role, None)
                continue
            if not self._available(choice.provider):
                raise NoKey(f"{PROVIDERS[choice.provider].label} isn't set up on this server.")
            self._data["roles"][role] = choice.model_dump()
        await self._save()

    async def test(self, provider: ProviderId, model: str) -> TestResult:
        """One tiny structured call with the saved key, so a bad key or model name shows up
        here rather than in the middle of a run."""
        p = self._provider(provider, model)
        if p is None:
            return TestResult(False, 0, "No saved key for this provider.")
        probe = LLMRouter({"probe": [p]}, http_client=self._http)
        started = time.perf_counter()
        try:
            await probe.structured("probe", 'Reply with {"ok": true}.', _Ping)
        except (LLMUnavailable, ProviderFailure) as exc:
            return TestResult(False, _ms(started), _plain(str(exc)))
        return TestResult(True, _ms(started))

    # ── internals ─────────────────────────────────────────────────────────────

    async def _save(self) -> None:
        await self._store.put_setting(SETTING_KEY, self._data)
        self._apply()

    def _provider(self, provider: str, model: str) -> Provider | None:
        if not self._available(provider):
            return None
        spec = PROVIDERS[provider]  # type: ignore[index]
        if spec.local:
            return Provider(
                name=f"yours:{provider}:{model}",
                base_url=self._settings.claude_code_command,  # the command to run
                api_key="",
                model=model,
                kind=spec.kind,
            )
        saved = self._data["keys"].get(provider)
        if saved is None or self._sealer is None:
            return None
        key = self._sealer.open(saved["sealed"])
        if key is None:  # sealed with a different SETTINGS_SECRET
            return None
        return Provider(
            name=f"yours:{provider}:{model}",
            base_url=saved.get("base_url") or spec.base_url,
            api_key=key,
            model=model,
            kind=spec.kind,
        )

    def _apply(self) -> None:
        routes = build_routes(self._settings)
        for role in ROLES:
            choice = self._data["roles"].get(role)
            mine = self._provider(choice["provider"], choice["model"]) if choice else None
            if mine is not None:
                routes[role] = [mine, *routes.get(role, [])]
        self._router.set_routes(routes)


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _plain(error: str) -> str:
    if "401" in error or "403" in error or "Rejected" in error:
        return "The provider rejected the request: check the key and the model name."
    if "rate limited" in error:
        return "The provider is rate limiting this key right now; try again in a minute."
    if "overloaded" in error:
        return "The provider is busy or unreachable right now; try again shortly."
    return error
