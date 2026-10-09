"""Central configuration: tunable settings, blocklists, and scoring weights.

Everything that encodes the manager's rules lives here so the behaviour is
transparent and easy to tweak without touching the pipeline logic.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Email classification data
# ---------------------------------------------------------------------------

# Role / shared / role-based inbox local-parts we explicitly DO NOT want.
# These are inbound addresses, not a specific person -> rejected for outreach.
GENERIC_LOCALPARTS: set[str] = {
    "info", "contact", "hello", "hi", "hey", "enquiry", "enquiries",
    "inquiry", "inquiries", "sales", "support", "help", "helpdesk", "care",
    "customercare", "customerservice", "customer", "service", "services",
    "admin", "administrator", "office", "team", "staff", "reception",
    "frontdesk", "booking", "bookings", "reservations", "reservation",
    "order", "orders", "billing", "accounts", "account", "accounting",
    "finance", "invoices", "invoice", "payments", "hr", "jobs", "careers",
    "recruitment", "press", "media", "pr", "marketing", "newsletter",
    "subscribe", "feedback", "general", "mail", "email", "contactus",
    "webmaster", "postmaster", "abuse", "security", "privacy", "legal",
    "compliance", "notifications", "notification", "alerts", "updates",
    "mailer", "mailbox", "web", "website", "shop", "store", "wholesale",
    "partners", "partnerships", "affiliate", "affiliates", "events",
}

# No-reply family -> always rejected.
NOREPLY_LOCALPARTS: set[str] = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "do_not_reply", "donotrespond", "notreply", "bounce", "bounces",
    "mailer-daemon", "mailerdaemon",
}

# Free / consumer mailbox providers. Emails here are flagged and ranked lower
# unless we can confirm they belong to the owner.
FREE_EMAIL_DOMAINS: set[str] = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "yahoo.co.in",
    "ymail.com", "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com",
    "msn.com", "aol.com", "icloud.com", "me.com", "mac.com", "gmx.com",
    "gmx.net", "proton.me", "protonmail.com", "pm.me", "zoho.com",
    "yandex.com", "yandex.ru", "mail.com", "rediffmail.com", "rocketmail.com",
    "fastmail.com", "hey.com", "tutanota.com", "126.com", "163.com", "qq.com",
}

# Obvious placeholder / vendor / tracking addresses to drop entirely.
JUNK_EMAIL_DOMAINS: set[str] = {
    "example.com", "example.org", "example.net", "domain.com", "email.com",
    "yourdomain.com", "yourcompany.com", "company.com", "test.com",
    "sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
    "godaddy.com", "squarespace.com", "shopify.com", "cloudflare.com",
    "w3.org", "schema.org", "googleapis.com", "gstatic.com", "googleusercontent.com",
    "2x.png", "3x.png", "jpg", "png", "gif", "webp", "svg",
}
JUNK_EMAIL_LOCALPARTS: set[str] = {
    "your", "youremail", "yourname", "name", "firstname", "lastname",
    "example", "user", "username", "test", "email", "someone", "sentry",
    "you", "sample", "demo", "johndoe", "janedoe", "john.doe", "jane.doe",
    "yourmail", "mail", "mailbox", "domain", "company", "business",
}

# ---------------------------------------------------------------------------
# People / title detection
# ---------------------------------------------------------------------------

# Decision-maker titles, grouped by priority. Higher = more valuable lead.
OWNER_TITLES: set[str] = {
    "owner", "co-owner", "coowner", "co owner", "founder", "co-founder",
    "cofounder", "co founder", "proprietor", "sole proprietor",
}
EXEC_TITLES: set[str] = {
    "ceo", "chief executive officer", "president", "managing director",
    "md", "general manager", "gm", "managing partner", "principal",
    "chairman", "chairwoman", "chairperson", "coo", "cto", "director",
    "partner", "head", "manager",
}

# Words that look like a Name but are not -> reject from person extraction.
NAME_STOPWORDS: set[str] = {
    "our", "team", "contact", "about", "us", "home", "menu", "privacy",
    "policy", "terms", "service", "cookie", "copyright", "all", "rights",
    "reserved", "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december",
    "the", "and", "for", "with", "your", "best", "new", "open", "closed",
    "read", "more", "learn", "book", "now", "order", "online", "google",
    "facebook", "instagram", "twitter", "linkedin", "youtube", "email",
    "phone", "address", "hours", "location", "map", "directions", "reviews",
    "of", "at", "in", "on", "by", "to", "from", "welcome", "meet", "team",
}

# ---------------------------------------------------------------------------
# Website crawling
# ---------------------------------------------------------------------------

# Internal pages most likely to carry owner / contact details.
CONTACT_PAGE_HINTS: tuple[str, ...] = (
    "contact", "about", "about-us", "aboutus", "team", "our-team", "ourteam",
    "meet-the-team", "people", "staff", "leadership", "management",
    "founder", "owner", "who-we-are", "company", "impressum", "meet",
    "our-story", "ourstory", "bio", "profile",
)

# A desktop-ish User-Agent so sites return their full markup.
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ---------------------------------------------------------------------------
# Scoring weights  (positive = reward, negative = penalty)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScoreWeights:
    owner_identified: int = 20        # name + decision-maker title found
    name_only: int = 8                # a person name but no clear title
    email_personal: int = 15          # a non-generic, person-style email exists
    email_domain_match: int = 15      # email domain == website domain
    email_matched_owner: int = 10     # email local-part maps to the owner name
    email_verified_smtp: int = 12     # SMTP said deliverable
    email_mx_ok: int = 5              # domain at least has MX records
    phone_valid: int = 6
    website_ok: int = 8               # website reachable & same business
    maps_presence: int = 6            # real Maps listing w/ reviews
    social_owner: int = 6             # owner LinkedIn/Instagram found
    data_complete: int = 6            # all key fields present (scaled)
    location_match: int = 4           # lead location matches the query
    consistency: int = 4              # name/website/email agree

    # Penalties
    permanently_closed: int = -60
    email_invalid: int = -15
    email_catch_all: int = -8
    email_free_domain: int = -8       # free mailbox, owner not confirmed
    only_generic_email: int = -25     # only role/shared inboxes available
    location_mismatch: int = -10
    no_email: int = -20


@dataclass
class Settings:
    """Runtime settings, built from CLI args in cli.py."""
    source: str = "google"            # "google" | "osm"
    limit: int = 40
    headless: bool = True
    concurrency: int = 8
    out_dir: str = "output"

    # website crawl
    max_pages_per_site: int = 6
    http_timeout: float = 15.0
    respect_robots: bool = True

    # email verification
    verify_smtp: bool = False         # opt-in: port 25 is often ISP-blocked
    smtp_timeout: float = 8.0
    smtp_from: str = "verify@example.com"

    # output
    include_discarded: bool = False

    weights: ScoreWeights = field(default_factory=ScoreWeights)
    user_agent: str = DEFAULT_USER_AGENT
