"""Orchestrates the full run: discover -> enrich -> verify -> score -> dedupe."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .config import Settings
from .dedupe import dedupe
from .enrich.emails import classify, extract_emails, select_best
from .enrich.people import extract_people
from .enrich.website import WebsiteEnricher
from .models import Lead
from .query import QuerySpec
from .scoring import score_lead
from .sources import get_source
from .util import registrable_domain
from .verify.email_verify import EmailVerifier

log = logging.getLogger(__name__)

_TIER_ORDER = {"T1": 0, "T2": 1, "T3": 2, "DISCARD": 3, "": 4}


def discover(spec: QuerySpec, settings: Settings) -> tuple[list[Lead], str]:
    """Phase 1: find businesses (no enrichment yet)."""
    source = get_source(settings)
    log.info("Discovering businesses via %s ...", source.name)
    return source.search(spec), source.name


def enrich_leads(leads: list[Lead], spec: QuerySpec, settings: Settings,
                 progress: Callable[[int, int], None] | None = None) -> list[Lead]:
    """Phase 2: enrich, verify, score, dedupe and rank."""
    if not leads:
        return []

    enricher = WebsiteEnricher(settings)
    verifier = EmailVerifier(settings)

    def worker(lead: Lead) -> Lead:
        try:
            _process_one(lead, spec, settings, enricher, verifier)
        except Exception as exc:  # never let one lead kill the batch
            log.warning("enrich failed for %s: %s", lead.business_name, exc)
            lead.add_flag("enrich_error")
        return lead

    total = len(leads)
    done = 0
    results: list[Lead] = []
    with ThreadPoolExecutor(max_workers=settings.concurrency) as pool:
        futures = [pool.submit(worker, l) for l in leads]
        for fut in as_completed(futures):
            results.append(fut.result())
            done += 1
            if progress:
                progress(done, total)

    results = dedupe(results)
    results.sort(key=lambda l: (_TIER_ORDER.get(l.tier, 4), -l.score))
    return results


def run(spec: QuerySpec, settings: Settings,
        progress: Callable[[int, int], None] | None = None) -> list[Lead]:
    leads, _ = discover(spec, settings)
    return enrich_leads(leads, spec, settings, progress)


def _process_one(lead: Lead, spec: QuerySpec, settings: Settings,
                 enricher: WebsiteEnricher, verifier: EmailVerifier) -> None:
    text = lead._enrich_text or ""
    html = ""
    website_domain = registrable_domain(lead.website)

    if lead.website:
        res = enricher.enrich(lead.website)
        lead.website_ok = res.ok
        if res.final_domain:
            website_domain = res.final_domain
        lead.website_domain = website_domain
        text = f"{text} {res.text}".strip()
        html = res.html
        lead.linkedin = res.socials.get("linkedin", "")
        lead.instagram = res.socials.get("instagram", "")
        lead.facebook = res.socials.get("facebook", "")
        lead.twitter = res.socials.get("twitter", "")
        seed_emails = set(res.emails)
    else:
        seed_emails = set()

    # emails from any seed text too (e.g. OSM-provided address)
    seed_emails |= extract_emails(html, text)

    # people / owner
    owner_name, owner_title, all_names = extract_people(text)
    lead.owner_name = owner_name
    lead.owner_title = owner_title

    # classify candidates
    cands = [classify(addr, website_domain, all_names) for addr in sorted(seed_emails)]
    lead.candidates = cands

    best = select_best(cands)
    if best:
        status, verified = verifier.verify(best.address)
        best.status, best.verified = status, verified
        lead.email = best.address
        lead.email_type = best.kind
        lead.email_domain_match = best.domain_match
        lead.email_free_domain = best.is_free
        lead.email_status = status
        lead.email_verified = verified

    others = [c.address for c in cands if c.address != lead.email]
    lead.other_emails = "; ".join(others[:8])

    score_lead(lead, spec, settings)
