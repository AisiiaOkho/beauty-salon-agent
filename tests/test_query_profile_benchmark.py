from __future__ import annotations

import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from database_manager import Database
from geometry.models import GridCell
from maintenance.canonical_backfill import CanonicalOrganizationBackfiller
from maintenance.query_profile_benchmark import QueryProfileBenchmarkRunner
from providers.twogis_client import TwoGisPlacesClient
from scanner.models import RawOrganization, SearchPage
from scanner.query_profiles import resolve_query_profile
from scanner.salon_scanner import SalonScannerManager


class CapturingTwoGisClient(TwoGisPlacesClient):
    def __init__(self) -> None:
        super().__init__(api_key="test", delay_seconds=0, progress_logger=lambda message: None)
        self.urls: list[str] = []

    def _perform_request(self, url: str) -> dict[str, object]:
        self.urls.append(url)
        return {"meta": {"code": 404}, "result": {"items": [], "total": 0}}


class FakeBenchmarkClient:
    def __init__(self, logger: object, pages: dict[str, list[RawOrganization]], fail_query: str | None = None) -> None:
        self.logger = logger
        self.pages = pages
        self.fail_query = fail_query

    def search(self, *, query: str, center_lat: float, center_lon: float, radius_meters: int, page: int, grid_cell_id: int) -> SearchPage:
        del center_lat, center_lon, radius_meters, page

        if query == self.fail_query:
            raise RuntimeError("provider failure")

        self.logger("2GIS HTTP status: 200")
        self.logger("2GIS payload meta.code: 200")
        organizations = [
            RawOrganization(
                external_source=organization.external_source,
                external_id=organization.external_id,
                name=organization.name,
                address=organization.address,
                latitude=organization.latitude,
                longitude=organization.longitude,
                categories=list(organization.categories),
                raw_payload=dict(organization.raw_payload),
                discovered_query=query,
                discovered_grid_cell_id=grid_cell_id,
            )
            for organization in self.pages.get(query, [])
        ]
        return SearchPage(organizations=organizations, page=1, has_next_page=False)


def org(external_id: str, name: str = "Ногтевая студия") -> RawOrganization:
    return RawOrganization(
        external_source="2GIS",
        external_id=external_id,
        name=name,
        address=f"{external_id} street",
        latitude=54.71,
        longitude=20.45,
        categories=["Ногтевые студии"],
        raw_payload={
            "id": external_id,
            "name": name,
            "address_name": f"{external_id} street",
            "rubrics": [{"name": "Ногтевые студии"}],
            "point": {"lat": 54.71, "lon": 20.45},
        },
    )


