"""Email extraction + classification against the manager's rules."""
from __future__ import annotations

import re

from ..config import (
    FREE_EMAIL_DOMAINS,
    GENERIC_LOCALPARTS,
    JUNK_EMAIL_DOMAINS,
    JUNK_EMAIL_LOCALPARTS,
    NOREPLY_LOCALPARTS,
)
from ..models import EmailCandidate
from ..util import registrable_domain, same_registrable_domain

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,24}")
MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.I)
_SPLIT_RE = re.compile(r"[._\-+]")
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")


def deobfuscate(text: str) -> str:
    """Turn 'name [at] domain [dot] com' style into real '@' / '.'."""
    if not text:
        return ""
    t = re.sub(r"\s*[\[\(\{]\s*at\s*[\]\)\}]\s*", "@", text, flags=re.I)
    t = re.sub(r"\s*[\[\(\{]\s*dot\s*[\]\)\}]\s*", ".", t, flags=re.I)
    return t


def extract_emails(html: str, text: str) -> set[str]:
    # Take linked addresses from mailto: and bare addresses from VISIBLE text
    # only. We deliberately do NOT regex raw HTML, which pulls false positives
    # out of inline CSS / <script> / font licences (e.g. a web-font author's
    # gmail address embedded in a stylesheet comment).
    found: set[str] = set()
    for m in MAILTO_RE.finditer(html or ""):
        found.add(m.group(1).split("?")[0])
    for m in EMAIL_RE.finditer(deobfuscate(text or "")):
        found.add(m.group(0))
    # normalise + drop junk
    clean: set[str] = set()
    for raw in found:
        addr = raw.strip().strip(".,;:").lower()
        if "@" not in addr:
            continue
        local, _, domain = addr.partition("@")
        if not local or not domain or "." not in domain:
            continue
        if domain.endswith(_IMG_EXT):
            continue
        if domain in JUNK_EMAIL_DOMAINS or registrable_domain(domain) in JUNK_EMAIL_DOMAINS:
            continue
        if local in JUNK_EMAIL_LOCALPARTS:
            continue
        if len(local) > 64 or len(addr) > 254:
            continue
        clean.add(addr)
    return clean


def _is_role(local: str) -> bool:
    if local in GENERIC_LOCALPARTS:
        return True
    tokens = _SPLIT_RE.split(local)
    return bool(tokens) and tokens[0] in GENERIC_LOCALPARTS


def _is_noreply(local: str) -> bool:
    if local in NOREPLY_LOCALPARTS:
        return True
    return local.startswith(("noreply", "no-reply", "no_reply", "donotreply", "do-not-reply"))


def _matches_owner(local: str, owner_names: list[str]) -> bool:
    flat = re.sub(r"[^a-z0-9]", "", local.lower())
    for name in owner_names:
        for tok in re.split(r"\s+", name.lower()):
            tok = re.sub(r"[^a-z]", "", tok)
            if len(tok) >= 3 and tok in flat:
                return True
    return False


def _looks_named(local: str) -> bool:
    # firstname.lastname / first_last style
    return bool(re.match(r"^[a-z]{2,}[._][a-z]{2,}$", local))


def classify(address: str, website_domain: str, owner_names: list[str]) -> EmailCandidate:
    local, _, domain = address.partition("@")
    reg = registrable_domain(domain)
    cand = EmailCandidate(address=address, local=local, domain=domain)
    cand.is_free = reg in FREE_EMAIL_DOMAINS or domain in FREE_EMAIL_DOMAINS
    cand.domain_match = bool(website_domain) and same_registrable_domain(domain, website_domain)
    cand.matched_owner = _matches_owner(local, owner_names)

    if _is_noreply(local):
        cand.kind = "noreply"
        cand.is_role = True
    elif _is_role(local):
        cand.kind = "generic_role"
        cand.is_role = True
    elif cand.is_free:
        cand.kind = "free_personal"
    elif cand.matched_owner or _looks_named(local):
        cand.kind = "personal_named"
    else:
        cand.kind = "personal"
    return cand


def select_best(cands: list[EmailCandidate]) -> EmailCandidate | None:
    """Pick the single best outreach email per the priority rules."""
    usable = [c for c in cands if c.usable]
    if not usable:
        return None

    def rank(c: EmailCandidate) -> tuple:
        return (
            c.kind == "personal_named",   # named beats bare personal
            c.domain_match,               # on company domain
            c.matched_owner,              # maps to the owner
            not c.is_free,                # company domain over free mailbox
            c.verified,                   # SMTP-confirmed
            c.status in {"valid", "mx_ok"},
        )

    return max(usable, key=rank)
