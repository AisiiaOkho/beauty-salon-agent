from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from config.settings import (
    ENRICHMENT_DRY_RUN,
    ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN,
    ENRICHMENT_REFRESH_AFTER_DAYS,
)
from database_manager import Database
from providers.base import OrganizationDetailsClient
from providers.twogis_client import MissingTwoGisApiKeyError, TwoGisPlacesClient

ProgressLogger = Callable[[str], None]


@dataclass
class EnrichmentSummary:
    """Counters collected during one details enrichment run."""

    processed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    contacts_created: int = 0
    contacts_updated: int = 0
    contacts_deactivated: int = 0
    dry_run: bool = False


class OrganizationEnricher:
    """Fetch and persist 2GIS details for accepted salon records."""

    def __init__(
        self,
        database: Database,
        details_client: OrganizationDetailsClient | None = None,
        max_organizations_per_run: int = ENRICHMENT_MAX_ORGANIZATIONS_PER_RUN,
        dry_run: bool = ENRICHMENT_DRY_RUN,
        refresh_after_days: int | None = ENRICHMENT_REFRESH_AFTER_DAYS,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if max_organizations_per_run < 0:
            raise ValueError("max_organizations_per_run cannot be negative.")

        self.database = database
        self.details_client = details_client
        self.max_organizations_per_run = max_organizations_per_run
        self.dry_run = dry_run
        self.refresh_after_days = refresh_after_days
        self.progress_logger = progress_logger or print

        if self.details_client is None and not self.dry_run:
            self.details_client = TwoGisPlacesClient(
                progress_logger=self.progress_logger,
            )

    def enrich_next(self) -> EnrichmentSummary:
        """Enrich up to the configured number of eligible salons."""

        summary = EnrichmentSummary(dry_run=self.dry_run)

        for _ in range(self.max_organizations_per_run):
            salon = self.database.get_next_salon_for_enrichment(
                self.refresh_after_days
            )

            if salon is None:
                break

            self._process_salon(salon, summary)

        return summary

    def enrich_salon_id(self, salon_id: int) -> EnrichmentSummary:
        """Enrich one explicit salon id if it is eligible."""

        summary = EnrichmentSummary(dry_run=self.dry_run)
        salon = self.database.get_salon_for_enrichment_by_id(salon_id)

        if salon is None:
            summary.skipped += 1
            return summary

        self._process_salon(salon, summary)
        return summary

    def enrich_external_id(self, external_id: str) -> EnrichmentSummary:
        """Enrich one explicit 2GIS external id if it is eligible."""

        summary = EnrichmentSummary(dry_run=self.dry_run)
        salon = self.database.get_salon_for_enrichment_by_external_id(external_id)

        if salon is None:
            summary.skipped += 1
            return summary

        self._process_salon(salon, summary)
        return summary

    def _process_salon(
        self,
        salon: dict[str, object],
        summary: EnrichmentSummary,
    ) -> None:
        salon_id = int(salon["id"])
        external_id = str(salon["external_id"])

        if self.dry_run:
            summary.skipped += 1
            self.progress_logger(
                "2GIS details dry-run: "
                f"salon_id={salon_id} external_id_present={bool(external_id)}"
            )
            return

        if self.details_client is None:
            raise MissingTwoGisApiKeyError("2GIS details client is not configured.")

        summary.processed += 1
        result = self.details_client.get_organization_details(
            external_id=external_id,
            salon_id=salon_id,
        )
        self.database.save_organization_detail_result(
            salon_id=salon_id,
            result=result,
        )

        if result.status != "success" or result.details is None:
            summary.failed += 1
            self.database.mark_salon_details_status(
                salon_id=salon_id,
                status=result.status,
                error=result.error_message,
            )
            self.progress_logger(
                "2GIS details failed: "
                f"salon_id={salon_id} status={result.status}"
            )
            return

        self.database.apply_organization_details(
            salon_id=salon_id,
            details=result.details,
        )
        created, updated, deactivated = self.database.upsert_salon_contacts(
            salon_id=salon_id,
            contacts=result.details.contacts,
            source=result.details.external_source,
        )
        summary.succeeded += 1
        summary.contacts_created += created
        summary.contacts_updated += updated
        summary.contacts_deactivated += deactivated
        self.progress_logger(
            "2GIS details enriched: "
            f"salon_id={salon_id} "
            f"contacts_created={created} "
            f"contacts_updated={updated} "
            f"contacts_deactivated={deactivated}"
        )
