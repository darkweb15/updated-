"""Pluggable business-discovery sources."""
from __future__ import annotations

from ..config import Settings
from ..query import QuerySpec
from .base import LeadSource


def get_source(settings: Settings) -> LeadSource:
    if settings.source == "osm":
        from .osm import OSMSource
        return OSMSource(settings)
    from .google_maps import GoogleMapsSource
    return GoogleMapsSource(settings)
