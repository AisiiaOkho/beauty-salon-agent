from __future__ import annotations

import sqlite3
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from config.settings import GRID_GENERATOR_VERSION
from database_manager import Database
from geometry.models import GridCell
from orchestration.models import AgentConfig
from orchestration.pipeline import AgentPipeline
from run_agent import config_from_args
from scanner.models import ScanSummary


class FakeScanner:
    calls = 0

    def __init__(
        self,
        database: Database,
        max_cells_per_run: int,
        dry_run: bool,
        target_cell_ids: list[int] | None = None,
        progress_logger: object | None = None,
    ) -> None:
        del progress_logger
        self.database = database
        self.max_cells_per_run = max_cells_per_run
        self.dry_run = dry_run
        self.target_cell_ids = target_cell_ids

    def scan_region(self, region: dict[str, object]) -> ScanSummary:
        FakeScanner.calls += 1
        summary = ScanSummary(dry_run=self.dry_run)

        for _ in range(self.max_cells_per_run):
            cell = self.database.start_next_grid_cell_scan(
                int(region["id"]),
                retry_limit=3,
                eligible_cell_ids=self.target_cell_ids,
            )

            if cell is None:
                break

            self.database.mark_grid_cell_completed(int(cell["id"]), 1)
            summary.cells_processed += 1
            summary.raw_organizations_found += 1

        return summary


class FailingScanner(FakeScanner):
    def scan_region(self, region: dict[str, object]) -> ScanSummary:
        del region
        raise RuntimeError("scanner failed")


class InterruptingScanner(FakeScanner):
    def scan_region(self, region: dict[str, object]) -> ScanSummary:
        del region
        raise KeyboardInterrupt()


class OrchestrationDatabaseMixin:
    def make_database(self, directory: str, cell_count: int = 2) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        database.mark_region_in_progress(1)
        database.insert_grid_cell_batch(
            1,
            [
                GridCell(
                    cell_order=index,
                    north=54.72,
                    south=54.70,
                    west=20.44 + index / 1000,
                    east=20.45 + index / 1000,
                    center_lat=54.71,
                    center_lon=20.445 + index / 1000,
                )
                for index in range(1, cell_count + 1)
            ],
        )
        with database.connect() as connection:
            connection.execute(
                """
                INSERT INTO grid_generations (
                    region_id,
                    status,
                    cell_size_meters,
                    expected_cells,
                    persisted_cells,
                    generator_version
                )
                VALUES (1, 'complete', 1500, ?, ?, ?)
                ON CONFLICT(region_id)
                DO UPDATE SET
                    status = 'complete',
                    expected_cells = excluded.expected_cells,
                    persisted_cells = excluded.persisted_cells
                """,
                (cell_count, cell_count, GRID_GENERATOR_VERSION),
            )
            connection.commit()
        return database

    def agent_run_count(self, database: Database) -> int:
        with database.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM agent_runs"
            ).fetchone()

        return int(row["total"])


