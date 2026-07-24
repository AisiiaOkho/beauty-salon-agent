from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SERVICE_KEY_BASIC_MANICURE_WITH_COATING = "basic_manicure_with_coating"


@dataclass(frozen=True)
class ServiceMatch:
    """Explainable deterministic service classification."""

    status: str
    service_name_normalized: str | None
    confidence: str
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriceValue:
    """Normalized price value in minor currency units."""

    price_type: str
    amount_minor: int | None = None
    currency: str | None = None
    range_min_minor: int | None = None
    range_max_minor: int | None = None


@dataclass(frozen=True)
class PriceEvidence:
    """Raw text or structured object that may contain a service price."""

    service_name_raw: str
    price_raw: str | int | float | None
    source_type: str
    source_url: str | None
    evidence_text: str
    raw_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PriceExtractionResult:
    """Final extraction outcome persisted for one salon check."""

    salon_id: int
    service_name_raw: str | None
    service_name_normalized: str | None
    amount_minor: int | None
    currency: str | None
    price_type: str
    range_min_minor: int | None
    range_max_minor: int | None
    source_type: str | None
    source_url: str | None
    evidence_text: str | None
    confidence: str
    extraction_status: str
    checked_at: str | None = None
    parser_version: str = "1.0.0"
    raw_evidence: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None

    @property
    def service_key(self) -> str:
        """Return the stable target service key."""

        return SERVICE_KEY_BASIC_MANICURE_WITH_COATING


@dataclass
class PricingSummary:
    """Counters collected during one pricing extraction run."""

    processed: int = 0
    found: int = 0
    not_found: int = 0
    ambiguous: int = 0
    errors: int = 0
    skipped: int = 0
    dry_run: bool = False
