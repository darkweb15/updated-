"""Remove duplicate businesses and duplicate emails."""
from __future__ import annotations

import re

from .models import Lead
from .util import registrable_domain

_ALNUM = re.compile(r"[a-z0-9]+")


def _name_key(lead: Lead) -> str:
    return "".join(_ALNUM.findall(lead.business_name.lower()))


def _completeness(lead: Lead) -> int:
    return sum(bool(x) for x in (lead.business_name, lead.owner_name, lead.email,
                                 lead.phone, lead.website, lead.address))


def _better(a: Lead, b: Lead) -> Lead:
    """Return the record to keep (higher score, then more complete)."""
    if a.score != b.score:
        return a if a.score > b.score else b
    return a if _completeness(a) >= _completeness(b) else b


def dedupe(leads: list[Lead]) -> list[Lead]:
    # 1) collapse the same business (by website domain, else name+zip)
    best: dict[str, Lead] = {}
    for lead in leads:
        dom = registrable_domain(lead.website)
        key = f"dom:{dom}" if dom else f"nm:{_name_key(lead)}|{lead.zip}"
        if key in best:
            best[key] = _better(best[key], lead)
        else:
            best[key] = lead
    kept = list(best.values())

    # 2) global duplicate-email removal: keep the highest-scored holder
    kept.sort(key=lambda l: l.score, reverse=True)
    seen_emails: set[str] = set()
    for lead in kept:
        if not lead.email:
            continue
        if lead.email in seen_emails:
            lead.add_flag("duplicate_email")
            lead.tier = "DISCARD"
        else:
            seen_emails.add(lead.email)
    return kept
