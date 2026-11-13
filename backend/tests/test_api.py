from collections.abc import AsyncIterator

import httpx
import pytest
from pydantic import SecretStr

from app.api.app import create_app
from app.config import Settings
from app.db.store import Store

CODE = "open-sesame"
AUTH = {"X-Access-Code": CODE}

PROFILE = {
    "company": {"name": "Ledgerly", "domain": "ledgerly.example"},
    "offer": {"product": "Ledgerly", "problem_solved": "slow month-end close"},
    "personas": [{"id": "fin", "title_patterns": ["VP Finance"], "seniority": "vp"}],
    "approved_claims": [{"id": "c1", "text": "Matches invoices to POs automatically"}],
}


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    store = Store(f"sqlite:///{tmp_path / 'test.db'}")
    await store.create_all()
    app = create_app(Settings(demo_access_code=SecretStr(CODE)), store=store)
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
