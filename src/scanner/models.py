from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RawOrganization:
    """Raw organization data returned by a search provider."""

    external_source: str
    external_id: str | None
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    phone: str | None = None
    website: str | None = None
    social_links: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    description: str | None = None
    working_hours: str | None = None
    branch_info: str | None = None
    raw_payload: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    discovered_query: str | None = None
    discovered_grid_cell_id: int | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class SearchPage:
    """One provider search response page."""

    organizations: list[RawOrganization]
    page: int
    has_next_page: bool


@dataclass(frozen=True)
class ClassificationResult:
    """Deterministic salon classification decision."""

    accepted: bool
    confidence: float
    reasons: list[str]
    salon_type: str


@dataclass
class ScanSummary:
    """Counters collected during a scanner run."""

    cells_processed: int = 0
    raw_organizations_found: int = 0
    accepted_salons: int = 0
    rejected_results: int = 0
    duplicates_merged: int = 0
    errors: int = 0
    dry_run: bool = False
