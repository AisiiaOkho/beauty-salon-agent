from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from database_manager import Database
from maintenance.reclassify_salons import SalonReclassifier


class ReclassificationDatabaseMixin:
    def make_database(self, directory: str) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        return database

    def insert_salon(
        self,
        database: Database,
        *,
        name: str,
        categories: list[str] | None,
        filter_status: str = "accepted",
        raw_payload: dict[str, object] | None = None,
    ) -> int:
        payload = raw_payload or {
            "id": name,
            "name": name,
            "address_name": "Ленина, 1",
            "rubrics": [
                {"name": category}
                for category in (categories or [])
            ],
        }

        with database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO salons (
                    region_id,
                    external_source,
                    source,
                    external_id,
                    name,
                    categories,
                    raw_payload,
                    filter_status
                )
                VALUES (1, '2GIS', '2GIS', ?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("id") or name),
                    name,
                    json.dumps(categories, ensure_ascii=False)
                    if categories is not None
                    else None,
                    json.dumps(payload, ensure_ascii=False),
                    filter_status,
                ),
            )
            connection.commit()

        return int(cursor.lastrowid)


class SalonReclassifierTests(ReclassificationDatabaseMixin, unittest.TestCase):
    def test_stale_accepted_salon_becomes_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы", "Массажист"],
            )
            reclassifier = SalonReclassifier(database, dry_run=False)

            summary = reclassifier.reclassify()

            self.assertEqual(summary.processed, 1)
            self.assertEqual(summary.changed, 1)
            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT filter_status, rejection_reason, business_profile
                    FROM salons
                    WHERE id = ?
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["filter_status"], "rejected")
            self.assertEqual(row["rejection_reason"], "mixed_non_salon")
            self.assertEqual(row["business_profile"], "mixed_non_salon")

    def test_accepted_salon_remains_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="K-Studio, студия маникюра и педикюра",
                categories=["Ногтевые студии", "Обучение мастеров для салонов красоты"],
            )

            SalonReclassifier(database, dry_run=False).reclassify()

            with database.connect() as connection:
                row = connection.execute(
                    "SELECT filter_status, business_profile FROM salons WHERE id = ?",
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["filter_status"], "accepted")
            self.assertEqual(row["business_profile"], "nail_specialist")

    def test_rejected_salon_excluded_from_enrichment_and_pricing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы"],
            )
            SalonReclassifier(database, dry_run=False).reclassify()

            self.assertIsNone(database.get_salon_for_enrichment_by_id(salon_id))
            self.assertIsNone(database.get_salon_for_pricing_by_id(salon_id))

    def test_dry_run_changes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы"],
            )

            summary = SalonReclassifier(database, dry_run=True).reclassify()

            self.assertEqual(summary.changed, 1)
            self.assertEqual(database.get_classification_audit_count(), 0)
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT filter_status FROM salons WHERE id = ?",
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["filter_status"], "accepted")

    def test_selected_salon_id_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            first = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы"],
            )
            second = self.insert_salon(
                database,
                name="K-Studio, студия маникюра и педикюра",
                categories=["Ногтевые студии"],
            )

            summary = SalonReclassifier(database, dry_run=False).reclassify(
                salon_id=second
            )

            self.assertEqual(summary.processed, 1)
            with database.connect() as connection:
                first_row = connection.execute(
                    "SELECT filter_status FROM salons WHERE id = ?",
                    (first,),
                ).fetchone()
                second_row = connection.execute(
                    "SELECT filter_status FROM salons WHERE id = ?",
                    (second,),
                ).fetchone()

            self.assertEqual(first_row["filter_status"], "accepted")
            self.assertEqual(second_row["filter_status"], "accepted")

    def test_repeated_reclassification_appends_audit_but_current_state_is_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы"],
            )
            reclassifier = SalonReclassifier(database, dry_run=False)

            reclassifier.reclassify()
            reclassifier.reclassify()

            self.assertEqual(database.get_classification_audit_count(), 2)
            with database.connect() as connection:
                row = connection.execute(
                    "SELECT filter_status, rejection_reason FROM salons WHERE id = ?",
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["filter_status"], "rejected")
            self.assertEqual(row["rejection_reason"], "mixed_non_salon")

    def test_missing_preserved_categories_is_unreliable_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_salon(
                database,
                name="Legacy Salon",
                categories=None,
                raw_payload={"id": "legacy", "name": "Legacy Salon"},
            )

            summary = SalonReclassifier(database, dry_run=True).reclassify()

            self.assertEqual(summary.unreliable, 1)
            self.assertEqual(summary.changes[0].issue, "missing_name_or_categories")
            self.assertEqual(summary.changes[0].new_status, "rejected")

    def test_historical_data_is_not_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(
                database,
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы"],
            )
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO organization_detail_results (
                        external_source,
                        external_id,
                        salon_id,
                        status,
                        raw_payload_json,
                        parser_version
                    )
                    VALUES ('2GIS', 'xfit', ?, 'success', '{}', 'test')
                    """,
                    (salon_id,),
                )
                connection.execute(
                    """
                    INSERT INTO price_check_results (
                        salon_id,
                        status,
                        raw_evidence_json,
                        parser_version
                    )
                    VALUES (?, 'not_found', '{}', 'test')
                    """,
                    (salon_id,),
                )
                connection.commit()

            SalonReclassifier(database, dry_run=False).reclassify()

            with database.connect() as connection:
                details = connection.execute(
                    "SELECT COUNT(*) AS total FROM organization_detail_results"
                ).fetchone()
                prices = connection.execute(
                    "SELECT COUNT(*) AS total FROM price_check_results"
                ).fetchone()

            self.assertEqual(int(details["total"]), 1)
            self.assertEqual(int(prices["total"]), 1)

    def test_legacy_row_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = Path(directory) / "legacy.db"

            with __import__("sqlite3").connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE salons (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        region_id INTEGER NOT NULL,
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

            self.assertIn("classifier_version", columns)
            self.assertIn("classified_at", columns)
            self.assertIn("salon_classification_results", tables)


if __name__ == "__main__":
    unittest.main()
