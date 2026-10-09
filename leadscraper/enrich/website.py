"""Crawl a business website for owner/contact signals.

Fetches the homepage plus a few likely pages (contact / about / team / ...),
and returns the combined text + html so the email/people/social extractors can
work over everything in one pass.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from ..config import CONTACT_PAGE_HINTS, Settings
from ..util import clean_text, normalize_url, registrable_domain, same_registrable_domain

log = logging.getLogger(__name__)

_MAX_BYTES = 2_000_000
_robots_cache: dict[str, RobotFileParser | None] = {}
_robots_lock = threading.Lock()


@dataclass
class EnrichResult:
    ok: bool = False
    final_domain: str = ""
    html: str = ""
    text: str = ""
    emails: set[str] = field(default_factory=set)
    socials: dict[str, str] = field(default_factory=dict)


class WebsiteEnricher:
    def __init__(self, settings: Settings) -> None:
        self.s = settings

    def enrich(self, website: str) -> EnrichResult:
        res = EnrichResult()
        start = normalize_url(website)
        if not start:
            return res

        with httpx.Client(
            headers={"User-Agent": self.s.user_agent, "Accept-Language": "en-US,en;q=0.9"},
            timeout=self.s.http_timeout,
            follow_redirects=True,
        ) as client:
            home = self._fetch(client, start)
            if not home:
                return res
            html, final_url = home
            res.ok = True
            res.final_domain = registrable_domain(final_url)

            htmls = [html]
            # discover and fetch a few promising internal pages
            for link in self._pick_pages(final_url, html):
                page = self._fetch(client, link)
                if page:
                    htmls.append(page[0])
                if len(htmls) >= self.s.max_pages_per_site:
                    break

        combined_html = "\n".join(htmls)
        res.html = combined_html
        res.text = self._to_text(combined_html)

        from .emails import extract_emails
        from .social import extract_socials

        res.emails = extract_emails(combined_html, res.text)
        res.socials = extract_socials(combined_html)
        return res

    # -- internals -------------------------------------------------------
    def _fetch(self, client: httpx.Client, url: str) -> tuple[str, str] | None:
        if self.s.respect_robots and not self._allowed(client, url):
            log.debug("robots.txt disallows %s", url)
            return None
        try:
            r = client.get(url)
        except Exception as exc:
            log.debug("fetch failed %s: %s", url, exc)
            return None
        ctype = r.headers.get("content-type", "")
        if r.status_code >= 400 or ("html" not in ctype and ctype):
            return None
        text = r.text[:_MAX_BYTES]
        return text, str(r.url)

    def _pick_pages(self, base_url: str, html: str) -> list[str]:
        base_dom = registrable_domain(base_url)
        soup = BeautifulSoup(html, "lxml")
        scored: list[tuple[int, str]] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            full = urljoin(base_url, href).split("#")[0]
            if full in seen or not same_registrable_domain(full, base_url):
                continue
            path = urlparse(full).path.lower()
            anchor = (a.get_text() or "").lower()
            for i, hint in enumerate(CONTACT_PAGE_HINTS):
                if hint in path or hint in anchor:
                    seen.add(full)
                    scored.append((i, full))
                    break
        scored.sort(key=lambda t: t[0])
        return [u for _, u in scored]

    @staticmethod
    def _to_text(html: str) -> str:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        return clean_text(soup.get_text(" "))

    def _allowed(self, client: httpx.Client, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        with _robots_lock:
            rp = _robots_cache.get(root, "missing")
        if rp == "missing":
            rp = self._load_robots(client, root)
            with _robots_lock:
                _robots_cache[root] = rp
        if rp is None:
            return True
        try:
            return rp.can_fetch(self.s.user_agent, url)
        except Exception:
            return True

    @staticmethod
    def _load_robots(client: httpx.Client, root: str) -> RobotFileParser | None:
        try:
            r = client.get(root + "/robots.txt")
        except Exception:
            return None
        if r.status_code in (401, 403):
            rp = RobotFileParser()
            rp.disallow_all = True
            return rp
        if r.status_code >= 400:
            return None  # treat as allow-all
        rp = RobotFileParser()
        try:
            rp.parse(r.text.splitlines())
        except Exception:
            return None
        return rp
