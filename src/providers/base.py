from __future__ import annotations

from typing import Protocol

from enrichment.models import OrganizationDetailsResult
from scanner.models import SearchPage


class OrganizationSearchClient(Protocol):
    """Interface for organization search providers."""

    def search(
        self,
        *,
        query: str,
        center_lat: float,
        center_lon: float,
        radius_meters: int,
        page: int,
        grid_cell_id: int,
    ) -> SearchPage:
        """Search organizations around a grid-cell center."""


class OrganizationDetailsClient(Protocol):
    """Interface for provider-specific organization details."""

    def get_organization_details(
        self,
        external_id: str,
        salon_id: int | None = None,
    ) -> OrganizationDetailsResult:
        """Fetch and parse details for one provider organization ID."""
