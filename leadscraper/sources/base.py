"""Base class for business-discovery sources."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import Settings
from ..models import Lead
from ..query import QuerySpec


class LeadSource(ABC):
    name: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @abstractmethod
    def search(self, spec: QuerySpec) -> list[Lead]:
        """Return business-level leads for the query (no email enrichment yet)."""
        raise NotImplementedError
