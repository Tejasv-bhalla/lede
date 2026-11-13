"""Hunter's email finder (https://hunter.io/api-documentation/v2#email-finder).

Asked only when no page that research read shows the contact's address. Hunter charges a credit
only when it finds one. An address its owner has asked Hunter not to share (HTTP 451) is never
used.
"""

from __future__ import annotations

import httpx

from app.pipeline.ports import Contact, EmailLookupFailed, FoundEmail

URL = "https://api.hunter.io/v2/email-finder"
TIMEOUT_S = 15.0  # Hunter answers within its own 10-second default search time


class HunterEmailFinder:
    def __init__(self, http: httpx.AsyncClient, api_key: str) -> None:
        self._http, self._key = http, api_key

    async def find(self, contact: Contact) -> FoundEmail | None:
        names = (contact.person_name or "").split()
        if len(names) < 2:
            return None  # first and last name are needed for a reliable answer
        params = {"first_name": names[0], "last_name": names[-1]}
        if contact.company_domain:
            params["domain"] = contact.company_domain
        else:
            params["company"] = contact.company_name
        try:
            r = await self._http.get(
                URL, params=params, headers={"X-API-KEY": self._key}, timeout=TIMEOUT_S
            )
        except httpx.HTTPError as exc:
            raise EmailLookupFailed(f"Hunter unreachable: {type(exc).__name__}") from exc
        if r.status_code == 451:
            return None
        if r.status_code == 429:
            raise EmailLookupFailed("Hunter's monthly limit is used up")
        if r.status_code == 401:
            raise EmailLookupFailed("Hunter rejected the API key")
        if r.status_code != 200:
            raise EmailLookupFailed(f"Hunter answered {r.status_code}")
        data = r.json().get("data") or {}
        if not data.get("email"):
            return None
        sources = data.get("sources") or []
        return FoundEmail(
            data["email"].casefold(),
            "finder",
            url=sources[0].get("uri") if sources else None,
            confidence=data.get("score"),
            status=(data.get("verification") or {}).get("status") or "",
        )
