"""Run one prospect through the real pipeline and print what happened.

    uv run python -m scripts.try_run --company Ramp --person "Eric Glyman" --title CEO

Uses the sample seller profile (samples/seller_profile.json) and the keys in .env. Search spend is
recorded in the configured database, so free-tier budgets stay accurate.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter
from datetime import date
from pathlib import Path

from app.agents.factory import Runtime
from app.config import get_settings
from app.context.merge import merge_brief
from app.db.store import Store, StoreLedger
from app.domain.models import Campaign, ProspectInput, SellerProfile, Tier
from app.pipeline.run import StageEvent, run_prospect
from app.services.runs import TIER_BUDGETS, TIER_HOOK_CANDIDATES, draft_rules_for

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


async def main(args: argparse.Namespace) -> None:
    settings = get_settings()
    store = Store(settings.database_url)
    await store.create_all()
    runtime = Runtime.create(settings, StoreLedger(store))
    usage: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    runtime.router.on_usage(
        lambda u: (
            usage.update({u.provider: u.prompt_tokens + u.completion_tokens}),
            calls.update({u.provider: 1}),
        )
    )
    profile = SellerProfile.model_validate_json((SAMPLES / "seller_profile.json").read_text())
    campaign = Campaign(
        name="Close faster",
        objective="Book a 20-minute intro call about speeding up month-end close",
        persona_id="finance_leader",
        angle="growth makes the monthly close slower",
    )
    brief = merge_brief(profile, campaign)
    prospect = ProspectInput(
        company_name=args.company,
        person_name=args.person,
        title=args.title,
        company_domain=args.domain,
    )
    started = time.perf_counter()

    def show(e: StageEvent) -> None:
        if e.status != "started":
            print(f"{time.perf_counter() - started:6.1f}s  {e.stage:10} {e.status:8} {e.summary}")

    tier = Tier(args.tier)
    outcome = await run_prospect(
        prospect,
        brief,
        runtime.deps(tier),
        rules=draft_rules_for(profile),
        today=date.today(),
        budget=TIER_BUDGETS[tier],
        on_event=show,
        max_hook_candidates=TIER_HOOK_CANDIDATES[tier],
    )
    print(f"\nSTATE: {outcome.state.value}   notes: {outcome.notes}")
    if outcome.research:
        r = outcome.research
        print(
            f"research: {len(r.ledger)} verified, {len(r.rejected)} rejected quotes, "
            f"{len(r.failures)} failures, {r.searches_used} searches, {r.pages_used} pages"
        )
        for f in r.failures[:8]:
            print(f"   failure: {f.reason[:90]}  {f.url[:60]}")
    if outcome.ranking:
        for h in outcome.ranking.top():
            e = h.evidence
            print(f"\nHOOK {h.total:.2f} [{e.category.value}/{e.about.value}] {e.claim}")
            print(f'   "{e.verbatim_quote[:160]}"\n   {e.url}  ({e.published_at})')
        for v in outcome.ranking.vetoed[:6]:
            print(f"   vetoed ({v.reason}): {v.evidence.claim[:90]}")
    if outcome.identity and outcome.identity.candidates:
        for c in outcome.identity.candidates:
            print(f"candidate: {c.person_name}, {c.title} at {c.company_name}  ({c.evidence_url})")
    if outcome.draft:
        d = outcome.draft
        print(f"\nSUBJECT: {d.subject}\n{d.body}\ncites: {d.citations}")
    for p in outcome.problems:
        print(f"PROBLEM: {p}")
    print(
        f"\ntime {time.perf_counter() - started:.0f}s; AI calls {dict(calls)}; tokens {dict(usage)}"
    )
    await runtime.close()
    await store.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--person")
    parser.add_argument("--title")
    parser.add_argument("--domain")
    parser.add_argument("--tier", default="standard", choices=[t.value for t in Tier])
    asyncio.run(main(parser.parse_args()))
