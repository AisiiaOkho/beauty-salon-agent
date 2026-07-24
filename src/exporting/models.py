from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ExportPrice:
    """Current active target price prepared for workbook output."""

    display_value: str | None
    currency: str | None
    price_type: str
    service_name: str | None
    source_type: str | None
    source_url: str | None
    status: str


@dataclass(frozen=True)
class ExportSalon:
    """One accepted salon row for the main export sheet."""

    region: str
    city: str | None
    name: str
    address: str | None
    phones: list[str] = field(default_factory=list)
    links: list[str] = field(default_factory=list)
    price: ExportPrice | None = None
    masters_count: str | None = None
    business_profile: str | None = None
    verification_status: str | None = None
    comment: str | None = None
    external_source: str | None = None
    external_id: str | None = None
    first_seen_at: datetime | None = None
    last_checked_at: datetime | None = None
    classifier_version: str | None = None


@dataclass(frozen=True)
class ExcludedSalon:
    """One rejected salon row for the excluded audit sheet."""

    region: str
    name: str
    address: str | None
    rejection_reason: str | None
    business_profile: str | None
    reason_codes: str | None
    external_id: str | None
    classifier_version: str | None
    classified_at: datetime | None


@dataclass(frozen=True)
class RegionExportSummary:
    """Per-region export summary metrics."""

    region: str
    accepted: int
    rejected: int
    with_contacts: int
    with_prices: int
    last_scan_status: str | None


@dataclass(frozen=True)
class ExportDataset:
    """All data needed to render an export workbook."""

    accepted_salons: list[ExportSalon]
    excluded_salons: list[ExcludedSalon]
    region_summaries: list[RegionExportSummary]
    database_path: str
    total_regions: int
    regions_with_grids: int
    classifier_version: str


@dataclass(frozen=True)
class ExportDryRunResult:
    """Dry-run export preview."""

    output_path: str
    accepted_count: int
    rejected_count: int
    file_written: bool = False


@dataclass(frozen=True)
class ExportResult:
    """Final workbook generation result."""

    output_path: str
    accepted_count: int
    rejected_count: int
    file_size_bytes: int
    file_written: bool = True
