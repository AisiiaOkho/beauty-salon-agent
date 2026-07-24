from __future__ import annotations

import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from database_manager import Database
from geometry.models import GridCell
from providers.twogis_client import TwoGisPlacesClient
from scanner.models import RawOrganization, SearchPage
from scanner.salon_scanner import SalonScannerManager


class FakeSearchClient:
    def __init__(self, pages: dict[tuple[str, int], SearchPage]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, int]] = []

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
        self.calls.append((query, page))
        configured = self.pages.get((query, page))

        if configured is None:
            return SearchPage(organizations=[], page=page, has_next_page=False)

        organizations = [
            RawOrganization(
                external_source=organization.external_source,
                external_id=organization.external_id,
                name=organization.name,
                address=organization.address,
                latitude=organization.latitude,
                longitude=organization.longitude,
                phone=organization.phone,
                website=organization.website,
                social_links=organization.social_links,
                categories=organization.categories,
                description=organization.description,
                working_hours=organization.working_hours,
                branch_info=organization.branch_info,
                raw_payload=organization.raw_payload,
                source_url=organization.source_url,
                discovered_query=query,
                discovered_grid_cell_id=grid_cell_id,
                fetched_at=organization.fetched_at,
            )
            for organization in configured.organizations
        ]

        return SearchPage(
            organizations=organizations,
            page=configured.page,
            has_next_page=configured.has_next_page,
        )


class ScannerDatabaseMixin:
    def make_database(self, directory: str) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        database.insert_grid_cell_batch(
            1,
            [
                GridCell(
                    cell_order=1,
                    north=54.72,
                    south=54.70,
                    west=20.49,
                    east=20.51,
                    center_lat=54.71,
                    center_lon=20.50,
                ),
                GridCell(
                    cell_order=2,
                    north=54.73,
                    south=54.71,
                    west=20.50,
                    east=20.52,
                    center_lat=54.72,
                    center_lon=20.51,
                ),
            ],
        )
        return database


def accepted_org(
    external_id: str | None = "org-1",
    name: str = "Ногтевая студия Лак",
    address: str = "Ленина, 1",
    phone: str = "+7 4012 11-22-33",
) -> RawOrganization:
    return RawOrganization(
        external_source="2GIS",
        external_id=external_id,
        name=name,
        address=address,
        latitude=54.71,
        longitude=20.50,
        phone=phone,
        categories=["Маникюр", "Салоны красоты"],
        description="Маникюр и педикюр",
        raw_payload={"id": external_id, "name": name},
    )


class SalonScannerTests(ScannerDatabaseMixin, unittest.TestCase):
    def test_pagination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            query = "маникюр"
            client = FakeSearchClient(
                {
                    (query, 1): SearchPage(
                        organizations=[accepted_org("1")],
                        page=1,
                        has_next_page=True,
                    ),
                    (query, 2): SearchPage(
                        organizations=[accepted_org("2", name="Студия маникюра Два")],
                        page=2,
                        has_next_page=False,
                    ),
                }
            )
            scanner = SalonScannerManager(
                database,
                search_client=client,
                max_cells_per_run=1,
                max_pages_per_query=2,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = scanner.scan_region(database.get_region_progress(1))

            self.assertEqual(summary.raw_organizations_found, 2)
            self.assertIn((query, 1), client.calls)
            self.assertIn((query, 2), client.calls)

    def test_deduplication_by_external_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            query = "маникюр"
            client = FakeSearchClient(
                {
                    (query, 1): SearchPage(
                        organizations=[
                            accepted_org("same"),
                            accepted_org("same", name="Ногтевая студия Лак филиал"),
                        ],
                        page=1,
                        has_next_page=False,
                    )
                }
            )
            scanner = SalonScannerManager(
                database,
                search_client=client,
                max_cells_per_run=1,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = scanner.scan_region(database.get_region_progress(1))

            self.assertEqual(summary.duplicates_merged, 1)
            self.assertEqual(self._salons_count(database), 1)

    def test_fallback_deduplication(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            query = "маникюр"
            client = FakeSearchClient(
                {
                    (query, 1): SearchPage(
                        organizations=[
                            accepted_org(None),
                            accepted_org(None),
                        ],
                        page=1,
                        has_next_page=False,
                    )
                }
            )
            scanner = SalonScannerManager(
                database,
                search_client=client,
                max_cells_per_run=1,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = scanner.scan_region(database.get_region_progress(1))

            self.assertEqual(summary.duplicates_merged, 1)
            self.assertEqual(self._salons_count(database), 1)

    def test_same_salon_found_in_multiple_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            query = "маникюр"
            client = FakeSearchClient(
                {
                    (query, 1): SearchPage(
                        organizations=[accepted_org("same")],
                        page=1,
                        has_next_page=False,
                    )
                }
            )
            scanner = SalonScannerManager(
                database,
                search_client=client,
                max_cells_per_run=2,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = scanner.scan_region(database.get_region_progress(1))

            self.assertEqual(summary.cells_processed, 2)
            self.assertEqual(self._salons_count(database), 1)
            self.assertEqual(self._discoveries_count(database), 2)

    def test_interrupted_cell_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            cell = database.start_next_grid_cell_scan(1, retry_limit=3)

            self.assertEqual(cell["status"], "in_progress")

            scanner = SalonScannerManager(
                database,
                search_client=FakeSearchClient({}),
                dry_run=False,
                max_cells_per_run=1,
                progress_logger=lambda message: None,
            )
            summary = scanner.scan_region(database.get_region_progress(1))
            recovered_cell = database.get_grid_cell(int(cell["id"]))

            self.assertEqual(summary.cells_processed, 1)
            self.assertEqual(recovered_cell["status"], "completed")

    def test_db_migration_safety(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"

            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE salons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        region_id INTEGER NOT NULL,
                        grid_cell_id INTEGER,
                        external_id TEXT,
                        source TEXT NOT NULL DEFAULT '2GIS',
                        name TEXT NOT NULL
                    )
                    """
                )

            database = Database(db_path=db_path)
            database.create_tables()

            with database.connect() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(salons)")
                }

            self.assertIn("external_source", columns)
            self.assertIn("normalized_name", columns)
            self.assertIn("raw_payload", columns)

    def _salons_count(self, database: Database) -> int:
        with database.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS total FROM salons").fetchone()

        return int(row["total"])

    def _discoveries_count(self, database: Database) -> int:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM salon_discoveries"
            ).fetchone()

        return int(row["total"])


class RetryTwoGisClient(TwoGisPlacesClient):
    def __init__(self) -> None:
        super().__init__(
            api_key="test",
            max_retries=2,
            backoff_seconds=0,
            delay_seconds=0,
            progress_logger=lambda message: None,
        )
        self.calls = 0

    def _perform_request(self, url: str) -> dict[str, object]:
        self.calls += 1

        if self.calls == 1:
            raise urllib.error.HTTPError(
                url=url,
                code=503,
                msg="busy",
                hdrs={},
                fp=None,
            )

        return {"result": {"items": [], "total": 0}}


class TwoGisClientTests(unittest.TestCase):
    def test_retry_behavior(self) -> None:
        client = RetryTwoGisClient()

        page = client.search(
            query="маникюр",
            center_lat=54.71,
            center_lon=20.50,
            radius_meters=1100,
            page=1,
            grid_cell_id=1,
        )

        self.assertEqual(page.organizations, [])
        self.assertEqual(client.calls, 2)


if __name__ == "__main__":
    unittest.main()
