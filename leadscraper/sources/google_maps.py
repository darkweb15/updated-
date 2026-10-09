"""Google Maps business discovery via Playwright.

NOTE (read me): scraping Google Maps is against Google's Terms of Service and
the page has anti-bot measures + a DOM that changes often. This source is
best-effort and the selectors may need occasional updates. For a fully free &
ToS-clean alternative use ``--source osm`` (OpenStreetMap).
"""
from __future__ import annotations

import logging
import random
import re
import time
from urllib.parse import quote_plus

from ..config import Settings
from ..models import Lead
from ..query import QuerySpec
from ..util import clean_text

log = logging.getLogger(__name__)

_COORD_PRECISE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")
_COORD_AT = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
_REVIEWS_RE = re.compile(r"([\d,]+)\s+review", re.I)
_RATING_RE = re.compile(r"^([0-5](?:\.\d)?)")
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_ZIP_RE = re.compile(r",\s*([A-Z]{2})\s+\d{5}")

_BLOCK_RESOURCES = {"image", "media", "font"}


class GoogleMapsSource:
    name = "google_maps"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # -- public ----------------------------------------------------------
    def search(self, spec: QuerySpec) -> list[Lead]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise SystemExit(
                "Playwright is not installed. Run:\n"
                "    pip install playwright\n"
                "    playwright install chromium"
            ) from exc

        leads: list[Lead] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=self.settings.headless)
            context = browser.new_context(
                locale="en-US",
                user_agent=self.settings.user_agent,
                viewport={"width": 1366, "height": 900},
            )
            context.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            # Speed up: drop heavy resources we never need.
            context.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if route.request.resource_type in _BLOCK_RESOURCES
                    else route.continue_()
                ),
            )
            page = context.new_page()
            try:
                place_urls = self._collect_place_urls(page, spec.raw)
                log.info("Found %d place links on Maps", len(place_urls))
                for i, url in enumerate(place_urls[: self.settings.limit], 1):
                    try:
                        lead = self._scrape_place(page, url, spec)
                        if lead:
                            leads.append(lead)
                            log.info("  [%d] %s", i, lead.business_name or "?")
                    except Exception as exc:  # keep going on any single failure
                        log.warning("  [%d] failed: %s", i, exc)
                    time.sleep(random.uniform(0.4, 1.1))
            finally:
                context.close()
                browser.close()
        return leads

    # -- internals -------------------------------------------------------
    def _handle_consent(self, page) -> None:
        if "consent." not in page.url:
            return
        for label in ("Reject all", "Accept all", "I agree", "Agree"):
            try:
                btn = page.get_by_role("button", name=label)
                if btn.count():
                    btn.first.click(timeout=4000)
                    page.wait_for_load_state("domcontentloaded", timeout=15000)
                    return
            except Exception:
                continue

    def _collect_place_urls(self, page, raw_query: str) -> list[str]:
        url = f"https://www.google.com/maps/search/{quote_plus(raw_query)}"
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self._handle_consent(page)

        # Single result sometimes opens a detail page directly (no feed).
        try:
            page.wait_for_selector("div[role='feed'], h1", timeout=20000)
        except Exception:
            return []

        feed = page.query_selector("div[role='feed']")
        if not feed:
            # direct single place
            return [page.url]

        seen: list[str] = []
        seen_set: set[str] = set()
        stale = 0
        for _ in range(40):
            for a in page.query_selector_all("div[role='feed'] a[href*='/maps/place/']"):
                href = a.get_attribute("href") or ""
                if href and href not in seen_set:
                    seen_set.add(href)
                    seen.append(href)
            if len(seen) >= self.settings.limit:
                break
            prev = len(seen)
            try:
                page.evaluate(
                    "el => el.scrollTo(0, el.scrollHeight)", feed
                )
            except Exception:
                break
            time.sleep(random.uniform(1.0, 1.8))
            # reached the end?
            if page.get_by_text("You've reached the end of the list").count():
                # one more sweep then stop
                for a in page.query_selector_all("div[role='feed'] a[href*='/maps/place/']"):
                    href = a.get_attribute("href") or ""
                    if href and href not in seen_set:
                        seen_set.add(href)
                        seen.append(href)
                break
            stale = stale + 1 if len(seen) == prev else 0
            if stale >= 4:
                break
        return seen

    def _scrape_place(self, page, url: str, spec: QuerySpec) -> Lead | None:
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_selector("h1", timeout=15000)
        except Exception:
            return None
        time.sleep(random.uniform(0.3, 0.7))

        name = _text(page, "h1")
        if not name:
            return None

        lead = Lead(query=spec.raw, source=self.name)
        lead.business_name = clean_text(name)
        lead.google_maps_url = page.url

        # website (the real external site, not a google url)
        lead.website = _attr(page, "a[data-item-id='authority']", "href")

        # phone
        phone = _aria_after(page, "button[data-item-id^='phone']", "Phone:")
        if not phone:
            did = _attr(page, "button[data-item-id^='phone']", "data-item-id")
            if "tel:" in did:
                phone = did.split("tel:", 1)[1]
        lead.phone = clean_text(phone)

        # address
        addr = _aria_after(page, "button[data-item-id='address']", "Address:")
        if not addr:
            addr = _text(page, "button[data-item-id='address'] .Io6YTe")
        lead.address = clean_text(addr)
        self._parse_address(lead, spec)

        # category
        lead.category = clean_text(_text(page, "button[jsaction*='category']"))

        # rating + reviews
        rating_lbl = _attr(page, "span[aria-label*='stars'], span[role='img'][aria-label*='stars']", "aria-label")
        rm = _RATING_RE.match(rating_lbl.strip()) if rating_lbl else None
        if rm:
            try:
                lead.rating = float(rm.group(1))
            except ValueError:
                pass
        lead.reviews_count = _reviews_count(page)

        # permanently closed
        try:
            if page.get_by_text("Permanently closed").count():
                lead.permanently_closed = True
        except Exception:
            pass

        # coordinates from the URL
        src = page.url
        m = _COORD_PRECISE.search(src) or _COORD_AT.search(src)
        if m:
            try:
                lead.lat = float(m.group(1))
                lead.lng = float(m.group(2))
            except ValueError:
                pass

        return lead

    def _parse_address(self, lead: Lead, spec: QuerySpec) -> None:
        addr = lead.address
        if not addr:
            lead.zip = lead.zip or spec.zip
            lead.state = lead.state or spec.state
            lead.city = lead.city or spec.city
            lead.country = lead.country or spec.country
            return
        zm = _ZIP_RE.search(addr)
        if zm:
            lead.zip = zm.group(1)
        sz = _STATE_ZIP_RE.search(addr)
        if sz:
            lead.state = sz.group(1)
        parts = [p.strip() for p in addr.split(",")]
        if len(parts) >= 2:
            # city is usually the second-to-last meaningful chunk
            lead.city = parts[-2] if not _STATE_ZIP_RE.search(parts[-1]) else parts[-2]
        lead.state = lead.state or spec.state
        lead.city = lead.city or spec.city
        lead.country = lead.country or spec.country


