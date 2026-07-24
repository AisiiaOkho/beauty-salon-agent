from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

from database_manager import Database
from osm.models import BoundaryRecord
from scanner.grid_manager import GridManager


class FakeBoundaryClient:
    def __init__(self, boundary: BoundaryRecord) -> None:
        self.boundary = boundary
        self.calls = 0

    def get_region_boundary(self, region_name: str) -> BoundaryRecord:
        self.calls += 1
        return self.boundary


def make_boundary(cache_path: Path | None = None) -> BoundaryRecord:
    return BoundaryRecord(
        region_name="Калининградская область",
        relation_id=999,
        source_endpoint="fake",
        fetched_at=datetime.now(UTC).isoformat(),
        cache_path=cache_path,
        geometry=MultiPolygon(
            [
                Polygon(
                    [
                        (20.0, 54.0),
                        (20.04, 54.0),
                        (20.04, 54.03),
                        (20.0, 54.03),
                        (20.0, 54.0),
                    ]
                )
            ]
        ),
    )


class GridPersistenceTests(unittest.TestCase):
    def make_database(self, directory: str) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        return database

    def test_repeated_execution_is_idempotent_when_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            fake_client = FakeBoundaryClient(make_boundary())
            manager = GridManager(
                database=database,
                boundary_client=fake_client,  # type: ignore[arg-type]
                batch_size=2,
                progress_logger=lambda message: None,
            )
            region = database.get_region_progress(1)

            first = manager.ensure_grid_for_region(region)
            second = manager.ensure_grid_for_region(region)

            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.cells_count, second.cells_count)
            self.assertEqual(fake_client.calls, 1)

    def test_partial_grid_is_regenerated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            boundary = make_boundary()
            database.start_grid_generation(
                region_id=1,
                cell_size_meters=1500,
                boundary=boundary,
            )
            fake_client = FakeBoundaryClient(boundary)
            manager = GridManager(
                database=database,
                boundary_client=fake_client,  # type: ignore[arg-type]
                batch_size=2,
                progress_logger=lambda message: None,
            )
            region = database.get_region_progress(1)

            result = manager.ensure_grid_for_region(region)
            generation = database.get_grid_generation(1)

            self.assertTrue(result.created)
            self.assertEqual(generation["status"], "complete")
            self.assertEqual(
                database.get_grid_cells_count(1),
                generation["expected_cells"],
            )


if __name__ == "__main__":
    unittest.main()
