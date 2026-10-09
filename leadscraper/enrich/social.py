"""Extract social-profile links from page HTML."""
from __future__ import annotations

import re

_PATTERNS = {
    "linkedin": re.compile(
        r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|company|pub)/[A-Za-z0-9\-_%./]+",
        re.I,
    ),
    "instagram": re.compile(
        r"https?://(?:www\.)?instagram\.com/[A-Za-z0-9_.]+", re.I
    ),
    "facebook": re.compile(
        r"https?://(?:www\.)?facebook\.com/[A-Za-z0-9_.\-/]+", re.I
    ),
    "twitter": re.compile(
        r"https?://(?:www\.)?(?:twitter|x)\.com/[A-Za-z0-9_]+", re.I
    ),
}

# Facebook/Instagram system pages that are not a business profile.
_IG_FB_JUNK = re.compile(
    r"/(sharer|share|plugins|tr\?|dialog|login|home|help|policies|privacy)",
    re.I,
)


def extract_socials(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, pat in _PATTERNS.items():
        for m in pat.finditer(html or ""):
            url = m.group(0).rstrip("/\"'")
            if name in {"facebook", "instagram"} and _IG_FB_JUNK.search(url):
                continue
            # Prefer personal LinkedIn (/in/) over company pages.
            if name == "linkedin" and "linkedin" in out and "/in/" not in url:
                continue
            out[name] = url
            if name != "linkedin":
                break
    return out
