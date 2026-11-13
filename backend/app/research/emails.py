"""Spot a person's own email address in page text.

Only addresses that look like theirs are kept (their name in the address, at the company's
domain when we know it), so nobody else's address is stored.
"""

from __future__ import annotations

import re
import unicodedata

_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
_NOT_A_TLD = {"png", "jpg", "jpeg", "gif", "webp", "svg", "css", "js"}  # e.g. logo@2x.png


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in folded if c.isalnum())


def _on_domain(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def person_emails(text: str, person_name: str, company_domain: str | None) -> list[str]:
    """Addresses in `text` that belong to `person_name`, lower-cased, in order of appearance."""
    names = [_plain(part) for part in person_name.split()]
    first, last = names[0], names[-1]
    domain = (company_domain or "").casefold().removeprefix("www.")
    found: list[str] = []
    for match in _EMAIL.finditer(text):
        address = match.group(0).casefold().rstrip(".")
        local, host = address.split("@")
        if host.rsplit(".", 1)[-1] in _NOT_A_TLD:
            continue
        if domain and not _on_domain(host, domain):
            continue
        local = _plain(local)
        # Their last name, or (with the company's domain confirmed) their first name.
        by_last = len(last) >= 2 and last in local
        by_first = bool(domain) and len(first) >= 3 and first in local
        if (by_last or by_first) and address not in found:
            found.append(address)
    return found
