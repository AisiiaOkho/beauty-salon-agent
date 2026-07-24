from __future__ import annotations

import math
from collections.abc import Callable

from config.settings import (
    GRID_SIZE_METERS,
    SCANNER_CELL_RETRY_LIMIT,
    SCANNER_DRY_RUN,
    SCANNER_MAX_CELLS_PER_RUN,
    SEARCH_QUERIES,
    TWOGIS_MAX_PAGES_PER_QUERY,
)
from database_manager import Database
from filters.salon_classifier import SalonClassifier
from providers.search_client import OrganizationSearchClient
from providers.twogis_client import MissingTwoGisApiKeyError, TwoGisPlacesClient
from scanner.models import ClassificationResult, RawOrganization, ScanSummary

ProgressLogger = Callable[[str], None]


class SalonScannerManager:
    """Orchestrates resumable grid-cell scanning for manicure salons."""

    def __init__(
        self,
        database: Database,
        search_client: OrganizationSearchClient | None = None,
        classifier: SalonClassifier | None = None,
        max_cells_per_run: int = SCANNER_MAX_CELLS_PER_RUN,
        max_pages_per_query: int = TWOGIS_MAX_PAGES_PER_QUERY,
        retry_limit: int = SCANNER_CELL_RETRY_LIMIT,
        dry_run: bool = SCANNER_DRY_RUN,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if max_cells_per_run < 0:
            raise ValueError("max_cells_per_run cannot be negative.")

        if max_pages_per_query <= 0:
            raise ValueError("max_pages_per_query must be greater than zero.")

        self.database = database
        self.classifier = classifier or SalonClassifier()
        self.max_cells_per_run = max_cells_per_run
        self.max_pages_per_query = max_pages_per_query
        self.retry_limit = retry_limit
        self.dry_run = dry_run
        self.progress_logger = progress_logger or print
        self.search_client = search_client

        if self.search_client is None and not self.dry_run:
            self.search_client = TwoGisPlacesClient(
                progress_logger=self.progress_logger,
            )

    def scan_region(self, region: dict[str, object]) -> ScanSummary:
        """Scan up to the configured number of pending cells for a region."""

        region_id = int(region["id"])
        summary = ScanSummary(dry_run=self.dry_run)
        recovered = self.database.recover_interrupted_grid_cells(
            region_id=region_id,
            retry_limit=self.retry_limit,
        )

        if recovered:
            self.progress_logger(f"Recovered interrupted cells: {recovered}")

        if self.dry_run:
            self.progress_logger(
                "2GIS scanner dry-run is enabled; no provider requests made."
            )
            return summary

        if self.search_client is None:
            raise MissingTwoGisApiKeyError("2GIS search client is not configured.")

        for _ in range(self.max_cells_per_run):
            cell = self.database.start_next_grid_cell_scan(
                region_id=region_id,
                retry_limit=self.retry_limit,
            )

            if cell is None:
                break

            cell_summary = self._scan_cell(region_id=region_id, cell=cell)
            summary.cells_processed += cell_summary.cells_processed
            summary.raw_organizations_found += cell_summary.raw_organizations_found
            summary.accepted_salons += cell_summary.accepted_salons
            summary.rejected_results += cell_summary.rejected_results
            summary.duplicates_merged += cell_summary.duplicates_merged
            summary.errors += cell_summary.errors

        self.database.update_region_salon_count(region_id)
        return summary

    def _scan_cell(
        self,
        region_id: int,
        cell: dict[str, object],
    ) -> ScanSummary:
        grid_cell_id = int(cell["id"])
        attempt_id = self.database.create_scan_attempt(
            region_id=region_id,
            grid_cell_id=grid_cell_id,
        )
        summary = ScanSummary(cells_processed=1)
        organizations_found_in_cell = 0

        try:
            for query in SEARCH_QUERIES:
                page = 1

                while page <= self.max_pages_per_query:
                    result_page = self.search_client.search(
                        query=query,
                        center_lat=float(cell["center_lat"]),
                        center_lon=float(cell["center_lon"]),
                        radius_meters=self._cell_radius_meters(),
                        page=page,
                        grid_cell_id=grid_cell_id,
                    )
                    self.progress_logger(
                        "2GIS page parsed: "
                        f"cell={cell['cell_order']} "
                        f"query='{query}' "
                        f"page={page} "
                        f"organizations={len(result_page.organizations)} "
                        f"has_next={result_page.has_next_page}"
                    )
                    organizations_found_in_cell += len(
                        result_page.organizations
                    )

                    for organization in result_page.organizations:
                        self._process_organization(
                            region_id=region_id,
                            organization=organization,
                            summary=summary,
                        )

                    if not result_page.has_next_page:
                        break

                    page += 1

            self.database.mark_grid_cell_completed(
                grid_cell_id=grid_cell_id,
                organizations_found=organizations_found_in_cell,
            )
            self.database.complete_scan_attempt(
                attempt_id=attempt_id,
                raw_organizations_found=summary.raw_organizations_found,
                accepted_salons=summary.accepted_salons,
                rejected_results=summary.rejected_results,
                duplicates_merged=summary.duplicates_merged,
            )
        except Exception as error:
            summary.errors += 1
            self.database.mark_grid_cell_failed(
                grid_cell_id=grid_cell_id,
                error=str(error),
                retry_limit=self.retry_limit,
            )
            self.database.fail_scan_attempt(attempt_id, str(error))
            self.progress_logger(
                f"Cell {cell['cell_order']} failed: {error}"
            )

        return summary

    def _process_organization(
        self,
        region_id: int,
        organization: RawOrganization,
        summary: ScanSummary,
    ) -> None:
        summary.raw_organizations_found += 1
        raw_result_id = self.database.save_raw_organization_result(
            region_id=region_id,
            organization=organization,
        )
        classification = self.classifier.classify(organization)

        if classification.accepted:
            salon_id, merged = self.database.upsert_salon(
                region_id=region_id,
                organization=organization,
                classification=classification,
            )
            summary.accepted_salons += 1

            if merged:
                summary.duplicates_merged += 1
        else:
            salon_id = None
            summary.rejected_results += 1

        self.database.save_salon_discovery(
            region_id=region_id,
            organization=organization,
            classification=classification,
            raw_result_id=raw_result_id,
            salon_id=salon_id,
        )

    def _cell_radius_meters(self) -> int:
        return math.ceil((GRID_SIZE_METERS * math.sqrt(2)) / 2)
