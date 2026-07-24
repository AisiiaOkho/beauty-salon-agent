from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ContactValue:
    """A normalized contact value parsed from provider details."""

    contact_type: str
    display_value: str
    normalized_value: str
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrganizationDetails:
    """Normalized organization details from a provider payload."""

    external_source: str
    external_id: str
    name: str | None = None
    full_address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    categories: list[str] = field(default_factory=list)
    description: str | None = None
    working_hours: str | None = None
    branch_info: str | None = None
    organization_id: str | None = None
    branch_id: str | None = None
    provider_updated_at: str | None = None
    contacts: list[ContactValue] = field(default_factory=list)


@dataclass(frozen=True)
class OrganizationDetailsResult:
    """Provider response and parser outcome for one details fetch."""

    external_source: str
    external_id: str
    status: str
    http_status: int | None
    payload_code: int | None
    sanitized_source_url: str
    raw_payload: dict[str, Any]
    details: OrganizationDetails | None = None
    error_message: str | None = None
