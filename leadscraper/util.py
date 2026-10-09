"""Small shared helpers: domain extraction, URL normalisation, text cleanup."""
from __future__ import annotations

import re

import tldextract

# Use the bundled public-suffix snapshot so we never hit the network at import
# time (and the tool works fully offline for this part).
_extract = tldextract.TLDExtract(suffix_list_urls=())

_WS_RE = re.compile(r"\s+")


def registrable_domain(url_or_domain: str) -> str:
    """Return the eTLD+1 (e.g. 'sub.foo.co.uk' -> 'foo.co.uk'). '' if none."""
    if not url_or_domain:
        return ""
    ext = _extract(url_or_domain.strip().lower())
    if ext.domain and ext.suffix:
        return f"{ext.domain}.{ext.suffix}"
    return ""


def same_registrable_domain(a: str, b: str) -> bool:
    ra, rb = registrable_domain(a), registrable_domain(b)
    return bool(ra) and ra == rb


def normalize_url(url: str) -> str:
    """Add a scheme if missing; trim whitespace."""
    if not url:
        return ""
    url = url.strip()
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url
    return url


def clean_text(text: str) -> str:
    return _WS_RE.sub(" ", (text or "").replace("\xa0", " ")).strip()


def collapse_spaces(text: str) -> str:
    return _WS_RE.sub(" ", text or "").strip()
