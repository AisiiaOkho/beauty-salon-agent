from __future__ import annotations

from typing import Protocol

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
