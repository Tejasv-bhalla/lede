import csv
import io
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from pydantic import SecretStr

from app.api.app import create_app
from app.config import Settings
from app.db.store import Store
from app.pipeline.ports import Draft, Identity, IdentityStatus
from app.pipeline.run import PipelineDeps
from tests.scenario import PODCAST_QUOTE, PRIYA, TODAY, deps

CODE = "open-sesame"
AUTH = {"X-Access-Code": CODE}

PROFILE = {
    "company": {"name": "Ledgerly", "domain": "ledgerly.example"},
    "offer": {"product": "Ledgerly", "problem_solved": "slow month-end close"},
    "personas": [{"id": "fin", "title_patterns": ["VP Finance"], "seniority": "vp"}],
    "approved_claims": [{"id": "c1", "text": "Matches invoices to POs automatically"}],
}


@pytest.fixture
def world() -> dict[str, Callable[[], PipelineDeps]]:
    """The scripted outside world each run sees; a test may swap it before starting runs."""
    return {"deps": lambda: deps(scores={PODCAST_QUOTE.claim: 4.5})}


@pytest.fixture
async def client(tmp_path, world) -> AsyncIterator[httpx.AsyncClient]:
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    await store.create_all()
    app = create_app(
        Settings(demo_access_code=SecretStr(CODE)),
        store=store,
        deps_factory=lambda: world["deps"](),
        today=lambda: TODAY,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    await store.dispose()


async def test_access_code_check_says_whether_the_code_is_right(client):
    assert (await client.post("/api/auth/check", json={"code": "nope"})).json() == {"ok": False}
    assert (await client.post("/api/auth/check", json={"code": CODE})).json() == {"ok": True}


async def test_api_refuses_requests_without_the_access_code(client):
    assert (await client.get("/api/profile")).status_code == 401
    assert (await client.get("/api/profile", headers={"X-Access-Code": "nope"})).status_code == 401


async def test_seller_profile_is_saved_and_read_back(client):
    assert (await client.get("/api/profile", headers=AUTH)).status_code == 404

    saved = await client.put("/api/profile", json=PROFILE, headers=AUTH)
    assert saved.status_code == 200

    body = (await client.get("/api/profile", headers=AUTH)).json()
    assert body["company"]["name"] == "Ledgerly"
    assert body["tone"]["max_words"] == 100  # defaults filled in


async def test_an_invalid_profile_is_rejected_with_the_field_at_fault(client):
    bad = {**PROFILE, "personas": [{"id": "fin", "title_patterns": [], "seniority": "wizard"}]}
    r = await client.put("/api/profile", json=bad, headers=AUTH)
    assert r.status_code == 422
    assert "seniority" in r.text


CAMPAIGN = {
    "name": "Q4 finance",
    "objective": "Book demos with finance leaders",
    "persona_id": "fin",
}


async def test_campaigns_are_created_listed_read_and_updated(client):
    created = (await client.post("/api/campaigns", json=CAMPAIGN, headers=AUTH)).json()
    cid = created["id"]

    listed = (await client.get("/api/campaigns", headers=AUTH)).json()
    assert [c["id"] for c in listed] == [cid]

    changed = {**CAMPAIGN, "angle": "audit season is coming"}
    assert (
        await client.put(f"/api/campaigns/{cid}", json=changed, headers=AUTH)
    ).status_code == 200
    body = (await client.get(f"/api/campaigns/{cid}", headers=AUTH)).json()
    assert (body["id"], body["angle"]) == (cid, "audit season is coming")

    assert (await client.get("/api/campaigns/nope", headers=AUTH)).status_code == 404


async def test_validating_a_campaign_reports_conflicts_with_the_profile(client):
    await client.put("/api/profile", json=PROFILE, headers=AUTH)
    good = (await client.post("/api/campaigns", json=CAMPAIGN, headers=AUTH)).json()
    bad = (
        await client.post("/api/campaigns", json={**CAMPAIGN, "persona_id": "cmo"}, headers=AUTH)
    ).json()

    ok = (await client.post(f"/api/campaigns/{good['id']}/validate", headers=AUTH)).json()
    assert ok == {"ok": True, "issues": [], "provenance": ok["provenance"]}

    report = (await client.post(f"/api/campaigns/{bad['id']}/validate", headers=AUTH)).json()
    assert report["ok"] is False
    assert [i["code"] for i in report["issues"]] == ["unknown_persona"]
    assert report["issues"][0]["fix"]


async def test_validating_before_a_profile_exists_says_what_to_do_first(client):
    cid = (await client.post("/api/campaigns", json=CAMPAIGN, headers=AUTH)).json()["id"]
    r = await client.post(f"/api/campaigns/{cid}/validate", headers=AUTH)
    assert r.status_code == 409
    assert "profile" in r.json()["detail"].lower()


async def new_campaign(client) -> str:
    return (await client.post("/api/campaigns", json=CAMPAIGN, headers=AUTH)).json()["id"]


async def test_a_prospect_is_added_to_a_campaign_and_listed(client):
    cid = await new_campaign(client)
    prospect = {"company_name": "Acme", "person_name": "Priya Shah", "title": "VP Finance"}
    added = await client.post(f"/api/campaigns/{cid}/prospects", json=prospect, headers=AUTH)
    assert added.status_code == 201

    listed = (await client.get(f"/api/campaigns/{cid}/prospects", headers=AUTH)).json()
    assert [(p["id"], p["person_name"]) for p in listed] == [(added.json()["id"], "Priya Shah")]


CSV = (
    "Full Name,Company,Website,Job Title,Favourite colour\n"
    "Priya Shah,Acme,https://www.Acme.com/about,VP Finance,green\n"
    "Sam Lee,,https://globex.example,CFO,blue\n"
    "priya shah,ACME,acme.com,VP Finance,green\n"
    ",Initech,initech.example,,red\n"
)


async def upload(client, cid: str, csv: str, *, dry_run: bool):
    return await client.post(
        f"/api/campaigns/{cid}/prospects/csv",
        params={"dry_run": dry_run},
        files={"file": ("prospects.csv", csv.encode(), "text/csv")},
        headers=AUTH,
    )


async def test_csv_preview_maps_columns_normalises_and_reports_problems_without_saving(client):
    cid = await new_campaign(client)
    preview = (await upload(client, cid, CSV, dry_run=True)).json()

    assert [
        (r["person_name"], r["company_name"], r["company_domain"]) for r in preview["rows"]
    ] == [
        ("Priya Shah", "Acme", "acme.com"),
        (None, "Initech", "initech.example"),  # company-only: the system will suggest a contact
    ]
    assert [(e["row"], e["reason"]) for e in preview["errors"]] == [
        (3, "missing company name"),
        (4, "duplicate of row 2"),
    ]
    assert preview["unmapped_columns"] == ["Favourite colour"]
    assert (await client.get(f"/api/campaigns/{cid}/prospects", headers=AUTH)).json() == []


async def test_csv_import_saves_valid_rows_and_skips_prospects_already_in_the_campaign(client):
    cid = await new_campaign(client)
    await client.post(
        f"/api/campaigns/{cid}/prospects",
        json={"company_name": "Initech", "company_domain": "initech.example"},
        headers=AUTH,
    )
    result = (await upload(client, cid, CSV, dry_run=False)).json()

    assert result["saved"] == 1
    assert (5, "already in this campaign") in [(e["row"], e["reason"]) for e in result["errors"]]
    names = [
        p["company_name"]
        for p in (await client.get(f"/api/campaigns/{cid}/prospects", headers=AUTH)).json()
    ]
    assert names == ["Initech", "Acme"]


async def test_a_csv_without_a_company_column_is_rejected_with_the_columns_we_accept(client):
    cid = await new_campaign(client)
    r = await upload(client, cid, "Name,Email\nPriya,p@acme.com\n", dry_run=True)
    assert r.status_code == 422
    assert "company" in r.json()["detail"].lower()


async def test_a_csv_over_the_row_limit_is_rejected_before_anything_is_saved(client):
    cid = await new_campaign(client)
    big = "Company\n" + "".join(f"Company {i}\n" for i in range(501))
    r = await upload(client, cid, big, dry_run=False)
    assert r.status_code == 422
    assert "500" in r.json()["detail"]
    assert (await client.get(f"/api/campaigns/{cid}/prospects", headers=AUTH)).json() == []


# ── runs ─────────────────────────────────────────────────────────────────────

PRIYA_ROW = {"company_name": "Acme", "person_name": "Priya Shah", "company_domain": "acme.example"}


async def ready_prospect(client) -> tuple[str, int]:
    await client.put("/api/profile", json=PROFILE, headers=AUTH)
    cid = await new_campaign(client)
    r = await client.post(f"/api/campaigns/{cid}/prospects", json=PRIYA_ROW, headers=AUTH)
    return cid, r.json()["id"]


async def start_run(client, **body) -> str:
    r = await client.post("/api/runs", json=body, headers=AUTH)
    assert r.status_code == 202, r.text
    return r.json()["run_id"]


async def events_of(client, run_id: str) -> list[dict]:
    async with client.stream("GET", f"/api/runs/{run_id}/events", headers=AUTH) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        return [
            json.loads(line.removeprefix("data:").strip())
            async for line in r.aiter_lines()
            if line.startswith("data:")
        ]


async def test_a_run_streams_its_stages_and_its_detail_shows_evidence_hooks_and_draft(client):
    cid, pid = await ready_prospect(client)
    run_id = await start_run(client, prospect_id=pid, tier="standard")

    events = await events_of(client, run_id)
    assert events[0] == {"stage": "identity", "status": "started", "summary": ""}
    assert events[-1] == {"stage": "run", "status": "finished", "summary": "DRAFT_READY"}

    run = (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()
    assert (run["state"], run["campaign_id"], run["tier"]) == ("DRAFT_READY", cid, "standard")
    assert run["prospect"]["person_name"] == "Priya Shah"
    assert run["brief"]["objective"] == "Book demos with finance leaders"
    assert {e["claim"] for e in run["outcome"]["research"]["ledger"]} >= {PODCAST_QUOTE.claim}
    assert run["outcome"]["ranking"]["ranked"][0]["evidence"]["claim"] == PODCAST_QUOTE.claim
    assert run["outcome"]["draft"]["subject"] == "Closing the books faster"
    assert run["events"] == events


async def test_run_history_is_filtered_by_campaign_and_state(client, world):
    cid, pid = await ready_prospect(client)
    ready = await start_run(client, prospect_id=pid, tier="quick")
    await events_of(client, ready)
    world["deps"] = lambda: deps(scores={PODCAST_QUOTE.claim: 1.0})
    weak = await start_run(client, prospect_id=pid, tier="quick")
    await events_of(client, weak)

    everything = (await client.get("/api/runs", params={"campaign_id": cid}, headers=AUTH)).json()
    assert {r["id"]: r["state"] for r in everything} == {ready: "DRAFT_READY", weak: "LOW_SIGNAL"}
    low = (await client.get("/api/runs", params={"state": "LOW_SIGNAL"}, headers=AUTH)).json()
    assert [r["id"] for r in low] == [weak]
    assert low[0]["prospect"]["company_name"] == "Acme"


async def test_a_paused_run_is_resumed_with_the_contact_the_rep_picked(client, world):
    _, pid = await ready_prospect(client)
    world["deps"] = lambda: deps(
        identity=Identity(IdentityStatus.AMBIGUOUS, candidates=(PRIYA,)),
        scores={PODCAST_QUOTE.claim: 4.5},
    )
    paused = await start_run(client, prospect_id=pid, tier="standard")
    await events_of(client, paused)
    detail = (await client.get(f"/api/runs/{paused}", headers=AUTH)).json()
    assert detail["state"] == "NEEDS_CLARIFICATION"
    picked = detail["outcome"]["identity"]["candidates"][0]

    resumed = await start_run(client, prospect_id=pid, tier="standard", pinned_identity=picked)
    assert (await events_of(client, resumed))[-1]["summary"] == "DRAFT_READY"


async def test_starting_a_run_needs_a_known_prospect_and_a_seller_profile(client):
    r = await client.post("/api/runs", json={"prospect_id": 999, "tier": "quick"}, headers=AUTH)
    assert r.status_code == 404

    cid = await new_campaign(client)
    pid = (
        await client.post(f"/api/campaigns/{cid}/prospects", json=PRIYA_ROW, headers=AUTH)
    ).json()["id"]
    r = await client.post("/api/runs", json={"prospect_id": pid, "tier": "quick"}, headers=AUTH)
    assert r.status_code == 409


# ── review ───────────────────────────────────────────────────────────────────


async def finished_run(client) -> str:
    _, pid = await ready_prospect(client)
    run_id = await start_run(client, prospect_id=pid, tier="standard")
    await events_of(client, run_id)
    return run_id


async def review(client, run_id: str, **body):
    return await client.post(f"/api/runs/{run_id}/review", json=body, headers=AUTH)


async def test_the_rep_approves_a_ready_draft(client):
    run_id = await finished_run(client)
    assert (await review(client, run_id, action="approve")).status_code == 200

    run = (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()
    assert run["review"]["state"] == "APPROVED"
    assert run["review"]["draft"]["subject"] == "Closing the books faster"


SALESY = Draft(subject="Hi", body="I hope this finds you well. Ledgerly is a game-changer.")


async def test_a_held_draft_must_be_edited_clean_before_it_can_be_approved(client, world):
    world["deps"] = lambda: deps(scores={PODCAST_QUOTE.claim: 4.5}, drafts=(SALESY,))
    run_id = await finished_run(client)

    refused = await review(client, run_id, action="approve")
    assert refused.status_code == 409

    still_bad = await review(client, run_id, action="edit", subject="Hi", body=SALESY.body)
    assert still_bad.status_code == 422
    assert "banned_phrase" in still_bad.text

    clean = "Priya, closing the books faster is your stated priority. Worth a short look?"
    edited = await review(client, run_id, action="edit", subject="Month-end", body=clean)
    assert edited.status_code == 200
    run = (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()
    assert run["review"]["state"] == "APPROVED_WITH_EDITS"
    assert run["review"]["draft"]["body"] == clean


async def test_rejecting_a_draft_needs_a_reason(client):
    run_id = await finished_run(client)
    assert (await review(client, run_id, action="reject")).status_code == 422

    assert (await review(client, run_id, action="reject", reason="wrong person")).status_code == 200
    run = (await client.get(f"/api/runs/{run_id}", headers=AUTH)).json()
    assert (run["review"]["state"], run["review"]["reason"]) == ("REJECTED", "wrong person")


async def test_runs_without_a_draft_cannot_be_reviewed(client, world):
    world["deps"] = lambda: deps(scores={PODCAST_QUOTE.claim: 1.0})
    run_id = await finished_run(client)
    assert (await review(client, run_id, action="approve")).status_code == 409


# ── dashboard and export ──────────────────────────────────────────────────────


async def test_dashboard_counts_runs_by_state_and_review_outcome(client, world):
    approved = await finished_run(client)
    await review(client, approved, action="approve")
    world["deps"] = lambda: deps(scores={PODCAST_QUOTE.claim: 1.0})
    await finished_run(client)

    board = (await client.get("/api/dashboard", headers=AUTH)).json()
    assert board["runs_total"] == 2
    assert board["by_state"] == {"DRAFT_READY": 1, "LOW_SIGNAL": 1}
    assert board["by_review"] == {"APPROVED": 1}
    assert board["approval_rate"] == 1.0  # of drafts reviewed


async def test_export_is_a_csv_of_approved_drafts_with_the_seller_footer(client):
    approved = await finished_run(client)
    await review(client, approved, action="approve")
    rejected = await finished_run(client)
    await review(client, rejected, action="reject", reason="tone")

    await client.put(
        "/api/profile",
        json={**PROFILE, "footer": "Ledgerly, 1 Main St. Reply STOP to opt out."},
        headers=AUTH,
    )
    r = await client.get("/api/export", headers=AUTH)
    assert r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert [row["run_id"] for row in rows] == [approved]
    assert rows[0]["person_name"] == "Priya Shah"
    assert rows[0]["subject"] == "Closing the books faster"
    assert rows[0]["body"].endswith("Reply STOP to opt out.")
    assert rows[0]["hook"] == PODCAST_QUOTE.claim
    assert rows[0]["hook_url"] == "https://pod.example/ep41"
