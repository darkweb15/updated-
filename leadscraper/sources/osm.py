"""OpenStreetMap business discovery (free, no API key, ToS-clean).

Geocode the location with Nominatim, then pull businesses in that bounding box
from the Overpass API. Coverage is thinner than Google Maps (especially for
emails/owners) but it is completely free and allowed.
"""
from __future__ import annotations

import logging
import time

import httpx

from ..config import Settings
from ..models import Lead
from ..query import QuerySpec

log = logging.getLogger(__name__)

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS = "https://overpass-api.de/api/interpreter"

# Nominatim's usage policy requires an identifying UA; it blocks placeholder /
# example.com contacts, so keep this real and generic (never the user's email).
OSM_USER_AGENT = "leadscraper/0.1 (contact: leadscraper@users.noreply.github.com)"

# Map a plain-English category to OSM tag filters.
CATEGORY_TAGS: dict[str, list[tuple[str, str]]] = {
    "restaurant": [("amenity", "restaurant")],
    "restaurants": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "coffee": [("amenity", "cafe")],
    "bar": [("amenity", "bar"), ("amenity", "pub")],
    "pub": [("amenity", "pub")],
    "bakery": [("shop", "bakery")],
    "hotel": [("tourism", "hotel")],
    "hotels": [("tourism", "hotel")],
    "dentist": [("amenity", "dentist"), ("healthcare", "dentist")],
    "dentists": [("amenity", "dentist")],
    "doctor": [("amenity", "doctors"), ("healthcare", "doctor")],
    "doctors": [("amenity", "doctors")],
    "pharmacy": [("amenity", "pharmacy")],
    "gym": [("leisure", "fitness_centre")],
    "fitness": [("leisure", "fitness_centre")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "spa": [("leisure", "spa"), ("shop", "beauty")],
    "lawyer": [("office", "lawyer")],
    "plumber": [("craft", "plumber")],
    "electrician": [("craft", "electrician")],
    "realestate": [("office", "estate_agent")],
    "car": [("shop", "car"), ("shop", "car_repair")],
    "clinic": [("amenity", "clinic"), ("healthcare", "clinic")],
}


class OSMSource:
    name = "openstreetmap"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = httpx.Client(
            headers={"User-Agent": OSM_USER_AGENT, "Accept-Language": "en-US"},
            timeout=60.0,
            follow_redirects=True,
        )

    def search(self, spec: QuerySpec) -> list[Lead]:
        where = spec.where or spec.raw
        bbox = self._geocode_bbox(where)
        if not bbox:
            log.warning("Could not geocode location: %r", where)
            return []
        query = self._build_overpass(spec, bbox)
        log.info("Overpass query over bbox %s", bbox)
        try:
            resp = self.client.post(OVERPASS, data={"data": query})
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
        except Exception as exc:
            log.warning("Overpass request failed: %s", exc)
            return []

        leads: list[Lead] = []
        for el in elements:
            lead = self._to_lead(el, spec)
            if lead:
                leads.append(lead)
            if len(leads) >= self.settings.limit:
                break
        log.info("OSM returned %d businesses", len(leads))
        return leads

    # -- internals -------------------------------------------------------
    def _geocode_bbox(self, where: str) -> tuple[float, float, float, float] | None:
        try:
            resp = self.client.get(
                NOMINATIM,
                params={"q": where, "format": "json", "limit": 1},
            )
            resp.raise_for_status()
            data = resp.json()
            time.sleep(1.0)  # Nominatim: max 1 req/sec
            if not data:
                return None
            # boundingbox = [south, north, west, east] as strings
            s, n, w, e = (float(x) for x in data[0]["boundingbox"])
            return (s, w, n, e)
        except Exception as exc:
            log.warning("Nominatim failed: %s", exc)
            return None

    def _build_overpass(self, spec: QuerySpec, bbox) -> str:
        s, w, n, e = bbox
        bb = f"{s},{w},{n},{e}"
        what = (spec.what or "").strip().lower().replace(" ", "")
        tags = CATEGORY_TAGS.get(what)
        clauses: list[str] = []
        if tags:
            for k, v in tags:
                for typ in ("node", "way"):
                    clauses.append(f'{typ}["{k}"="{v}"]({bb});')
        else:
            # generic: name matches the search word and it's a real business
            word = spec.what or spec.raw
            for key in ("shop", "amenity", "office", "craft"):
                clauses.append(f'node["name"~"{word}",i]["{key}"]({bb});')
                clauses.append(f'way["name"~"{word}",i]["{key}"]({bb});')
        body = "\n  ".join(clauses)
        return f"[out:json][timeout:60];\n(\n  {body}\n);\nout center tags {self.settings.limit * 2};"

    def _to_lead(self, el: dict, spec: QuerySpec) -> Lead | None:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name:
            return None
        lead = Lead(query=spec.raw, source=self.name)
        lead.business_name = name
        lead.category = spec.what
        lead.phone = tags.get("phone") or tags.get("contact:phone", "")
        lead.website = tags.get("website") or tags.get("contact:website", "")

        # address
        hn = tags.get("addr:housenumber", "")
        st = tags.get("addr:street", "")
        street = f"{hn} {st}".strip()
        lead.city = tags.get("addr:city", spec.city)
        lead.state = tags.get("addr:state", spec.state)
        lead.zip = tags.get("addr:postcode", spec.zip)
        lead.country = tags.get("addr:country", spec.country)
        lead.address = ", ".join(
            p for p in (street, lead.city, lead.state, lead.zip) if p
        )

        # coordinates
        if "lat" in el and "lon" in el:
            lead.lat, lead.lng = el["lat"], el["lon"]
        elif "center" in el:
            lead.lat, lead.lng = el["center"].get("lat"), el["center"].get("lon")

        # seed any email/owner OSM already knows so enrichment can use it
        seed = []
        osm_email = tags.get("email") or tags.get("contact:email")
        if osm_email:
            seed.append(f"Email: {osm_email}")
        if tags.get("contact:owner") or tags.get("operator"):
            seed.append(f"Owner: {tags.get('contact:owner') or tags.get('operator')}")
        lead._enrich_text = " . ".join(seed)
        return lead
