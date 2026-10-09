"""Parse the free-form search key into structured parts.

Example:
    "restaurants 10001 new york ny usa"
    -> what="restaurants", where="10001 new york ny usa",
       zip="10001", country="usa", state="ny", city="new york"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .util import collapse_spaces

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_US_STATE_RE = re.compile(
    r"\b(a[klzr]|c[aot]|de|fl|ga|hi|i[adln]|k[sy]|la|m[adeinost]|"
    r"n[cdehjmvy]|o[hkr]|pa|ri|s[cd]|t[nx]|ut|v[at]|w[aivy])\b",
    re.I,
)
_COUNTRIES = {
    "usa": "USA", "us": "USA", "united states": "USA", "uk": "UK",
    "united kingdom": "UK", "canada": "Canada", "ca": "Canada",
    "australia": "Australia", "india": "India", "in": "India",
}


@dataclass
class QuerySpec:
    raw: str
    what: str = ""
    where: str = ""
    zip: str = ""
    city: str = ""
    state: str = ""
    country: str = ""


def parse_query(raw: str) -> QuerySpec:
    raw = collapse_spaces(raw)
    spec = QuerySpec(raw=raw)
    if not raw:
        return spec

    low = raw.lower()

    # country (match the longest multi-word country first)
    for token in sorted(_COUNTRIES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(token)}\b", low):
            spec.country = _COUNTRIES[token]
            break

    # zip code
    m = _ZIP_RE.search(raw)
    if m:
        spec.zip = m.group(1)

    # split "what" vs "where": everything before the zip is the category,
    # otherwise fall back to the first token as the category.
    if m:
        spec.what = raw[: m.start()].strip(" ,")
        spec.where = raw[m.start():].strip(" ,")
    else:
        parts = raw.split(" ", 1)
        spec.what = parts[0]
        spec.where = parts[1] if len(parts) > 1 else ""

    if not spec.what:
        spec.what = raw

    # state (2-letter US) inside the where-part
    sm = _US_STATE_RE.search(spec.where or raw)
    if sm:
        spec.state = sm.group(1).upper()

    # city = where minus zip/state/country tokens
    city = spec.where
    for junk in (spec.zip, spec.state, spec.state.lower() if spec.state else ""):
        if junk:
            city = re.sub(rf"\b{re.escape(junk)}\b", " ", city, flags=re.I)
    for token in _COUNTRIES:
        city = re.sub(rf"\b{re.escape(token)}\b", " ", city, flags=re.I)
    spec.city = collapse_spaces(city).strip(" ,").title()

    return spec