class AgentPipelineTests(OrchestrationDatabaseMixin, unittest.TestCase):
    def setUp(self) -> None:
        FakeScanner.calls = 0

    def test_dry_run_makes_no_db_writes_or_network_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            before = self.agent_run_count(database)
            config = AgentConfig(dry_run=True, region_id=1)

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                summary = AgentPipeline(database, config).run()

            self.assertEqual(summary.status, "dry_run")
            self.assertEqual(self.agent_run_count(database), before)
            self.assertEqual(FakeScanner.calls, 0)

    def test_existing_grid_reused_and_one_cell_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=2)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                summary = AgentPipeline(database, config).run()

            counts = database.get_region_cell_status_counts(1)
            grid_stage = next(stage for stage in summary.stages if stage.stage == "ensure_grid")
            self.assertFalse(grid_stage.metrics["created"])
            self.assertEqual(summary.cells_attempted, 1)
            self.assertEqual(counts.get("completed"), 1)
            self.assertEqual(counts.get("pending"), 1)

    def test_completed_cell_skipped_and_second_run_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=2)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                first = AgentPipeline(database, config).run()
                second = AgentPipeline(database, config).run()

            counts = database.get_region_cell_status_counts(1)
            self.assertEqual(first.cells_attempted, 1)
            self.assertEqual(second.cells_attempted, 1)
            self.assertEqual(counts.get("completed"), 2)

    def test_target_cell_allowlist_controls_selection_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=4)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                target_cell_ids=[3, 2],
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                AgentPipeline(database, config).run()

            self.assertEqual(database.get_grid_cell(3)["status"], "completed")
            self.assertEqual(database.get_grid_cell(1)["status"], "pending")
            self.assertEqual(database.get_grid_cell(2)["status"], "pending")

    def test_region_not_completed_after_partial_scan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=2)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                AgentPipeline(database, config).run()

            region = database.get_region_progress(1)
            self.assertEqual(region["status"], "in_progress")

    def test_region_completed_only_after_all_cells_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=1)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                AgentPipeline(database, config).run()

            region = database.get_region_progress(1)
            self.assertEqual(region["status"], "completed")

    def test_failed_stage_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=1)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FailingScanner):
                summary = AgentPipeline(database, config).run()

            run = database.get_agent_run(int(summary.run_id))
            self.assertEqual(summary.status, "failed")
            self.assertEqual(run["status"], "failed")
            self.assertEqual(run["error_stage"], "scan_cells")

    def test_rejected_salons_not_enriched(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=0)
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO salons (
                        region_id,
                        external_source,
                        source,
                        external_id,
                        name,
                        filter_status
                    )
                    VALUES (1, '2GIS', '2GIS', 'x', 'Rejected', 'rejected')
                    """
                )
                connection.commit()
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                enable_scanning=False,
                enable_enrichment=True,
                enable_reclassification=False,
            )

            summary = AgentPipeline(database, config).run()

            self.assertEqual(summary.enrichments_attempted, 0)

    def test_pricing_skipped_when_no_source_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=0)
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO salons (
                        region_id,
                        external_source,
                        source,
                        external_id,
                        name,
                        filter_status
                    )
                    VALUES (1, '2GIS', '2GIS', 'a', 'Accepted', 'accepted')
                    """
                )
                connection.commit()
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                enable_scanning=False,
                enable_pricing=True,
                enable_reclassification=False,
            )

            summary = AgentPipeline(database, config).run()
            stage = next(stage for stage in summary.stages if stage.stage == "check_prices")

            self.assertEqual(stage.status, "skipped")
            self.assertEqual(summary.price_checks_attempted, 0)

    def test_export_after_partial_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=2)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
                enable_export=True,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                summary = AgentPipeline(database, config).run()

            self.assertIsNotNone(summary.export_path)
            self.assertTrue(Path(summary.export_path).exists())
            self.assertEqual(database.get_region_progress(1)["status"], "in_progress")

    def test_duplicate_orchestrator_lock_prevented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            acquired = database.acquire_agent_lock("global_agent_orchestrator", "owner", 30)
            config = AgentConfig(dry_run=False, region_id=1, enable_scanning=False)

            summary = AgentPipeline(database, config).run()

            self.assertTrue(acquired)
            self.assertEqual(summary.status, "blocked")

    def test_stale_lock_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO agent_locks (
                        lock_name,
                        owner,
                        acquired_at,
                        expires_at
                    )
                    VALUES ('global_agent_orchestrator', 'stale', '2000-01-01', '2000-01-01')
                    """
                )
                connection.commit()
            config = AgentConfig(dry_run=False, region_id=1, enable_scanning=False)

            summary = AgentPipeline(database, config).run()

            self.assertNotEqual(summary.status, "blocked")

    def test_ctrl_c_interruption_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=1)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", InterruptingScanner):
                summary = AgentPipeline(database, config).run()

            self.assertEqual(summary.status, "paused")
            run = database.get_agent_run(int(summary.run_id))
            self.assertEqual(run["status"], "paused")

    def test_agent_run_metrics_and_configuration_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=1)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                summary = AgentPipeline(database, config).run()

            run = database.get_agent_run(int(summary.run_id))
            self.assertEqual(run["cells_attempted"], 1)
            self.assertIn('"max_cells_per_run": 1', run["configuration_snapshot_json"])

    def test_no_duplication_after_repeated_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory, cell_count=1)
            config = AgentConfig(
                dry_run=False,
                region_id=1,
                max_cells_per_run=1,
                enable_reclassification=False,
            )

            with patch("orchestration.pipeline.SalonScannerManager", FakeScanner):
                AgentPipeline(database, config).run()
                AgentPipeline(database, config).run()

            counts = database.get_region_cell_status_counts(1)
            self.assertEqual(counts.get("completed"), 1)

    def test_legacy_db_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE agent_runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        region_id INTEGER,
                        started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                        status TEXT NOT NULL DEFAULT 'running'
                    )
                    """
                )
            database = Database(db_path=db_path)
            database.create_tables()

            with database.connect() as connection:
                agent_columns = {
                    row["name"]
                    for row in connection.execute("PRAGMA table_info(agent_runs)")
                }
                tables = {
                    row["name"]
                    for row in connection.execute(
                        """
                        SELECT name
                        FROM sqlite_master
                        WHERE type = 'table'
                        """
                    )
                }

            self.assertIn("configuration_snapshot_json", agent_columns)
            self.assertIn("agent_locks", tables)

    def test_cli_live_and_limit_overrides(self) -> None:
        args = Namespace(
            live=True,
            dry_run=False,
            region_id=1,
            max_cells=1,
            max_enrichments=1,
            max_price_checks=1,
            disable_grid=False,
            enable_scanning=True,
            disable_scanning=False,
            enable_reclassification=True,
            disable_reclassification=False,
            enable_enrichment=False,
            disable_enrichment=True,
            enable_pricing=False,
            disable_pricing=True,
            enable_export=False,
            disable_export=True,
            continue_on_stage_error=False,
            cell_ids=None,
        )

        config = config_from_args(args)

        self.assertFalse(config.dry_run)
        self.assertEqual(config.region_id, 1)
        self.assertEqual(config.max_cells_per_run, 1)
        self.assertFalse(config.enable_enrichment)
        self.assertFalse(config.enable_pricing)
        self.assertFalse(config.enable_export)


if __name__ == "__main__":
    unittest.main()
