"""Data models shared across the pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class EmailCandidate:
    """A single email found for a business, with its classification."""
    address: str
    local: str
    domain: str
    kind: str = "unknown"          # personal_named | personal | generic_role | noreply | free_personal
    is_free: bool = False
    is_role: bool = False
    domain_match: bool = False     # domain == business website registrable domain
    matched_owner: bool = False    # local-part maps to a detected owner name
    status: str = "unknown"        # valid | invalid | catch_all | mx_ok | no_mx | bad_syntax | unknown
    verified: bool = False         # True only when SMTP confirmed deliverable

    @property
    def usable(self) -> bool:
        """Addresses we are willing to use for outreach (not role/noreply)."""
        return self.kind in {"personal_named", "personal", "free_personal"}


@dataclass
class Lead:
    """One business lead. One row in the final output."""
    # provenance
    query: str = ""
    source: str = ""
    scraped_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))

    # business identity
    business_name: str = ""
    category: str = ""

    # location
    address: str = ""
    city: str = ""
    state: str = ""
    zip: str = ""
    country: str = ""
    lat: float | None = None
    lng: float | None = None

    # contact
    phone: str = ""
    website: str = ""
    website_domain: str = ""
    website_ok: bool = False
    google_maps_url: str = ""

    # reputation / liveness
    rating: float | None = None
    reviews_count: int | None = None
    permanently_closed: bool = False

    # people
    owner_name: str = ""
    owner_title: str = ""

    # chosen email
    email: str = ""
    email_type: str = ""
    email_domain_match: bool = False
    email_free_domain: bool = False
    email_status: str = ""
    email_verified: bool = False
    other_emails: str = ""         # ; joined fallback / extra addresses

    # socials
    linkedin: str = ""
    instagram: str = ""
    facebook: str = ""
    twitter: str = ""

    # scoring
    score: int = 0
    tier: str = ""                 # T1 | T2 | T3 | DISCARD
    flags: list[str] = field(default_factory=list)

    # internal working state (not exported)
    candidates: list[EmailCandidate] = field(default_factory=list, repr=False)
    _enrich_text: str = field(default="", repr=False)

    # --- helpers ---------------------------------------------------------
    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    # columns exported to CSV / Excel, in display order
    EXPORT_FIELDS = (
        "tier", "score", "business_name", "owner_name", "owner_title",
        "email", "email_type", "email_domain_match", "email_free_domain",
        "email_status", "email_verified", "other_emails",
        "phone", "website", "website_ok", "category",
        "address", "city", "state", "zip", "country",
        "rating", "reviews_count", "permanently_closed",
        "linkedin", "instagram", "facebook", "twitter",
        "google_maps_url", "lat", "lng",
        "flags", "source", "query", "scraped_at",
    )

    def to_row(self) -> dict:
        d = asdict(self)
        d.pop("candidates", None)
        d.pop("_enrich_text", None)
        d["flags"] = "; ".join(self.flags)
        return {k: d.get(k, "") for k in self.EXPORT_FIELDS}
