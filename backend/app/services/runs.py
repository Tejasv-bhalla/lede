"""Start runs in the background, fan their stage events out to live viewers, persist outcomes.

A run's final event is announced only after its outcome is saved, so anyone who sees "finished"
can immediately read the full result.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any
from uuid import uuid4

from pydantic import TypeAdapter

from app.context.merge import MergedBrief, merge_brief
from app.db.store import Store
from app.domain.models import Campaign, ProspectInput, RunState, SellerProfile, Tier
from app.pipeline.ports import Contact
from app.pipeline.run import PipelineDeps, RunOutcome, StageEvent, run_prospect
from app.policy.draft_rules import DEFAULT_BANNED_PHRASES, DraftRules
from app.research.loop import Budget

log = logging.getLogger(__name__)

TIER_BUDGETS: dict[Tier, Budget] = {
    Tier.QUICK: Budget(max_follow_up_rounds=0, max_searches=8, max_pages=10),
    Tier.STANDARD: Budget(max_follow_up_rounds=2, max_searches=20, max_pages=25),
    Tier.DEEP: Budget(max_follow_up_rounds=4, max_searches=40, max_pages=50),
}

_OUTCOME = TypeAdapter(RunOutcome)
_BRIEF = TypeAdapter(MergedBrief)


class NotFound(LookupError):
    pass


class NotReady(RuntimeError):
    """A precondition the rep must fix first (e.g. no seller profile)."""


def draft_rules_for(profile: SellerProfile) -> DraftRules:
    return DraftRules(
        max_words=profile.tone.max_words,
        banned_phrases=(*DEFAULT_BANNED_PHRASES, *profile.tone.banned_phrases),
        never_claims=tuple(profile.never_claims),
        footer=None,  # appended at export; the writer never has to reproduce it
    )


@dataclass(slots=True)
class _Live:
    """Events of a run in progress, for any number of followers."""

    events: list[dict[str, str]] = field(default_factory=list)
    done: bool = False
    _wake: asyncio.Event = field(default_factory=asyncio.Event)

    def push(self, event: dict[str, str]) -> None:
        self.events.append(event)
        self._notify()

    def close(self) -> None:
        self.done = True
        self._notify()

    def _notify(self) -> None:
        self._wake.set()
        self._wake = asyncio.Event()

    async def follow(self) -> AsyncIterator[dict[str, str]]:
        seen = 0
        while True:
            while seen < len(self.events):
                yield self.events[seen]
                seen += 1
            if self.done:
                return
            await self._wake.wait()


class RunService:
    def __init__(
        self,
        store: Store,
        deps_factory: Callable[[], PipelineDeps],
        today: Callable[[], date],
    ) -> None:
        self._store = store
        self._deps_factory = deps_factory
        self._today = today
        self._live: dict[str, _Live] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    async def start(self, prospect_id: int, tier: Tier, pinned: Contact | None) -> str:
        found = await self._store.get_prospect(prospect_id)
        if found is None:
            raise NotFound(f"No prospect {prospect_id}.")
        campaign_id, prospect_data = found
        profile_data = await self._store.get_profile()
        if profile_data is None:
            raise NotReady("Set up the seller profile before running prospects.")
        campaign_data = await self._store.get_campaign(campaign_id)
        assert campaign_data is not None, "prospects always belong to a campaign"

        profile = SellerProfile.model_validate(profile_data)
        prospect = ProspectInput.model_validate(prospect_data)
        brief = merge_brief(profile, Campaign.model_validate(campaign_data))
        run_id = uuid4().hex[:12]
        await self._store.create_run(
            run_id,
            campaign_id=campaign_id,
            prospect_id=prospect_id,
            tier=tier.value,
            inputs={
                "prospect": prospect_data,
                "brief": _BRIEF.dump_python(brief, mode="json"),
                "pinned_identity": asdict(pinned) if pinned else None,
            },
        )
        live = self._live[run_id] = _Live()
        task = asyncio.create_task(
            self._execute(run_id, live, prospect, brief, draft_rules_for(profile), tier, pinned)
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return run_id

    async def _execute(
        self,
        run_id: str,
        live: _Live,
        prospect: ProspectInput,
        brief: MergedBrief,
        rules: DraftRules,
        tier: Tier,
        pinned: Contact | None,
    ) -> None:
        final: dict[str, str] | None = None

        def on_event(event: StageEvent) -> None:
            nonlocal final
            payload = asdict(event)
            if event.stage == "run":
                final = payload  # announced after the outcome is saved
            else:
                live.push(payload)

        try:
            outcome = await run_prospect(
                prospect,
                brief,
                self._deps_factory(),
                rules=rules,
                today=self._today(),
                budget=TIER_BUDGETS[tier],
                pinned=pinned,
                on_event=on_event,
            )
        except Exception:  # a bug, not a model outage: record it instead of hanging viewers
            log.exception("run %s crashed", run_id)
            outcome = RunOutcome(RunState.FAILED, problems=["Internal error; see server logs."])
            final = {"stage": "run", "status": "finished", "summary": RunState.FAILED.value}
        assert final is not None
        try:
            await self._store.finish_run(
                run_id,
                state=outcome.state.value,
                outcome=_OUTCOME.dump_python(outcome, mode="json"),
                events=[*live.events, final],
            )
        finally:
            live.push(final)
            live.close()
            self._live.pop(run_id, None)

    async def follow(self, run_id: str) -> AsyncIterator[dict[str, str]]:
        live = self._live.get(run_id)
        if live is not None:
            async for event in live.follow():
                yield event
            return
        run = await self._store.get_run(run_id)
        if run is None:
            raise NotFound(f"No run '{run_id}'.")
        for event in run["events"]:
            yield event

    async def detail(self, run_id: str) -> dict[str, Any]:
        run = await self._store.get_run(run_id)
        if run is None:
            raise NotFound(f"No run '{run_id}'.")
        live = self._live.get(run_id)
        if live is not None:
            run["events"] = list(live.events)
        return run