class QueryBenchmarkDatabaseMixin:
    def make_database(self, directory: str, cells: int = 1) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        database.insert_grid_cell_batch(
            1,
            [
                GridCell(
                    cell_order=index,
                    north=54.72 + index / 1000,
                    south=54.70 + index / 1000,
                    west=20.44,
                    east=20.46,
                    center_lat=54.71 + index / 1000,
                    center_lon=20.45,
                )
                for index in range(1, cells + 1)
            ],
        )
        return database

    def insert_discovery(
        self,
        database: Database,
        *,
        external_id: str,
        name: str,
        status: str = "rejected",
        rejection_reason: str | None = "mixed_non_salon",
        business_profile: str = "mixed_non_salon",
    ) -> None:
        payload = {
            "id": external_id,
            "name": name,
            "address_name": "Ленина, 1",
            "rubrics": [{"name": "Ногтевые студии"}],
        }
        reason_codes = ["manicure_signal"]

        with database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO raw_organization_results (
                    region_id, grid_cell_id, query, external_source,
                    external_id, name, payload
                )
                VALUES (1, 1, 'маникюр', '2GIS', ?, ?, ?)
                """,
                (external_id, name, json.dumps(payload, ensure_ascii=False)),
            )
            connection.execute(
                """
                INSERT INTO salon_discoveries (
                    raw_result_id, region_id, grid_cell_id, query,
                    external_source, external_id, filter_status,
                    filter_confidence, filter_reasons,
                    classifier_reason_codes, rejection_reason, business_profile
                )
                VALUES (?, 1, 1, 'маникюр', '2GIS', ?, ?, 1.0, ?, ?, ?, ?)
                """,
                (
                    int(cursor.lastrowid),
                    external_id,
                    status,
                    json.dumps(reason_codes, ensure_ascii=False),
                    json.dumps(reason_codes, ensure_ascii=False),
                    rejection_reason,
                    business_profile,
                ),
            )
            connection.commit()


class QueryProfileBenchmarkTests(QueryBenchmarkDatabaseMixin, unittest.TestCase):
    def test_distinct_queries_produce_distinct_request_parameters(self) -> None:
        client = CapturingTwoGisClient()

        client.search(query="маникюр", center_lat=54.71, center_lon=20.45, radius_meters=1000, page=1, grid_cell_id=1)
        client.search(query="nail studio", center_lat=54.71, center_lon=20.45, radius_meters=1000, page=1, grid_cell_id=1)

        parsed = [urllib.parse.parse_qs(urllib.parse.urlparse(url).query) for url in client.urls]
        self.assertEqual(parsed[0]["q"], ["маникюр"])
        self.assertEqual(parsed[1]["q"], ["nail studio"])
        self.assertNotEqual(client.urls[0], client.urls[1])

    def test_source_url_cache_key_equivalent_includes_query_and_space(self) -> None:
        client = CapturingTwoGisClient()
        base = {
            "type": "branch",
            "point": "20.45,54.71",
            "radius": "1000",
            "page": "1",
        }

        first = client._build_source_url({**base, "q": "маникюр", "key": "secret"})
        second = client._build_source_url({**base, "q": "nail studio", "key": "secret"})

        self.assertNotIn("secret", first)
        self.assertNotEqual(first, second)
        self.assertIn("q=", first)

    def test_profile_configuration_default_and_reduced(self) -> None:
        full = resolve_query_profile()
        reduced = resolve_query_profile("reduced_ru_en_v1")

        self.assertEqual(full.name, "full_v1")
        self.assertEqual(len(full.queries), 5)
        self.assertEqual(reduced.queries, ("маникюр", "nail studio"))

    def test_persisted_query_attribution_and_snapshot_match_request_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            scanner = SalonScannerManager(
                database,
                search_client=FakeBenchmarkClient(
                    lambda message: None,
                    {"маникюр": [org("a")]},
                ),
                queries=["маникюр"],
                max_cells_per_run=1,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            scanner.scan_region(database.get_region_progress(1))

            with database.connect() as connection:
                raw = connection.execute("SELECT query FROM raw_organization_results").fetchone()
                discovery = connection.execute("SELECT query FROM salon_discoveries").fetchone()
                attempt = connection.execute("SELECT query_profile_name, query_snapshot_json FROM scan_attempts").fetchone()

            self.assertEqual(raw["query"], "маникюр")
            self.assertEqual(discovery["query"], "маникюр")
            self.assertEqual(attempt["query_profile_name"], "explicit")
            self.assertEqual(json.loads(attempt["query_snapshot_json"]), ["маникюр"])

    def test_benchmark_does_not_duplicate_canonical_salons_or_normal_discoveries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            pages = {
                "маникюр": [org("a")],
                "nail studio": [org("a"), org("b", name="Вторая ногтевая студия")],
            }
            runner = QueryProfileBenchmarkRunner(
                database,
                dry_run=False,
                search_client_factory=lambda logger: FakeBenchmarkClient(logger, pages),
            )

            summary = runner.run(region_id=1, cell_ids=[1])

            self.assertEqual(summary.results[0].status, "complete")
            with database.connect() as connection:
                salons = connection.execute("SELECT COUNT(*) AS total FROM salons").fetchone()
                discoveries = connection.execute("SELECT COUNT(*) AS total FROM salon_discoveries").fetchone()
                attempts = connection.execute("SELECT query_profile_name, query_snapshot_json FROM scan_attempts").fetchone()
                benchmarks = connection.execute(
                    """
                    SELECT COUNT(*) AS total,
                           full_http_statuses_json,
                           reduced_meta_codes_json
                    FROM query_profile_benchmark_runs
                    """
                ).fetchone()

            self.assertEqual(int(salons["total"]), 2)
            self.assertEqual(int(discoveries["total"]), 3)
            self.assertEqual(int(benchmarks["total"]), 1)
            self.assertEqual(json.loads(benchmarks["full_http_statuses_json"]), {"200": 5})
            self.assertEqual(json.loads(benchmarks["reduced_meta_codes_json"]), {"200": 2})
            self.assertEqual(attempts["query_profile_name"], "full_v1")
            self.assertEqual(len(json.loads(attempts["query_snapshot_json"])), 5)

    def test_same_cell_compared_by_two_profiles_and_then_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            pages = {"маникюр": [org("a")], "nail studio": [org("a")]}
            runner = QueryProfileBenchmarkRunner(
                database,
                dry_run=False,
                search_client_factory=lambda logger: FakeBenchmarkClient(logger, pages),
            )

            result = runner.run(region_id=1, cell_ids=[1]).results[0]

            self.assertEqual(result.full.request_count, 5)
            self.assertEqual(result.reduced.request_count, 2)
            self.assertEqual(database.get_grid_cell(1)["status"], "completed")

    def test_benchmark_failure_does_not_mark_cell_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            runner = QueryProfileBenchmarkRunner(
                database,
                dry_run=False,
                search_client_factory=lambda logger: FakeBenchmarkClient(
                    logger,
                    {"маникюр": [org("a")]},
                    fail_query="nail studio",
                ),
            )

            result = runner.run(region_id=1, cell_ids=[1]).results[0]

            self.assertEqual(result.status, "failed")
            self.assertEqual(database.get_grid_cell(1)["status"], "pending")
            with database.connect() as connection:
                rows = connection.execute("SELECT COUNT(*) AS total FROM raw_organization_results").fetchone()
            self.assertEqual(int(rows["total"]), 0)

    def test_reduced_full_set_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            pages = {
                "маникюр": [org("a")],
                "студия маникюра": [org("b")],
                "nail studio": [org("a")],
            }
            runner = QueryProfileBenchmarkRunner(
                database,
                dry_run=False,
                search_client_factory=lambda logger: FakeBenchmarkClient(logger, pages),
            )

            result = runner.run(region_id=1, cell_ids=[1]).results[0]

            self.assertEqual(result.missing_from_reduced, ["b"])
            self.assertEqual(result.accepted_missing_from_reduced, ["b"])
            self.assertAlmostEqual(result.jaccard_similarity, 0.5)

    def test_dry_run_makes_no_network_calls_or_db_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            calls = {"total": 0}

            def factory(logger: object) -> FakeBenchmarkClient:
                calls["total"] += 1
                return FakeBenchmarkClient(logger, {"маникюр": [org("a")]})

            runner = QueryProfileBenchmarkRunner(
                database,
                dry_run=True,
                search_client_factory=factory,
            )

            summary = runner.run(region_id=1, cell_ids=[1])

            self.assertEqual(calls["total"], 0)
            self.assertEqual(summary.results, [])
            with database.connect() as connection:
                benchmarks = connection.execute("SELECT COUNT(*) AS total FROM query_profile_benchmark_runs").fetchone()
            self.assertEqual(int(benchmarks["total"]), 0)

    def test_conflict_report_details(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_discovery(
                database,
                external_id="same",
                name="Beauty, студия красоты",
                status="accepted",
                rejection_reason=None,
                business_profile="mixed_beauty_salon",
            )
            self.insert_discovery(database, external_id="same", name="Beauty, студия красоты")

            summary = CanonicalOrganizationBackfiller(database, dry_run=True).backfill_rejected()

            self.assertEqual(summary.conflicts, 1)
            self.assertEqual(len(summary.changes[0].conflict_decisions), 2)


if __name__ == "__main__":
    unittest.main()
