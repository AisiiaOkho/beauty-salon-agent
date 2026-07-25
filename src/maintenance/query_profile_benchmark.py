from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.settings import (  # noqa: E402
    DEFAULT_QUERY_PROFILE,
    GRID_SIZE_METERS,
    SCANNER_CELL_RETRY_LIMIT,
    TWOGIS_API_KEY_ENV,
    TWOGIS_MAX_PAGES_PER_QUERY,
)
from database_manager import Database  # noqa: E402
from filters.salon_classifier import SalonClassifier  # noqa: E402
from providers.search_client import OrganizationSearchClient  # noqa: E402
from providers.twogis_client import MissingTwoGisApiKeyError, TwoGisPlacesClient  # noqa: E402
from scanner.models import ClassificationResult, RawOrganization  # noqa: E402
from scanner.query_profiles import QueryProfile, resolve_query_profile  # noqa: E402


@dataclass
class ProfileFetchResult:
    """One query-profile result for a single grid cell."""

    profile: QueryProfile
    request_count: int = 0
    http_statuses: Counter[int] = field(default_factory=Counter)
    meta_codes: Counter[int] = field(default_factory=Counter)
    organizations: list[RawOrganization] = field(default_factory=list)
    by_external_id: dict[str, tuple[RawOrganization, ClassificationResult]] = field(default_factory=dict)
    duration_seconds: float = 0.0


@dataclass
class CellBenchmarkResult:
    """Paired benchmark result for one cell."""

    benchmark_run_id: int | None
    cell_id: int
    cell_order: int
    full: ProfileFetchResult | None = None
    reduced: ProfileFetchResult | None = None
    missing_from_reduced: list[str] = field(default_factory=list)
    extra_in_reduced: list[str] = field(default_factory=list)
    accepted_missing_from_reduced: list[str] = field(default_factory=list)
    rejected_missing_from_reduced: list[str] = field(default_factory=list)
    jaccard_similarity: float = 1.0
    status: str = "pending"
    error_message: str | None = None


@dataclass
class BenchmarkSummary:
    """Counters for a controlled paired query-profile benchmark."""

    dry_run: bool
    region_id: int
    selected_cells: list[dict[str, Any]]
    results: list[CellBenchmarkResult] = field(default_factory=list)


class ProfileLogCollector:
    """Parse sanitized provider progress logs into benchmark counters."""

    HTTP_PATTERN = re.compile(r"2GIS HTTP status: (\d+)")
    META_PATTERN = re.compile(r"2GIS payload meta\.code: (\d+)")

    def __init__(self, echo: bool = True) -> None:
        self.echo = echo
        self.messages: list[str] = []
        self.http_statuses: Counter[int] = Counter()
        self.meta_codes: Counter[int] = Counter()

    def __call__(self, message: str) -> None:
        self.messages.append(message)

        http = self.HTTP_PATTERN.search(message)
        meta = self.META_PATTERN.search(message)

        if http:
            self.http_statuses[int(http.group(1))] += 1

        if meta:
            self.meta_codes[int(meta.group(1))] += 1

        if self.echo:
            print(message)