# --- tiny DOM helpers ---------------------------------------------------
def _text(page, selector: str) -> str:
    try:
        el = page.query_selector(selector)
        return el.inner_text() if el else ""
    except Exception:
        return ""


def _attr(page, selector: str, attr: str) -> str:
    try:
        el = page.query_selector(selector)
        return (el.get_attribute(attr) or "") if el else ""
    except Exception:
        return ""


def _reviews_count(page) -> int | None:
    """Pull the review count from any aria-label / text that carries it."""
    selectors = (
        "button[aria-label*='review']",
        "span[aria-label*='review']",
        "[aria-label*='review']",
        "button[jsaction*='reviewChart']",
    )
    for sel in selectors:
        try:
            for el in page.query_selector_all(sel):
                lbl = el.get_attribute("aria-label") or ""
                m = _REVIEWS_RE.search(lbl)
                if m:
                    return int(m.group(1).replace(",", ""))
        except Exception:
            continue
    # fallback: the "(1,234)" shown next to the rating
    try:
        el = page.query_selector("div.F7nice, div[jsaction*='reviewChart']")
        if el:
            m = re.search(r"\(([\d,]+)\)", el.inner_text())
            if m:
                return int(m.group(1).replace(",", ""))
    except Exception:
        pass
    return None


def _aria_after(page, selector: str, prefix: str) -> str:
    label = _attr(page, selector, "aria-label")
    if label and label.startswith(prefix):
        return label[len(prefix):].strip()
    return label.strip() if label else ""
