"""Score a lead by how confident we are it is a genuine, active business with
a reachable owner / decision-maker -- not merely how much data was found.

Also assigns a priority tier:
  T1  verified owner/founder email on the company domain
  T2  decision-maker / personal email on the company domain
  T3  owner email on a free domain, only if confirmed as the owner's
  DISCARD  generic-only, invalid, closed, or unmatched
"""
from __future__ import annotations

import re

from ..config import ScoreWeights, Settings
from ..models import EmailCandidate, Lead
from ..query import QuerySpec
from ..util import registrable_domain

_ALPHA = re.compile(r"[a-z]+")


def _valid_phone(phone: str) -> bool:
    return len(re.sub(r"\D", "", phone or "")) >= 7


def _is_owner_founder(title: str) -> bool:
    t = (title or "").lower()
    return any(k in t for k in ("owner", "founder", "proprietor"))


def _location_match(lead: Lead, spec: QuerySpec):
    """True = matches target, False = clearly different, None = unknown."""
    if spec.zip and lead.zip:
        if spec.zip == lead.zip:
            return True
        # different zip -> fall through to city/state check
    if spec.city and lead.city:
        a, b = spec.city.lower(), lead.city.lower()
        if a in b or b in a:
            return True
    if spec.state and lead.state and spec.state.upper() != lead.state.upper():
        return False
    if spec.zip and lead.zip and spec.zip != lead.zip and not (spec.city and lead.city):
        return False
    return None


def _consistent(lead: Lead) -> bool:
    name_tokens = [t for t in _ALPHA.findall(lead.business_name.lower()) if len(t) >= 4]
    if not name_tokens:
        return False
    blob = (registrable_domain(lead.website) + " " +
            (lead.email.partition("@")[2] if lead.email else "")).replace(".", "")
    return any(tok in blob for tok in name_tokens)


def _chosen_candidate(lead: Lead) -> EmailCandidate | None:
    return next((c for c in lead.candidates if c.address == lead.email), None)


def score_lead(lead: Lead, spec: QuerySpec, settings: Settings) -> None:
    w: ScoreWeights = settings.weights
    pts = 0
    chosen = _chosen_candidate(lead)
    usable_exists = any(c.usable for c in lead.candidates)
    only_generic = (not usable_exists) and any(c.is_role for c in lead.candidates)

    # --- people ---
    if lead.owner_name and lead.owner_title:
        pts += w.owner_identified
    elif lead.owner_name:
        pts += w.name_only
    else:
        lead.add_flag("no_owner_identified")

    # --- email ---
    if lead.email and chosen:
        pts += w.email_personal
        if lead.email_domain_match:
            pts += w.email_domain_match
        if chosen.matched_owner:
            pts += w.email_matched_owner
        if lead.email_verified:
            pts += w.email_verified_smtp
        elif lead.email_status == "mx_ok":
            pts += w.email_mx_ok
        elif lead.email_status == "catch_all":
            pts += w.email_catch_all
            lead.add_flag("catch_all")
        elif lead.email_status in ("invalid", "no_mx", "bad_syntax"):
            pts += w.email_invalid
            lead.add_flag(f"email_{lead.email_status}")
        if lead.email_free_domain and not chosen.matched_owner:
            pts += w.email_free_domain
            lead.add_flag("free_domain_unconfirmed")
    elif only_generic:
        pts += w.only_generic_email
        lead.add_flag("only_generic_email")
    else:
        pts += w.no_email
        lead.add_flag("no_email")

    # --- phone / website / maps ---
    if _valid_phone(lead.phone):
        pts += w.phone_valid
    if lead.website_ok:
        pts += w.website_ok
    elif lead.website:
        lead.add_flag("website_unreachable")
    else:
        lead.add_flag("no_website")
    if lead.google_maps_url and (lead.reviews_count or 0) > 0:
        pts += w.maps_presence

    # --- socials ---
    if lead.linkedin or lead.instagram:
        pts += w.social_owner

    # --- completeness ---
    key_fields = [lead.business_name, lead.owner_name, lead.website,
                  lead.phone, lead.address, lead.email]
    frac = sum(1 for f in key_fields if f) / len(key_fields)
    pts += round(w.data_complete * frac)

    # --- location ---
    loc = _location_match(lead, spec)
    if loc is True:
        pts += w.location_match
    elif loc is False:
        pts += w.location_mismatch
        lead.add_flag("location_mismatch")

    # --- consistency ---
    if _consistent(lead):
        pts += w.consistency

    # --- hard penalties ---
    if lead.permanently_closed:
        pts += w.permanently_closed
        lead.add_flag("permanently_closed")

    lead.score = max(0, min(100, pts))
    lead.tier = _tier(lead, chosen)


def _tier(lead: Lead, chosen: EmailCandidate | None) -> str:
    if lead.permanently_closed:
        return "DISCARD"
    if chosen is None:
        return "DISCARD"
    if lead.email_status in ("invalid", "no_mx", "bad_syntax"):
        return "DISCARD"

    confirmed_owner = chosen.matched_owner or _is_owner_founder(lead.owner_title)

    if lead.email_domain_match and not lead.email_free_domain:
        tier = "T1" if confirmed_owner else "T2"
    elif lead.email_free_domain:
        tier = "T3" if confirmed_owner else "DISCARD"
    elif chosen.kind == "personal_named":
        tier = "T2"
    else:
        tier = "DISCARD"

    # Catch-all addresses are softer evidence -> demote the top tier by one.
    if lead.email_status == "catch_all" and tier == "T1":
        tier = "T2"
    return tier
