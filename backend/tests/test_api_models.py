"""Model settings through the API: bring your own key and model per job, free models behind."""

import json
from collections.abc import AsyncIterator

import httpx
import httpx2
import pytest
from pydantic import SecretStr

from app.api.app import create_app
from app.config import Settings
from app.db.store import Store
from app.providers.llm_roles import build_routes
from app.providers.llm_router import LLMRouter
from app.services.models import ModelService

CODE = "open-sesame"
AUTH = {"X-Access-Code": CODE}
CLAUDE_KEY = "sk-ant-test-0000-SECRET-9f3a"


def claude_reply(req: httpx2.Request) -> httpx2.Response:
    sent = req.headers.get("x-api-key") or req.headers.get("authorization", "").removeprefix(
        "Bearer "
    )
    if sent != CLAUDE_KEY:
        return httpx2.Response(401, json={"type": "error", "error": {"type": "authentication"}})
    body = json.loads(req.content)
    assert body["model"].startswith("claude-")
    return httpx2.Response(
        200,
        json={
            "id": "m",
            "type": "message",
            "role": "assistant",
            "model": body["model"],
            "content": [{"type": "text", "text": '{"ok": true}'}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 5, "output_tokens": 3},
        },
    )


def settings(secret: str | None = "a-long-local-secret") -> Settings:
    return Settings(
        _env_file=None,  # tests must not depend on this machine's .env
        demo_access_code=SecretStr(CODE),
        groq_api_key=SecretStr("free-groq"),
        settings_secret=SecretStr(secret) if secret else None,
    )


async def make_client(store: Store, s: Settings) -> tuple[httpx.AsyncClient, LLMRouter]:
    http = httpx2.AsyncClient(transport=httpx2.MockTransport(claude_reply))
    router = LLMRouter(build_routes(s), http_client=http)
    models = ModelService(store, s, router, http_client=http)
    await models.load()
    app = create_app(s, store=store, models=models)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    return client, router


@pytest.fixture
async def store(tmp_path) -> AsyncIterator[Store]:
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    await store.create_all()
    yield store
    await store.dispose()


@pytest.fixture
async def api(store) -> AsyncIterator[tuple[httpx.AsyncClient, LLMRouter]]:
    client, router = await make_client(store, settings())
    async with client:
        yield client, router


async def test_every_job_starts_on_the_free_models(api):
    client, _ = api
    data = (await client.get("/api/models", headers=AUTH)).json()

    assert set(data["roles"]) == {"judge", "writer", "reader", "checker"}
    assert all(choice is None for choice in data["roles"].values())
    assert data["free"]["writer"]  # the free chain is shown so the user knows the fallback
    claude = next(p for p in data["providers"] if p["id"] == "anthropic")
    assert (claude["has_key"], claude["key_hint"]) == (False, None)


async def test_a_saved_key_is_never_sent_back_only_its_last_four_characters(api):
    client, _ = api
    saved = await client.put(
        "/api/models/keys/anthropic", headers=AUTH, json={"api_key": CLAUDE_KEY}
    )
    data = await client.get("/api/models", headers=AUTH)

    assert saved.status_code == 200
    assert CLAUDE_KEY not in saved.text and CLAUDE_KEY not in data.text
    claude = next(p for p in data.json()["providers"] if p["id"] == "anthropic")
    assert (claude["has_key"], claude["key_hint"]) == (True, "9f3a")


async def test_keys_cannot_be_saved_without_a_settings_secret(store):
    client, _ = await make_client(store, settings(secret=None))
    async with client:
        r = await client.put(
            "/api/models/keys/anthropic", headers=AUTH, json={"api_key": CLAUDE_KEY}
        )
    assert r.status_code == 409
    assert "SETTINGS_SECRET" in r.json()["detail"]


async def test_choosing_claude_for_writing_puts_it_first_with_the_free_models_behind(api):
    client, router = api
    free_writers = [p.name for p in router.routes()["writer"]]
    await client.put("/api/models/keys/anthropic", headers=AUTH, json={"api_key": CLAUDE_KEY})
    r = await client.put(
        "/api/models/roles",
        headers=AUTH,
        json={"writer": {"provider": "anthropic", "model": "claude-opus-5-5"}},
    )

    assert r.status_code == 200
    writer = router.routes()["writer"]
    assert (writer[0].kind, writer[0].model) == ("anthropic", "claude-opus-5-5")
    assert [p.name for p in writer[1:]] == free_writers
    assert [p.name for p in router.routes()["reader"]] == [
        p.name for p in build_routes(settings())["reader"]
    ]

    await client.put("/api/models/roles", headers=AUTH, json={"writer": None})
    assert [p.name for p in router.routes()["writer"]] == free_writers


async def test_a_provider_without_a_key_cannot_be_chosen(api):
    client, _ = api
    r = await client.put(
        "/api/models/roles",
        headers=AUTH,
        json={"judge": {"provider": "anthropic", "model": "claude-opus-5-5"}},
    )
    assert r.status_code == 409


async def test_choices_survive_a_restart(store):
    client, _ = await make_client(store, settings())
    async with client:
        await client.put("/api/models/keys/anthropic", headers=AUTH, json={"api_key": CLAUDE_KEY})
        await client.put(
            "/api/models/roles",
            headers=AUTH,
            json={"judge": {"provider": "anthropic", "model": "claude-sonnet-5-5"}},
        )

    _, router = await make_client(store, settings())
    assert router.routes()["judge"][0].model == "claude-sonnet-5-5"


async def test_a_key_can_be_tested_before_relying_on_it(api):
    client, _ = api
    await client.put("/api/models/keys/anthropic", headers=AUTH, json={"api_key": CLAUDE_KEY})
    ok = await client.post(
        "/api/models/test",
        headers=AUTH,
        json={"provider": "anthropic", "model": "claude-haiku-5-5"},
    )
    assert ok.json()["ok"] is True

    await client.put("/api/models/keys/anthropic", headers=AUTH, json={"api_key": "wrong"})
    bad = (
        await client.post(
            "/api/models/test",
            headers=AUTH,
            json={"provider": "anthropic", "model": "claude-haiku-5-5"},
        )
    ).json()
    assert bad["ok"] is False and bad["error"]


async def test_claude_code_is_offered_only_when_switched_on_for_this_computer(store):
    client, _ = await make_client(store, settings())
    async with client:
        listed = {
            p["id"] for p in (await client.get("/api/models", headers=AUTH)).json()["providers"]
        }
        refused = await client.put(
            "/api/models/roles",
            headers=AUTH,
            json={"writer": {"provider": "claude_code", "model": "opus"}},
        )
    assert "claude_code" not in listed
    assert refused.status_code == 409

    local = settings().model_copy(update={"claude_code_local": True})
    client, router = await make_client(store, local)
    async with client:
        provider = next(
            p
            for p in (await client.get("/api/models", headers=AUTH)).json()["providers"]
            if p["id"] == "claude_code"
        )
        chosen = await client.put(
            "/api/models/roles",
            headers=AUTH,
            json={"writer": {"provider": "claude_code", "model": "opus"}},
        )
    assert provider["has_key"] and provider["local"]  # no key needed: it uses this login
    assert chosen.status_code == 200
    assert (router.routes()["writer"][0].kind, router.routes()["writer"][0].model) == (
        "claude_code",
        "opus",
    )