class QueryProfileBenchmarkRunner:
    """Run an isolated paired query-profile benchmark on pending cells."""

    def __init__(
        self,
        database: Database,
        *,
        full_profile_name: str = DEFAULT_QUERY_PROFILE,
        reduced_profile_name: str = "reduced_ru_en_v1",
        max_pages_per_query: int = TWOGIS_MAX_PAGES_PER_QUERY,
        dry_run: bool = True,
        classifier: SalonClassifier | None = None,
        search_client_factory: Any | None = None,
    ) -> None:
        if max_pages_per_query <= 0:
            raise ValueError("max_pages_per_query must be positive.")

        self.database = database
        self.full_profile = resolve_query_profile(full_profile_name)
        self.reduced_profile = resolve_query_profile(reduced_profile_name)
        self.max_pages_per_query = max_pages_per_query
        self.dry_run = dry_run
        self.classifier = classifier or SalonClassifier()
        self.search_client_factory = search_client_factory

    def select_cells(
        self,
        *,
        region_id: int,
        target_lat: float,
        target_lon: float,
        limit: int,
        exclude_cell_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Select pending cells closest to a target coordinate."""

        excluded = set(exclude_cell_ids or [])

        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT *
                FROM grid_cells
                WHERE region_id = ?
                  AND status = 'pending'
                """,
                (region_id,),
            ).fetchall()

        selected = [
            {
                **dict(row),
                "distance_m": self._distance_m(
                    target_lat,
                    target_lon,
                    float(row["center_lat"]),
                    float(row["center_lon"]),
                ),
            }
            for row in rows
            if int(row["id"]) not in excluded
        ]
        selected.sort(key=lambda row: (row["distance_m"], row["cell_order"]))
        return selected[:limit]

    def run(
        self,
        *,
        region_id: int,
        cell_ids: list[int],
    ) -> BenchmarkSummary:
        """Run paired profile comparisons for explicit pending cells."""

        selected = self._load_cells(region_id, cell_ids)
        summary = BenchmarkSummary(
            dry_run=self.dry_run,
            region_id=region_id,
            selected_cells=selected,
        )

        if self.dry_run:
            return summary

        for cell in selected:
            result = self._run_cell(region_id=region_id, cell=cell)
            summary.results.append(result)

            if result.status == "failed":
                break

        return summary

    def _run_cell(
        self,
        *,
        region_id: int,
        cell: dict[str, Any],
    ) -> CellBenchmarkResult:
        benchmark_run_id = self.database.create_query_profile_benchmark_run(
            region_id=region_id,
            cell_id=int(cell["id"]),
            full_profile_name=self.full_profile.name,
            reduced_profile_name=self.reduced_profile.name,
            full_query_snapshot=self.full_profile.queries,
            reduced_query_snapshot=self.reduced_profile.queries,
        )
        result = CellBenchmarkResult(
            benchmark_run_id=benchmark_run_id,
            cell_id=int(cell["id"]),
            cell_order=int(cell["cell_order"]),
        )

        try:
            full = self._fetch_profile(cell, self.full_profile)
            reduced = self._fetch_profile(cell, self.reduced_profile)
            self._compare(result, full, reduced)
            self._persist_full_profile(region_id, cell, full)
            self.database.complete_query_profile_benchmark_run(
                benchmark_run_id,
                self._benchmark_metrics(result),
            )
            result.status = "complete"
        except Exception as error:
            result.status = "failed"
            result.error_message = str(error)
            self.database.fail_query_profile_benchmark_run(benchmark_run_id, str(error))

        return result

    def _fetch_profile(
        self,
        cell: dict[str, Any],
        profile: QueryProfile,
    ) -> ProfileFetchResult:
        logger = ProfileLogCollector(echo=True)
        client = self._search_client(logger)
        result = ProfileFetchResult(profile=profile)
        started = time.monotonic()

        for query in profile.queries:
            page = 1

            while page <= self.max_pages_per_query:
                page_result = client.search(
                    query=query,
                    center_lat=float(cell["center_lat"]),
                    center_lon=float(cell["center_lon"]),
                    radius_meters=self._cell_radius_meters(),
                    page=page,
                    grid_cell_id=int(cell["id"]),
                )
                result.request_count += 1
                result.organizations.extend(page_result.organizations)

                for organization in page_result.organizations:
                    if not organization.external_id:
                        continue

                    result.by_external_id[organization.external_id] = (
                        organization,
                        self.classifier.classify(organization),
                    )

                if not page_result.has_next_page:
                    break

                page += 1

        result.duration_seconds = time.monotonic() - started
        result.http_statuses = logger.http_statuses
        result.meta_codes = logger.meta_codes
        return result

    def _persist_full_profile(
        self,
        region_id: int,
        cell: dict[str, Any],
        full: ProfileFetchResult,
    ) -> None:
        claimed = self.database.start_next_grid_cell_scan(
            region_id=region_id,
            retry_limit=SCANNER_CELL_RETRY_LIMIT,
            eligible_cell_ids=[int(cell["id"])],
        )

        if claimed is None:
            raise RuntimeError(f"Benchmark cell {cell['id']} is no longer pending.")

        attempt_id = self.database.create_scan_attempt(
            region_id=region_id,
            grid_cell_id=int(cell["id"]),
            query_profile_name=full.profile.name,
            query_snapshot=full.profile.queries,
        )
        accepted = 0
        rejected = 0
        merged = 0

        try:
            for organization in full.organizations:
                raw_result_id = self.database.save_raw_organization_result(
                    region_id=region_id,
                    organization=organization,
                )
                classification = self.classifier.classify(organization)

                if classification.accepted or organization.external_id:
                    salon_id, was_merged = self.database.upsert_salon(
                        region_id=region_id,
                        organization=organization,
                        classification=classification,
                    )

                    if was_merged:
                        merged += 1
                else:
                    salon_id = None

                if classification.accepted:
                    accepted += 1
                else:
                    rejected += 1

                self.database.save_salon_discovery(
                    region_id=region_id,
                    organization=organization,
                    classification=classification,
                    raw_result_id=raw_result_id,
                    salon_id=salon_id,
                )

            self.database.mark_grid_cell_completed(
                grid_cell_id=int(cell["id"]),
                organizations_found=len(full.organizations),
            )
            self.database.complete_scan_attempt(
                attempt_id=attempt_id,
                raw_organizations_found=len(full.organizations),
                accepted_salons=accepted,
                rejected_results=rejected,
                duplicates_merged=merged,
            )
            self.database.update_region_salon_count(region_id)
        except Exception as error:
            self.database.mark_grid_cell_failed(
                grid_cell_id=int(cell["id"]),
                error=str(error),
                retry_limit=SCANNER_CELL_RETRY_LIMIT,
            )
            self.database.fail_scan_attempt(attempt_id, str(error))
            raise

    def _compare(
        self,
        result: CellBenchmarkResult,
        full: ProfileFetchResult,
        reduced: ProfileFetchResult,
    ) -> None:
        full_ids = set(full.by_external_id)
        reduced_ids = set(reduced.by_external_id)
        missing = sorted(full_ids - reduced_ids)
        extra = sorted(reduced_ids - full_ids)
        union = full_ids | reduced_ids
        intersection = full_ids & reduced_ids

        result.full = full
        result.reduced = reduced
        result.missing_from_reduced = missing
        result.extra_in_reduced = extra
        result.accepted_missing_from_reduced = [
            external_id
            for external_id in missing
            if full.by_external_id[external_id][1].accepted
        ]
        result.rejected_missing_from_reduced = [
            external_id
            for external_id in missing
            if not full.by_external_id[external_id][1].accepted
        ]
        result.jaccard_similarity = (
            1.0 if not union else len(intersection) / len(union)
        )

    def _benchmark_metrics(self, result: CellBenchmarkResult) -> dict[str, Any]:
        assert result.full is not None
        assert result.reduced is not None

        return {
            "full_request_count": result.full.request_count,
            "reduced_request_count": result.reduced.request_count,
            "full_http_statuses_json": self._counter_json(result.full.http_statuses),
            "reduced_http_statuses_json": self._counter_json(result.reduced.http_statuses),
            "full_meta_codes_json": self._counter_json(result.full.meta_codes),
            "reduced_meta_codes_json": self._counter_json(result.reduced.meta_codes),
            "full_external_ids_json": json.dumps(sorted(result.full.by_external_id), ensure_ascii=False),
            "reduced_external_ids_json": json.dumps(sorted(result.reduced.by_external_id), ensure_ascii=False),
            "missing_from_reduced_json": json.dumps(result.missing_from_reduced, ensure_ascii=False),
            "extra_in_reduced_json": json.dumps(result.extra_in_reduced, ensure_ascii=False),
            "accepted_missing_from_reduced_json": json.dumps(result.accepted_missing_from_reduced, ensure_ascii=False),
            "rejected_missing_from_reduced_json": json.dumps(result.rejected_missing_from_reduced, ensure_ascii=False),
            "full_duration_seconds": result.full.duration_seconds,
            "reduced_duration_seconds": result.reduced.duration_seconds,
            "jaccard_similarity": result.jaccard_similarity,
        }

    def _load_cells(self, region_id: int, cell_ids: list[int]) -> list[dict[str, Any]]:
        if not cell_ids:
            return []

        placeholders = ",".join("?" for _ in cell_ids)
        order_cases = " ".join(
            f"WHEN {int(cell_id)} THEN {index}"
            for index, cell_id in enumerate(cell_ids)
        )

        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM grid_cells
                WHERE region_id = ?
                  AND id IN ({placeholders})
                ORDER BY CASE id {order_cases} ELSE {len(cell_ids)} END
                """,
                [region_id, *cell_ids],
            ).fetchall()

        cells = [dict(row) for row in rows]

        if len(cells) != len(cell_ids):
            raise ValueError("One or more benchmark cell IDs were not found.")

        non_pending = [cell for cell in cells if cell["status"] != "pending"]

        if non_pending:
            ids = ", ".join(str(cell["id"]) for cell in non_pending)
            raise ValueError(f"Benchmark cells are not pending: {ids}")

        return cells

    def _search_client(self, logger: ProfileLogCollector) -> OrganizationSearchClient:
        if self.search_client_factory is not None:
            return self.search_client_factory(logger)

        try:
            return TwoGisPlacesClient(progress_logger=logger)
        except MissingTwoGisApiKeyError:
            raise

    def _counter_json(self, counter: Counter[int]) -> str:
        return json.dumps(
            {str(key): counter[key] for key in sorted(counter)},
            ensure_ascii=False,
        )

    def _cell_radius_meters(self) -> int:
        return math.ceil((GRID_SIZE_METERS * math.sqrt(2)) / 2)

    def _distance_m(
        self,
        target_lat: float,
        target_lon: float,
        lat: float,
        lon: float,
    ) -> float:
        d_lat = math.radians(lat - target_lat)
        d_lon = math.radians(lon - target_lon)
        mean_lat = math.radians((lat + target_lat) / 2)
        return math.sqrt(
            (d_lat * 6371008.8) ** 2
            + (d_lon * 6371008.8 * math.cos(mean_lat)) ** 2
        )


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for a paired query-profile benchmark."""

    parser = argparse.ArgumentParser(description="Run a controlled query-profile benchmark.")
    parser.add_argument("--region-id", type=int, required=True)
    parser.add_argument("--cell-ids", required=True)
    parser.add_argument("--full-profile", default="full_v1")
    parser.add_argument("--reduced-profile", default="reduced_ru_en_v1")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--live", action="store_true")
    return parser


def main() -> None:
    """Run a paired query-profile benchmark from the command line."""

    args = build_parser().parse_args()
    dry_run = not args.live or args.dry_run
    cell_ids = [
        int(value.strip())
        for value in args.cell_ids.split(",")
        if value.strip()
    ]
    database = Database()

    if not dry_run:
        database.initialize()

    runner = QueryProfileBenchmarkRunner(
        database,
        full_profile_name=args.full_profile,
        reduced_profile_name=args.reduced_profile,
        dry_run=dry_run,
    )
    summary = runner.run(region_id=args.region_id, cell_ids=cell_ids)

    print(f"Dry-run: {summary.dry_run}")
    print(f"Selected cells: {len(summary.selected_cells)}")

    for result in summary.results:
        print(
            "Benchmark cell "
            f"id={result.cell_id} order={result.cell_order} "
            f"status={result.status} "
            f"missing={len(result.missing_from_reduced)} "
            f"accepted_missing={len(result.accepted_missing_from_reduced)} "
            f"jaccard={result.jaccard_similarity:.3f}"
        )


if __name__ == "__main__":
    main()
