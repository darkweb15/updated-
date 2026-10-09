"""Heuristic owner / decision-maker extraction from page text.

This is intentionally conservative: it only accepts a 2-3 word capitalised
name that sits next to a decision-maker title, and rejects common false
positives (nav labels, days, months, etc.). It will miss some owners -- that
is fine, a missing owner just lowers the score rather than inventing one.
"""
from __future__ import annotations

import re

from ..config import EXEC_TITLES, NAME_STOPWORDS, OWNER_TITLES

_ALL_TITLES = sorted(
    {t.replace("-", "[ -]?") for t in (OWNER_TITLES | EXEC_TITLES)},
    key=len,
    reverse=True,
)
_TITLE_ALT = "|".join(_ALL_TITLES)
# Titles are matched case-INSENSITIVELY (scoped inline flag); names stay
# case-SENSITIVE so the "Capitalised Name" heuristic keeps working and we do
# not grab lowercase words like "of" from "Owner of Joe's Diner".
_TITLE = rf"(?P<title>(?i:{_TITLE_ALT}))"
_NAME = r"(?P<name>[A-Z][a-zA-Z'’\-]+(?:\s+[A-Z][a-zA-Z'’\-]+){1,2})"

_TITLE_THEN_NAME = re.compile(rf"{_TITLE}\s*[:,\-–]?\s+{_NAME}")
_NAME_THEN_TITLE = re.compile(rf"{_NAME}\s*[,\-–]\s*(?:the\s+|our\s+|a\s+)?{_TITLE}")
_NAME_IS_TITLE = re.compile(rf"{_NAME}\s+(?:is|are|,)\s+(?:the\s+|our\s+|a\s+|co-?)?{_TITLE}")


def _valid_name(name: str) -> bool:
    toks = name.split()
    if not (2 <= len(toks) <= 3):
        return False
    for t in toks:
        tl = re.sub(r"[^a-z]", "", t.lower())
        if len(tl) < 2 or tl in NAME_STOPWORDS:
            return False
    return True


def _rank(title: str) -> int:
    t = title.lower().replace("-", " ").replace("  ", " ").strip()
    if any(k in t for k in ("owner", "founder", "proprietor")):
        return 3
    if any(k in t for k in ("ceo", "chief executive", "president",
                            "managing director", "general manager")) \
       or t in {"md", "gm"}:
        return 2
    return 1


def _canonical_title(title: str) -> str:
    t = re.sub(r"\s+", " ", title.strip())
    up = t.lower()
    special = {"ceo": "CEO", "md": "MD", "gm": "GM", "coo": "COO", "cto": "CTO"}
    if up in special:
        return special[up]
    return t.title()


def extract_people(text: str) -> tuple[str, str, list[str]]:
    """Return (best_name, best_title, all_candidate_names)."""
    if not text:
        return "", "", []
    found: list[tuple[int, str, str]] = []  # (rank, name, title)
    for pat in (_TITLE_THEN_NAME, _NAME_THEN_TITLE, _NAME_IS_TITLE):
        for m in pat.finditer(text):
            name = re.sub(r"\s+", " ", m.group("name")).strip()
            title = m.group("title")
            if _valid_name(name):
                found.append((_rank(title), name, _canonical_title(title)))

    if not found:
        return "", "", []

    # de-dup names, keep highest rank seen for each
    best_by_name: dict[str, tuple[int, str]] = {}
    for rank, name, title in found:
        if name not in best_by_name or rank > best_by_name[name][0]:
            best_by_name[name] = (rank, title)

    ordered = sorted(best_by_name.items(), key=lambda kv: kv[1][0], reverse=True)
    best_name, (_, best_title) = ordered[0]
    all_names = [n for n, _ in ordered]
    return best_name, best_title, all_names
