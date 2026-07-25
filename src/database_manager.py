import sqlite3
import sys
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.regions import REGIONS
from config.settings import (
    DETAIL_PARSER_VERSION,
    GRID_GENERATOR_VERSION,
    SALON_CLASSIFIER_VERSION,
)
from enrichment.models import ContactValue, OrganizationDetails, OrganizationDetailsResult
from geometry.models import GridCell
from osm.models import BoundaryRecord
from pricing.models import (
    SERVICE_KEY_BASIC_MANICURE_WITH_COATING,
    PriceExtractionResult,
)
from scanner.models import ClassificationResult, RawOrganization
from utils.normalization import coordinate_key, normalize_phone, normalize_text


class ClosingConnection(sqlite3.Connection):
    """SQLite connection that closes when used as a context manager."""

    def __exit__(
        self,
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> bool:
        super().__exit__(exc_type, exc_value, traceback)
        self.close()
        return False


class Database:
    """
    Управляет SQLite-базой Beauty Salon Agent.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.project_root = PROJECT_ROOT
        self.db_path = db_path or self.project_root / "data" / "beauty_agent.db"
        self.data_directory = self.db_path.parent

        self.data_directory.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.db_path,
            factory=ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    def create_tables(self) -> None:
        with self.connect() as connection:
            cursor = connection.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scan_order INTEGER NOT NULL UNIQUE,
                    name TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'pending',
                    started_at TEXT,
                    completed_at TEXT,
                    total_cells INTEGER NOT NULL DEFAULT 0,
                    completed_cells INTEGER NOT NULL DEFAULT 0,
                    salons_found INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    comment TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS grid_cells (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL,
                    cell_order INTEGER NOT NULL,

                    north REAL NOT NULL,
                    south REAL NOT NULL,
                    west REAL NOT NULL,
                    east REAL NOT NULL,

                    center_lat REAL NOT NULL,
                    center_lon REAL NOT NULL,

                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    organizations_found INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE,

                    UNIQUE(region_id, cell_order)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS salons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL,
                    grid_cell_id INTEGER,

                    external_id TEXT,
                    source TEXT NOT NULL DEFAULT '2GIS',

                    city TEXT,
                    name TEXT NOT NULL,
                    salon_type TEXT,
                    address TEXT,

                    latitude REAL,
                    longitude REAL,

                    phone TEXT,
                    website TEXT,
                    social_links TEXT,
                    map_url TEXT,

                    manicure_confirmed INTEGER NOT NULL DEFAULT 0,
                    service_name TEXT,
                    service_price TEXT,
                    price_min INTEGER,
                    price_max INTEGER,
                    price_source TEXT,
                    price_source_url TEXT,

                    masters_count TEXT,
                    verification_status TEXT NOT NULL DEFAULT 'not_checked',
                    comment TEXT,

                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (grid_cell_id)
                        REFERENCES grid_cells(id)
                        ON DELETE SET NULL
                )
            """)

            self._add_column_if_missing(
                cursor,
                "salons",
                "grid_cell_id",
                "INTEGER",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "external_id",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "source",
                "TEXT NOT NULL DEFAULT '2GIS'",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "external_source",
                "TEXT NOT NULL DEFAULT '2GIS'",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "normalized_name",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "normalized_address",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "address",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "latitude",
                "REAL",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "longitude",
                "REAL",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "phone",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "website",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "social_links",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "categories",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "description",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "salon_type",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "filter_status",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "filter_confidence",
                "REAL",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "filter_reasons",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "classifier_reason_codes",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "rejection_reason",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "business_profile",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "classifier_decision_name",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "classifier_decision_categories",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "raw_payload",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "source_url",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "manicure_confirmed",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "verification_status",
                "TEXT NOT NULL DEFAULT 'not_checked'",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "first_seen_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "last_seen_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "updated_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "details_enriched_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "details_status",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "details_error",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "provider_updated_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "organization_id",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "branch_id",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "classifier_version",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salons",
                "classified_at",
                "TEXT",
            )

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_salons_source_external_id
                ON salons(source, external_id)
                WHERE external_id IS NOT NULL
            """)

            cursor.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                idx_salons_external_source_external_id
                ON salons(external_source, external_id)
                WHERE external_id IS NOT NULL
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    cells_processed INTEGER NOT NULL DEFAULT 0,
                    salons_added INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    report TEXT,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE SET NULL
                )
            """)
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "finished_at",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "current_stage",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "dry_run",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "configuration_snapshot_json",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "cells_attempted",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "cells_completed",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "cells_failed",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "organizations_observed",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "salons_created",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "salons_updated",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "salons_accepted",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "salons_rejected",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "enrichments_attempted",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "enrichments_succeeded",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "price_checks_attempted",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "prices_found",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "export_path",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "error_stage",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "error_message",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "agent_runs",
                "resume_token",
                "TEXT",
            )

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS agent_locks (
                    lock_name TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    acquired_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS grid_generations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    cell_size_meters INTEGER NOT NULL,
                    expected_cells INTEGER NOT NULL DEFAULT 0,
                    persisted_cells INTEGER NOT NULL DEFAULT 0,
                    boundary_relation_id INTEGER,
                    boundary_cache_path TEXT,
                    boundary_fetched_at TEXT,
                    generated_at TEXT,
                    generator_version TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS raw_organization_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL,
                    grid_cell_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    external_source TEXT NOT NULL,
                    external_id TEXT,
                    name TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (grid_cell_id)
                        REFERENCES grid_cells(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS salon_discoveries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    salon_id INTEGER,
                    raw_result_id INTEGER,
                    region_id INTEGER NOT NULL,
                    grid_cell_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    external_source TEXT NOT NULL,
                    external_id TEXT,
                    filter_status TEXT NOT NULL,
                    filter_confidence REAL NOT NULL,
                    filter_reasons TEXT NOT NULL,
                    discovered_at TEXT DEFAULT CURRENT_TIMESTAMP,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE SET NULL,

                    FOREIGN KEY (raw_result_id)
                        REFERENCES raw_organization_results(id)
                        ON DELETE SET NULL,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (grid_cell_id)
                        REFERENCES grid_cells(id)
                        ON DELETE CASCADE
                )
            """)
            self._add_column_if_missing(
                cursor,
                "salon_discoveries",
                "classifier_reason_codes",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salon_discoveries",
                "rejection_reason",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salon_discoveries",
                "business_profile",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salon_discoveries",
                "classifier_decision_name",
                "TEXT",
            )
            self._add_column_if_missing(
                cursor,
                "salon_discoveries",
                "classifier_decision_categories",
                "TEXT",
            )

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS scan_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    region_id INTEGER NOT NULL,
                    grid_cell_id INTEGER NOT NULL,
                    started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running',
                    raw_organizations_found INTEGER NOT NULL DEFAULT 0,
                    accepted_salons INTEGER NOT NULL DEFAULT 0,
                    rejected_results INTEGER NOT NULL DEFAULT 0,
                    duplicates_merged INTEGER NOT NULL DEFAULT 0,
                    error TEXT,

                    FOREIGN KEY (region_id)
                        REFERENCES regions(id)
                        ON DELETE CASCADE,

                    FOREIGN KEY (grid_cell_id)
                        REFERENCES grid_cells(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS organization_detail_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    external_source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    salon_id INTEGER,
                    fetched_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    http_status INTEGER,
                    payload_code INTEGER,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    sanitized_source_url TEXT,
                    raw_payload_json TEXT NOT NULL,
                    parser_version TEXT NOT NULL,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE SET NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS salon_contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    salon_id INTEGER NOT NULL,
                    contact_type TEXT NOT NULL,
                    display_value TEXT NOT NULL,
                    normalized_value TEXT NOT NULL,
                    source TEXT NOT NULL,
                    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    metadata_json TEXT,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        salon_id,
                        contact_type,
                        normalized_value,
                        source
                    )
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS price_check_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    salon_id INTEGER NOT NULL,
                    checked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    status TEXT NOT NULL,
                    source_type TEXT,
                    sanitized_source_url TEXT,
                    raw_evidence_json TEXT NOT NULL,
                    error_message TEXT,
                    parser_version TEXT NOT NULL,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS salon_prices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    salon_id INTEGER NOT NULL,
                    service_key TEXT NOT NULL,
                    service_name_raw TEXT,
                    service_name_normalized TEXT,
                    amount_minor INTEGER,
                    currency TEXT,
                    price_type TEXT NOT NULL,
                    range_min_minor INTEGER,
                    range_max_minor INTEGER,
                    source_type TEXT,
                    source_url TEXT,
                    evidence_text TEXT,
                    confidence TEXT NOT NULL,
                    first_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    last_seen_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER NOT NULL DEFAULT 1,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE CASCADE,

                    UNIQUE (
                        salon_id,
                        service_key,
                        source_type,
                        evidence_text
                    )
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS salon_classification_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    salon_id INTEGER NOT NULL,
                    classified_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    classifier_version TEXT NOT NULL,
                    accepted INTEGER NOT NULL,
                    business_profile TEXT,
                    reason_codes_json TEXT NOT NULL,
                    rejection_reason TEXT,
                    input_snapshot_json TEXT NOT NULL,

                    FOREIGN KEY (salon_id)
                        REFERENCES salons(id)
                        ON DELETE CASCADE
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_grid_cells_region_status_order
                ON grid_cells(region_id, status, cell_order)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_grid_cells_region_id
                ON grid_cells(region_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salons_region_id
                ON salons(region_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salons_grid_cell_id
                ON salons(grid_cell_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salons_normalized_name_address
                ON salons(normalized_name, normalized_address)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salons_phone
                ON salons(phone)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_raw_results_cell_query
                ON raw_organization_results(grid_cell_id, query)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_discoveries_salon_id
                ON salon_discoveries(salon_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_scan_attempts_cell_status
                ON scan_attempts(grid_cell_id, status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_detail_results_source_external
                ON organization_detail_results(external_source, external_id)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_detail_results_salon_status
                ON organization_detail_results(salon_id, status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salon_contacts_salon_type_active
                ON salon_contacts(salon_id, contact_type, is_active)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salon_contacts_normalized
                ON salon_contacts(contact_type, normalized_value)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_price_check_results_salon_status
                ON price_check_results(salon_id, status)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_salon_prices_salon_service_active
                ON salon_prices(salon_id, service_key, is_active)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS
                idx_classification_results_salon_version
                ON salon_classification_results(salon_id, classifier_version)
            """)

            connection.commit()

    def _add_column_if_missing(
        self,
        cursor: sqlite3.Cursor,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        columns = cursor.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()

        if column_name in {column["name"] for column in columns}:
            return

        cursor.execute(
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN {column_name} {column_definition}"
        )

    def sync_regions(self) -> None:
        """
        Загружает все регионы и обновляет их порядок.

        Существующие статусы и результаты обработки не удаляются.
        """

        with self.connect() as connection:
            cursor = connection.cursor()

            # Временно освобождаем положительные значения scan_order,
            # чтобы обновление порядка не столкнулось с UNIQUE.
            cursor.execute("""
                UPDATE regions
                SET scan_order = -id
            """)

            for scan_order, name in REGIONS:
                existing_region = cursor.execute(
                    """
                    SELECT id
                    FROM regions
                    WHERE name = ?
                    """,
                    (name,),
                ).fetchone()

                if existing_region:
                    cursor.execute(
                        """
                        UPDATE regions
                        SET scan_order = ?
                        WHERE id = ?
                        """,
                        (scan_order, existing_region["id"]),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO regions (
                            scan_order,
                            name,
                            status
                        )
                        VALUES (?, ?, 'pending')
                        """,
                        (scan_order, name),
                    )

            connection.commit()

        print(f"✅ Регионы синхронизированы: {len(REGIONS)}.")

    def get_regions_count(self) -> int:
        with self.connect() as connection:
            row = connection.execute("""
                SELECT COUNT(*) AS total
                FROM regions
            """).fetchone()

        return int(row["total"])

    def get_next_region(self) -> dict[str, Any] | None:
        """
        Возвращает регион, который нужно обрабатывать следующим.

        Приоритет:
        1. Регион со статусом in_progress.
        2. Первый регион со статусом pending.
        """

        with self.connect() as connection:
            row = connection.execute("""
                SELECT *
                FROM regions
                WHERE status IN ('in_progress', 'pending')
                ORDER BY
                    CASE
                        WHEN status = 'in_progress' THEN 0
                        ELSE 1
                    END,
                    scan_order
                LIMIT 1
            """).fetchone()

        if row is None:
            return None

        return dict(row)

    def mark_region_in_progress(self, region_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE regions
                SET
                    status = 'in_progress',
                    started_at = COALESCE(
                        started_at,
                        CURRENT_TIMESTAMP
                    )
                WHERE id = ?
                """,
                (region_id,),
            )

            connection.commit()

    def mark_region_completed(
        self,
        region_id: int,
        comment: str | None = None,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE regions
                SET
                    status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    comment = COALESCE(?, comment)
                WHERE id = ?
                """,
                (comment, region_id),
            )

            connection.commit()

    def get_region_progress(self, region_id: int) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    id,
                    scan_order,
                    name,
                    status,
                    started_at,
                    completed_at,
                    total_cells,
                    completed_cells,
                    salons_found,
                    errors_count,
                    comment
                FROM regions
                WHERE id = ?
                """,
                (region_id,),
            ).fetchone()

        if row is None:
            raise ValueError(
                f"Регион с ID {region_id} не найден."
            )

        return dict(row)

    def get_grid_cells_count(self, region_id: int) -> int:
        """
        Возвращает количество grid cells для региона.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                """,
                (region_id,),
            ).fetchone()

        return int(row["total"])

    def get_grid_generation(
        self,
        region_id: int,
    ) -> dict[str, Any] | None:
        """
        Возвращает metadata последней генерации сетки региона.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM grid_generations
                WHERE region_id = ?
                """,
                (region_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def start_grid_generation(
        self,
        region_id: int,
        cell_size_meters: int,
        boundary: BoundaryRecord,
        generator_version: str = GRID_GENERATOR_VERSION,
    ) -> None:
        """
        Начинает регенерацию сетки и очищает неполные cells региона.
        """

        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM grid_cells
                WHERE region_id = ?
                """,
                (region_id,),
            )
            connection.execute(
                """
                INSERT INTO grid_generations (
                    region_id,
                    status,
                    cell_size_meters,
                    expected_cells,
                    persisted_cells,
                    boundary_relation_id,
                    boundary_cache_path,
                    boundary_fetched_at,
                    generator_version,
                    error,
                    updated_at
                )
                VALUES (?, 'generating', ?, 0, 0, ?, ?, ?, ?, NULL,
                        CURRENT_TIMESTAMP)
                ON CONFLICT(region_id)
                DO UPDATE SET
                    status = 'generating',
                    cell_size_meters = excluded.cell_size_meters,
                    expected_cells = 0,
                    persisted_cells = 0,
                    boundary_relation_id = excluded.boundary_relation_id,
                    boundary_cache_path = excluded.boundary_cache_path,
                    boundary_fetched_at = excluded.boundary_fetched_at,
                    generated_at = NULL,
                    generator_version = excluded.generator_version,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    region_id,
                    cell_size_meters,
                    boundary.relation_id,
                    str(boundary.cache_path) if boundary.cache_path else None,
                    boundary.fetched_at,
                    generator_version,
                ),
            )
            connection.execute(
                """
                UPDATE regions
                SET total_cells = 0
                WHERE id = ?
                """,
                (region_id,),
            )
            connection.commit()

    def insert_grid_cell_batch(
        self,
        region_id: int,
        cells: list[GridCell],
    ) -> int:
        """
        Сохраняет batch cells и обновляет persisted_cells.
        """

        if not cells:
            return self.get_grid_cells_count(region_id)

        with self.connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO grid_cells (
                    region_id,
                    cell_order,
                    north,
                    south,
                    west,
                    east,
                    center_lat,
                    center_lon,
                    status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        region_id,
                        cell.cell_order,
                        cell.north,
                        cell.south,
                        cell.west,
                        cell.east,
                        cell.center_lat,
                        cell.center_lon,
                        cell.status,
                    )
                    for cell in cells
                ],
            )
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                """,
                (region_id,),
            ).fetchone()
            persisted_cells = int(row["total"])
            connection.execute(
                """
                UPDATE grid_generations
                SET
                    persisted_cells = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE region_id = ?
                """,
                (persisted_cells, region_id),
            )
            connection.commit()

        return persisted_cells

    def complete_grid_generation(
        self,
        region_id: int,
        expected_cells: int,
    ) -> None:
        """
        Помечает генерацию сетки завершенной, если counts совпадают.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                """,
                (region_id,),
            ).fetchone()
            persisted_cells = int(row["total"])

            if persisted_cells != expected_cells:
                raise ValueError(
                    "Cannot complete grid generation: expected "
                    f"{expected_cells}, persisted {persisted_cells}."
                )

            connection.execute(
                """
                UPDATE grid_generations
                SET
                    status = 'complete',
                    expected_cells = ?,
                    persisted_cells = ?,
                    generated_at = CURRENT_TIMESTAMP,
                    error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE region_id = ?
                """,
                (expected_cells, persisted_cells, region_id),
            )
            connection.execute(
                """
                UPDATE regions
                SET total_cells = ?
                WHERE id = ?
                """,
                (persisted_cells, region_id),
            )
            connection.commit()

    def fail_grid_generation(
        self,
        region_id: int,
        error: str,
    ) -> None:
        """
        Сохраняет ошибку генерации сетки.
        """

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                """,
                (region_id,),
            ).fetchone()
            persisted_cells = int(row["total"])
            connection.execute(
                """
                UPDATE grid_generations
                SET
                    status = 'failed',
                    persisted_cells = ?,
                    error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE region_id = ?
                """,
                (persisted_cells, error, region_id),
            )
            connection.commit()

    def recover_interrupted_grid_cells(
        self,
        region_id: int,
        retry_limit: int,
    ) -> int:
        """Reset interrupted in_progress cells if they can still be retried."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE grid_cells
                SET
                    status = 'pending',
                    updated_at = CURRENT_TIMESTAMP
                WHERE region_id = ?
                  AND status = 'in_progress'
                  AND attempts < ?
                """,
                (region_id, retry_limit),
            )
            connection.commit()

        return cursor.rowcount

    def start_next_grid_cell_scan(
        self,
        region_id: int,
        retry_limit: int,
    ) -> dict[str, Any] | None:
        """Select and mark the next pending/retryable grid cell in progress."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM grid_cells
                WHERE region_id = ?
                  AND status = 'pending'
                  AND attempts < ?
                ORDER BY cell_order
                LIMIT 1
                """,
                (region_id, retry_limit),
            ).fetchone()

            if row is None:
                return None

            connection.execute(
                """
                UPDATE grid_cells
                SET
                    status = 'in_progress',
                    attempts = attempts + 1,
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (row["id"],),
            )
            connection.commit()

        return self.get_grid_cell(int(row["id"]))

    def get_grid_cell(self, grid_cell_id: int) -> dict[str, Any]:
        """Return one grid cell by id."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM grid_cells
                WHERE id = ?
                """,
                (grid_cell_id,),
            ).fetchone()

        if row is None:
            raise ValueError(f"Grid cell with ID {grid_cell_id} not found.")

        return dict(row)

    def mark_grid_cell_completed(
        self,
        grid_cell_id: int,
        organizations_found: int,
    ) -> None:
        """Mark a grid cell as completely scanned."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT region_id
                FROM grid_cells
                WHERE id = ?
                """,
                (grid_cell_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Grid cell with ID {grid_cell_id} not found.")

            region_id = int(row["region_id"])
            connection.execute(
                """
                UPDATE grid_cells
                SET
                    status = 'completed',
                    organizations_found = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (organizations_found, grid_cell_id),
            )
            progress = connection.execute(
                """
                SELECT COUNT(*) AS completed_cells
                FROM grid_cells
                WHERE region_id = ?
                  AND status = 'completed'
                """,
                (region_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE regions
                SET completed_cells = ?
                WHERE id = ?
                """,
                (int(progress["completed_cells"]), region_id),
            )
            connection.commit()

    def mark_grid_cell_failed(
        self,
        grid_cell_id: int,
        error: str,
        retry_limit: int,
    ) -> None:
        """Store a cell scan error and schedule retry when possible."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT attempts
                FROM grid_cells
                WHERE id = ?
                """,
                (grid_cell_id,),
            ).fetchone()

            if row is None:
                raise ValueError(f"Grid cell with ID {grid_cell_id} not found.")

            next_status = (
                "pending"
                if int(row["attempts"]) < retry_limit
                else "failed"
            )
            connection.execute(
                """
                UPDATE grid_cells
                SET
                    status = ?,
                    last_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (next_status, error, grid_cell_id),
            )
            connection.commit()

    def create_scan_attempt(
        self,
        region_id: int,
        grid_cell_id: int,
    ) -> int:
        """Create a scan attempt record for one grid cell."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO scan_attempts (
                    region_id,
                    grid_cell_id,
                    status
                )
                VALUES (?, ?, 'running')
                """,
                (region_id, grid_cell_id),
            )
            attempt_id = int(cursor.lastrowid)
            connection.commit()

        return attempt_id

    def complete_scan_attempt(
        self,
        attempt_id: int,
        raw_organizations_found: int,
        accepted_salons: int,
        rejected_results: int,
        duplicates_merged: int,
    ) -> None:
        """Mark a scan attempt as completed."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE scan_attempts
                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = 'complete',
                    raw_organizations_found = ?,
                    accepted_salons = ?,
                    rejected_results = ?,
                    duplicates_merged = ?
                WHERE id = ?
                """,
                (
                    raw_organizations_found,
                    accepted_salons,
                    rejected_results,
                    duplicates_merged,
                    attempt_id,
                ),
            )
            connection.commit()

    def fail_scan_attempt(self, attempt_id: int, error: str) -> None:
        """Mark a scan attempt as failed."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE scan_attempts
                SET
                    completed_at = CURRENT_TIMESTAMP,
                    status = 'failed',
                    error = ?
                WHERE id = ?
                """,
                (error, attempt_id),
            )
            connection.commit()

    def save_raw_organization_result(
        self,
        region_id: int,
        organization: RawOrganization,
    ) -> int:
        """Persist raw provider payload before filtering."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO raw_organization_results (
                    region_id,
                    grid_cell_id,
                    query,
                    external_source,
                    external_id,
                    name,
                    payload,
                    fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP))
                """,
                (
                    region_id,
                    organization.discovered_grid_cell_id,
                    organization.discovered_query or "",
                    organization.external_source,
                    organization.external_id,
                    organization.name,
                    json.dumps(organization.raw_payload, ensure_ascii=False),
                    organization.fetched_at,
                ),
            )
            raw_result_id = int(cursor.lastrowid)
            connection.commit()

        return raw_result_id

    def upsert_salon(
        self,
        region_id: int,
        organization: RawOrganization,
        classification: ClassificationResult,
    ) -> tuple[int, bool]:
        """
        Insert or merge an accepted salon.

        Returns (salon_id, merged_existing).
        """

        normalized_name = normalize_text(organization.name)
        normalized_address = normalize_text(organization.address)
        normalized_phone = normalize_phone(organization.phone)
        existing_id = self._find_existing_salon_id(
            region_id=region_id,
            external_source=organization.external_source,
            external_id=organization.external_id,
            normalized_name=normalized_name,
            normalized_address=normalized_address,
            normalized_phone=normalized_phone,
            latitude=organization.latitude,
            longitude=organization.longitude,
        )
        payload = self._salon_payload(
            region_id=region_id,
            organization=organization,
            classification=classification,
            normalized_name=normalized_name,
            normalized_address=normalized_address,
            normalized_phone=normalized_phone,
        )

        if existing_id is not None:
            self._update_salon(existing_id, payload)
            return existing_id, True

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO salons (
                    region_id,
                    grid_cell_id,
                    external_id,
                    source,
                    external_source,
                    name,
                    normalized_name,
                    address,
                    normalized_address,
                    latitude,
                    longitude,
                    phone,
                    website,
                    social_links,
                    categories,
                    description,
                    salon_type,
                    filter_status,
                    filter_confidence,
                    filter_reasons,
                    classifier_reason_codes,
                    rejection_reason,
                    business_profile,
                    classifier_decision_name,
                    classifier_decision_categories,
                    manicure_confirmed,
                    verification_status,
                    raw_payload,
                    source_url,
                    first_seen_at,
                    last_seen_at,
                    updated_at
                )
                VALUES (
                    :region_id,
                    :grid_cell_id,
                    :external_id,
                    :source,
                    :external_source,
                    :name,
                    :normalized_name,
                    :address,
                    :normalized_address,
                    :latitude,
                    :longitude,
                    :phone,
                    :website,
                    :social_links,
                    :categories,
                    :description,
                    :salon_type,
                    :filter_status,
                    :filter_confidence,
                    :filter_reasons,
                    :classifier_reason_codes,
                    :rejection_reason,
                    :business_profile,
                    :classifier_decision_name,
                    :classifier_decision_categories,
                    1,
                    'not_checked',
                    :raw_payload,
                    :source_url,
                    COALESCE(:fetched_at, CURRENT_TIMESTAMP),
                    COALESCE(:fetched_at, CURRENT_TIMESTAMP),
                    CURRENT_TIMESTAMP
                )
                """,
                payload,
            )
            salon_id = int(cursor.lastrowid)
            connection.commit()

        return salon_id, False

    def save_salon_discovery(
        self,
        region_id: int,
        organization: RawOrganization,
        classification: ClassificationResult,
        raw_result_id: int,
        salon_id: int | None,
    ) -> None:
        """Persist discovery history for accepted and rejected results."""

        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO salon_discoveries (
                    salon_id,
                    raw_result_id,
                    region_id,
                    grid_cell_id,
                    query,
                    external_source,
                    external_id,
                    filter_status,
                    filter_confidence,
                    filter_reasons,
                    classifier_reason_codes,
                    rejection_reason,
                    business_profile,
                    classifier_decision_name,
                    classifier_decision_categories
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    salon_id,
                    raw_result_id,
                    region_id,
                    organization.discovered_grid_cell_id,
                    organization.discovered_query or "",
                    organization.external_source,
                    organization.external_id,
                    "accepted" if classification.accepted else "rejected",
                    classification.confidence,
                    json.dumps(classification.reasons, ensure_ascii=False),
                    json.dumps(classification.reason_codes, ensure_ascii=False),
                    classification.rejection_reason,
                    classification.business_profile,
                    classification.decision_name,
                    json.dumps(
                        classification.decision_categories,
                        ensure_ascii=False,
                    ),
                ),
            )
            connection.commit()

    def update_region_salon_count(self, region_id: int) -> None:
        """Sync regions.salons_found with accepted salon records."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM salons
                WHERE region_id = ?
                  AND filter_status = 'accepted'
                """,
                (region_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE regions
                SET salons_found = ?
                WHERE id = ?
                """,
                (int(row["total"]), region_id),
            )
            connection.commit()

    def _find_existing_salon_id(
        self,
        *,
        region_id: int,
        external_source: str,
        external_id: str | None,
        normalized_name: str | None,
        normalized_address: str | None,
        normalized_phone: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> int | None:
        with self.connect() as connection:
            if external_id:
                row = connection.execute(
                    """
                    SELECT id
                    FROM salons
                    WHERE external_source = ?
                      AND external_id = ?
                    LIMIT 1
                    """,
                    (external_source, external_id),
                ).fetchone()

                if row is not None:
                    return int(row["id"])

            if normalized_name and normalized_address:
                row = connection.execute(
                    """
                    SELECT id
                    FROM salons
                    WHERE region_id = ?
                      AND normalized_name = ?
                      AND normalized_address = ?
                    LIMIT 1
                    """,
                    (region_id, normalized_name, normalized_address),
                ).fetchone()

                if row is not None:
                    return int(row["id"])

            if normalized_name and normalized_phone:
                row = connection.execute(
                    """
                    SELECT id
                    FROM salons
                    WHERE region_id = ?
                      AND normalized_name = ?
                      AND phone = ?
                    LIMIT 1
                    """,
                    (region_id, normalized_name, normalized_phone),
                ).fetchone()

                if row is not None:
                    return int(row["id"])

            coord_key = coordinate_key(latitude, longitude)

            if normalized_name and coord_key:
                rows = connection.execute(
                    """
                    SELECT id, latitude, longitude
                    FROM salons
                    WHERE region_id = ?
                      AND normalized_name = ?
                      AND latitude IS NOT NULL
                      AND longitude IS NOT NULL
                    """,
                    (region_id, normalized_name),
                ).fetchall()

                for row in rows:
                    if coordinate_key(row["latitude"], row["longitude"]) == coord_key:
                        return int(row["id"])

        return None

    def _salon_payload(
        self,
        *,
        region_id: int,
        organization: RawOrganization,
        classification: ClassificationResult,
        normalized_name: str | None,
        normalized_address: str | None,
        normalized_phone: str | None,
    ) -> dict[str, Any]:
        return {
            "region_id": region_id,
            "grid_cell_id": organization.discovered_grid_cell_id,
            "external_id": organization.external_id,
            "source": organization.external_source,
            "external_source": organization.external_source,
            "name": organization.name,
            "normalized_name": normalized_name,
            "address": organization.address,
            "normalized_address": normalized_address,
            "latitude": organization.latitude,
            "longitude": organization.longitude,
            "phone": normalized_phone,
            "website": organization.website,
            "social_links": json.dumps(
                organization.social_links,
                ensure_ascii=False,
            ),
            "categories": json.dumps(organization.categories, ensure_ascii=False),
            "description": organization.description,
            "salon_type": classification.salon_type,
            "filter_status": "accepted",
            "filter_confidence": classification.confidence,
            "filter_reasons": json.dumps(
                classification.reasons,
                ensure_ascii=False,
            ),
            "classifier_reason_codes": json.dumps(
                classification.reason_codes,
                ensure_ascii=False,
            ),
            "rejection_reason": classification.rejection_reason,
            "business_profile": classification.business_profile,
            "classifier_decision_name": classification.decision_name,
            "classifier_decision_categories": json.dumps(
                classification.decision_categories,
                ensure_ascii=False,
            ),
            "raw_payload": json.dumps(
                organization.raw_payload,
                ensure_ascii=False,
            ),
            "source_url": organization.source_url,
            "fetched_at": organization.fetched_at,
        }

    def _update_salon(
        self,
        salon_id: int,
        payload: dict[str, Any],
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE salons
                SET
                    grid_cell_id = COALESCE(grid_cell_id, :grid_cell_id),
                    external_id = COALESCE(external_id, :external_id),
                    source = :source,
                    external_source = :external_source,
                    name = :name,
                    normalized_name = :normalized_name,
                    address = COALESCE(:address, address),
                    normalized_address = COALESCE(
                        :normalized_address,
                        normalized_address
                    ),
                    latitude = COALESCE(:latitude, latitude),
                    longitude = COALESCE(:longitude, longitude),
                    phone = COALESCE(:phone, phone),
                    website = COALESCE(:website, website),
                    social_links = :social_links,
                    categories = :categories,
                    description = COALESCE(:description, description),
                    salon_type = :salon_type,
                    filter_status = :filter_status,
                    filter_confidence = :filter_confidence,
                    filter_reasons = :filter_reasons,
                    classifier_reason_codes = :classifier_reason_codes,
                    rejection_reason = :rejection_reason,
                    business_profile = :business_profile,
                    classifier_decision_name = :classifier_decision_name,
                    classifier_decision_categories = :classifier_decision_categories,
                    manicure_confirmed = 1,
                    raw_payload = :raw_payload,
                    source_url = COALESCE(:source_url, source_url),
                    first_seen_at = COALESCE(first_seen_at, :fetched_at),
                    last_seen_at = COALESCE(:fetched_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :salon_id
                """,
                {**payload, "salon_id": salon_id},
            )
            connection.commit()

    def get_next_salon_for_enrichment(
        self,
        refresh_after_days: int | None,
    ) -> dict[str, Any] | None:
        """Return the next accepted 2GIS salon needing details enrichment."""

        refresh_clause = ""
        parameters: list[Any] = []

        if refresh_after_days is not None:
            refresh_clause = """
               OR details_enriched_at <= datetime(
                    'now',
                    '-' || ? || ' days'
               )
            """
            parameters.append(refresh_after_days)

        with self.connect() as connection:
            row = connection.execute(
                f"""
                SELECT *
                FROM salons
                WHERE lower(COALESCE(external_source, source, '')) = '2gis'
                  AND external_id IS NOT NULL
                  AND trim(external_id) != ''
                  AND COALESCE(filter_status, 'accepted') = 'accepted'
                  AND (
                    details_enriched_at IS NULL
                    OR details_status IS NULL
                    OR details_status != 'success'
                    {refresh_clause}
                  )
                ORDER BY id
                LIMIT 1
                """,
                parameters,
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_salons_for_reclassification(
        self,
        max_records: int,
        salon_id: int | None = None,
        missing_classifier_version: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return salon rows with preserved classifier input fields."""

        parameters: list[Any] = []
        where_parts: list[str] = []

        if salon_id is not None:
            where_parts.append("id = ?")
            parameters.append(salon_id)

        if missing_classifier_version is not None:
            where_parts.append(
                "(classifier_version IS NULL OR classifier_version != ?)"
            )
            parameters.append(missing_classifier_version)

        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        parameters.append(max_records)

        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM salons
                {where_clause}
                ORDER BY id
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return [dict(row) for row in rows]

    def save_salon_classification_result(
        self,
        salon_id: int,
        classification: ClassificationResult,
        input_snapshot: dict[str, Any],
        classifier_version: str = SALON_CLASSIFIER_VERSION,
    ) -> int:
        """Append one classification audit result and update current state."""

        filter_status = "accepted" if classification.accepted else "rejected"

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO salon_classification_results (
                    salon_id,
                    classifier_version,
                    accepted,
                    business_profile,
                    reason_codes_json,
                    rejection_reason,
                    input_snapshot_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    salon_id,
                    classifier_version,
                    1 if classification.accepted else 0,
                    classification.business_profile,
                    json.dumps(classification.reason_codes, ensure_ascii=False),
                    classification.rejection_reason,
                    json.dumps(input_snapshot, ensure_ascii=False),
                ),
            )
            result_id = int(cursor.lastrowid)
            connection.execute(
                """
                UPDATE salons
                SET
                    filter_status = ?,
                    filter_confidence = ?,
                    filter_reasons = ?,
                    classifier_reason_codes = ?,
                    rejection_reason = ?,
                    business_profile = ?,
                    classifier_decision_name = ?,
                    classifier_decision_categories = ?,
                    salon_type = ?,
                    manicure_confirmed = ?,
                    classifier_version = ?,
                    classified_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    filter_status,
                    classification.confidence,
                    json.dumps(classification.reasons, ensure_ascii=False),
                    json.dumps(classification.reason_codes, ensure_ascii=False),
                    classification.rejection_reason,
                    classification.business_profile,
                    classification.decision_name,
                    json.dumps(
                        classification.decision_categories,
                        ensure_ascii=False,
                    ),
                    classification.salon_type,
                    1 if classification.accepted else 0,
                    classifier_version,
                    salon_id,
                ),
            )
            connection.commit()

        return result_id

    def get_classification_audit_count(self) -> int:
        """Return total classification audit rows."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM salon_classification_results
                """
            ).fetchone()

        return int(row["total"])

    def get_salon_for_enrichment_by_id(
        self,
        salon_id: int,
    ) -> dict[str, Any] | None:
        """Return one accepted 2GIS salon eligible for details enrichment."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM salons
                WHERE id = ?
                  AND lower(COALESCE(external_source, source, '')) = '2gis'
                  AND external_id IS NOT NULL
                  AND trim(external_id) != ''
                  AND COALESCE(filter_status, 'accepted') = 'accepted'
                """,
                (salon_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_salon_for_enrichment_by_external_id(
        self,
        external_id: str,
    ) -> dict[str, Any] | None:
        """Return one accepted 2GIS salon by provider organization id."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM salons
                WHERE lower(COALESCE(external_source, source, '')) = '2gis'
                  AND external_id = ?
                  AND COALESCE(filter_status, 'accepted') = 'accepted'
                ORDER BY id
                LIMIT 1
                """,
                (external_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def save_organization_detail_result(
        self,
        salon_id: int | None,
        result: OrganizationDetailsResult,
        parser_version: str = DETAIL_PARSER_VERSION,
    ) -> int:
        """Append one raw details response and parser status."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO organization_detail_results (
                    external_source,
                    external_id,
                    salon_id,
                    http_status,
                    payload_code,
                    status,
                    error_message,
                    sanitized_source_url,
                    raw_payload_json,
                    parser_version
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.external_source,
                    result.external_id,
                    salon_id,
                    result.http_status,
                    result.payload_code,
                    result.status,
                    result.error_message,
                    result.sanitized_source_url,
                    json.dumps(result.raw_payload, ensure_ascii=False),
                    parser_version,
                ),
            )
            detail_result_id = int(cursor.lastrowid)
            connection.commit()

        return detail_result_id

    def apply_organization_details(
        self,
        salon_id: int,
        details: OrganizationDetails,
    ) -> None:
        """Merge provider details into the accepted salon record."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE salons
                SET
                    name = COALESCE(?, name),
                    address = COALESCE(?, address),
                    normalized_address = COALESCE(?, normalized_address),
                    latitude = COALESCE(?, latitude),
                    longitude = COALESCE(?, longitude),
                    categories = CASE
                        WHEN ? IS NOT NULL THEN ?
                        ELSE categories
                    END,
                    description = COALESCE(?, description),
                    organization_id = COALESCE(?, organization_id),
                    branch_id = COALESCE(?, branch_id),
                    provider_updated_at = COALESCE(?, provider_updated_at),
                    details_enriched_at = CURRENT_TIMESTAMP,
                    details_status = 'success',
                    details_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    details.name,
                    details.full_address,
                    normalize_text(details.full_address),
                    details.latitude,
                    details.longitude,
                    json.dumps(details.categories, ensure_ascii=False)
                    if details.categories
                    else None,
                    json.dumps(details.categories, ensure_ascii=False)
                    if details.categories
                    else None,
                    details.description,
                    details.organization_id,
                    details.branch_id,
                    details.provider_updated_at,
                    salon_id,
                ),
            )
            connection.commit()

    def mark_salon_details_status(
        self,
        salon_id: int,
        status: str,
        error: str | None,
    ) -> None:
        """Store the latest details enrichment status for one salon."""

        with self.connect() as connection:
            connection.execute(
                """
                UPDATE salons
                SET
                    details_enriched_at = CURRENT_TIMESTAMP,
                    details_status = ?,
                    details_error = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, error, salon_id),
            )
            connection.commit()

    def upsert_salon_contacts(
        self,
        salon_id: int,
        contacts: list[ContactValue],
        source: str,
    ) -> tuple[int, int, int]:
        """Merge normalized contacts and mark disappeared contacts inactive."""

        created = 0
        updated = 0
        seen_keys = {
            (contact.contact_type, contact.normalized_value, contact.source)
            for contact in contacts
        }

        with self.connect() as connection:
            for contact in contacts:
                existing = connection.execute(
                    """
                    SELECT id
                    FROM salon_contacts
                    WHERE salon_id = ?
                      AND contact_type = ?
                      AND normalized_value = ?
                      AND source = ?
                    """,
                    (
                        salon_id,
                        contact.contact_type,
                        contact.normalized_value,
                        contact.source,
                    ),
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO salon_contacts (
                        salon_id,
                        contact_type,
                        display_value,
                        normalized_value,
                        source,
                        is_active,
                        metadata_json
                    )
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT (
                        salon_id,
                        contact_type,
                        normalized_value,
                        source
                    )
                    DO UPDATE SET
                        display_value = excluded.display_value,
                        last_seen_at = CURRENT_TIMESTAMP,
                        is_active = 1,
                        metadata_json = excluded.metadata_json
                    """,
                    (
                        salon_id,
                        contact.contact_type,
                        contact.display_value,
                        contact.normalized_value,
                        contact.source,
                        json.dumps(contact.metadata, ensure_ascii=False),
                    ),
                )

                if existing is None:
                    created += 1
                else:
                    updated += 1

            active_rows = connection.execute(
                """
                SELECT id, contact_type, normalized_value, source
                FROM salon_contacts
                WHERE salon_id = ?
                  AND source = ?
                  AND is_active = 1
                """,
                (salon_id, source),
            ).fetchall()
            deactivate_ids = [
                int(row["id"])
                for row in active_rows
                if (
                    row["contact_type"],
                    row["normalized_value"],
                    row["source"],
                )
                not in seen_keys
            ]

            if deactivate_ids:
                placeholders = ",".join("?" for _ in deactivate_ids)
                connection.execute(
                    f"""
                    UPDATE salon_contacts
                    SET
                        is_active = 0,
                        last_seen_at = CURRENT_TIMESTAMP
                    WHERE id IN ({placeholders})
                    """,
                    deactivate_ids,
                )

            connection.commit()

        return created, updated, len(deactivate_ids)

    def get_next_salon_for_pricing(self) -> dict[str, Any] | None:
        """Return the next accepted salon needing a pricing check."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM salons
                WHERE COALESCE(filter_status, 'accepted') = 'accepted'
                ORDER BY
                    CASE
                        WHEN verification_status = 'not_checked' THEN 0
                        ELSE 1
                    END,
                    id
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_salon_for_pricing_by_id(
        self,
        salon_id: int,
    ) -> dict[str, Any] | None:
        """Return one accepted salon for controlled pricing extraction."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM salons
                WHERE id = ?
                  AND COALESCE(filter_status, 'accepted') = 'accepted'
                """,
                (salon_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def get_latest_detail_payloads_for_pricing(
        self,
        salon_id: int,
        limit: int = 3,
    ) -> list[dict[str, Any]]:
        """Return recent successful details payloads for structured price parsing."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT raw_payload_json, sanitized_source_url
                FROM organization_detail_results
                WHERE salon_id = ?
                  AND status = 'success'
                ORDER BY id DESC
                LIMIT ?
                """,
                (salon_id, limit),
            ).fetchall()

        payloads: list[dict[str, Any]] = []

        for row in rows:
            try:
                payload = json.loads(row["raw_payload_json"])
            except json.JSONDecodeError:
                continue

            payloads.append(
                {
                    "payload": payload,
                    "source_url": row["sanitized_source_url"],
                }
            )

        return payloads

    def count_pricing_eligible_salons(self) -> int:
        """Count accepted salons with an attributable pricing source."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(DISTINCT s.id) AS total
                FROM salons s
                LEFT JOIN salon_contacts sc
                    ON sc.salon_id = s.id
                   AND sc.is_active = 1
                   AND sc.contact_type = 'website'
                LEFT JOIN organization_detail_results od
                    ON od.salon_id = s.id
                   AND od.status = 'success'
                WHERE s.filter_status = 'accepted'
                  AND (
                    s.website IS NOT NULL
                    OR sc.id IS NOT NULL
                    OR od.id IS NOT NULL
                  )
                """
            ).fetchone()

        return int(row["total"])

    def save_price_check_result(
        self,
        result: PriceExtractionResult,
    ) -> int:
        """Append one price extraction audit result."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO price_check_results (
                    salon_id,
                    checked_at,
                    status,
                    source_type,
                    sanitized_source_url,
                    raw_evidence_json,
                    error_message,
                    parser_version
                )
                VALUES (?, COALESCE(?, CURRENT_TIMESTAMP), ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.salon_id,
                    result.checked_at,
                    result.extraction_status,
                    result.source_type,
                    result.source_url,
                    json.dumps(result.raw_evidence, ensure_ascii=False),
                    result.error_message,
                    result.parser_version,
                ),
            )
            check_id = int(cursor.lastrowid)
            connection.commit()

        return check_id

    def upsert_salon_price(
        self,
        result: PriceExtractionResult,
    ) -> tuple[int | None, bool]:
        """Persist current price state while keeping audit history append-only."""

        if result.extraction_status not in ("found", "ambiguous"):
            self._mark_missing_price_result(result)
            return None, False

        evidence_text = result.evidence_text or ""

        with self.connect() as connection:
            existing = connection.execute(
                """
                SELECT id
                FROM salon_prices
                WHERE salon_id = ?
                  AND service_key = ?
                  AND COALESCE(source_type, '') = COALESCE(?, '')
                  AND COALESCE(evidence_text, '') = COALESCE(?, '')
                LIMIT 1
                """,
                (
                    result.salon_id,
                    result.service_key,
                    result.source_type,
                    evidence_text,
                ),
            ).fetchone()
            connection.execute(
                """
                UPDATE salon_prices
                SET
                    is_active = 0,
                    last_seen_at = CURRENT_TIMESTAMP
                WHERE salon_id = ?
                  AND service_key = ?
                  AND is_active = 1
                  AND NOT (
                    COALESCE(source_type, '') = COALESCE(?, '')
                    AND COALESCE(evidence_text, '') = COALESCE(?, '')
                  )
                """,
                (
                    result.salon_id,
                    result.service_key,
                    result.source_type,
                    evidence_text,
                ),
            )
            cursor = connection.execute(
                """
                INSERT INTO salon_prices (
                    salon_id,
                    service_key,
                    service_name_raw,
                    service_name_normalized,
                    amount_minor,
                    currency,
                    price_type,
                    range_min_minor,
                    range_max_minor,
                    source_type,
                    source_url,
                    evidence_text,
                    confidence,
                    is_active
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT (
                    salon_id,
                    service_key,
                    source_type,
                    evidence_text
                )
                DO UPDATE SET
                    service_name_raw = excluded.service_name_raw,
                    service_name_normalized = excluded.service_name_normalized,
                    amount_minor = excluded.amount_minor,
                    currency = excluded.currency,
                    price_type = excluded.price_type,
                    range_min_minor = excluded.range_min_minor,
                    range_max_minor = excluded.range_max_minor,
                    source_url = excluded.source_url,
                    confidence = excluded.confidence,
                    last_seen_at = CURRENT_TIMESTAMP,
                    is_active = 1
                """,
                (
                    result.salon_id,
                    result.service_key,
                    result.service_name_raw,
                    result.service_name_normalized,
                    result.amount_minor,
                    result.currency,
                    result.price_type,
                    result.range_min_minor,
                    result.range_max_minor,
                    result.source_type,
                    result.source_url,
                    evidence_text,
                    result.confidence,
                ),
            )
            price_id = (
                int(existing["id"])
                if existing is not None
                else int(cursor.lastrowid)
            )
            self._update_salon_price_summary(connection, result)
            connection.commit()

        return price_id, existing is not None

    def _mark_missing_price_result(
        self,
        result: PriceExtractionResult,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE salon_prices
                SET
                    is_active = 0,
                    last_seen_at = CURRENT_TIMESTAMP
                WHERE salon_id = ?
                  AND service_key = ?
                  AND is_active = 1
                """,
                (result.salon_id, result.service_key),
            )
            connection.execute(
                """
                UPDATE salons
                SET
                    verification_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result.extraction_status, result.salon_id),
            )
            connection.commit()

    def _update_salon_price_summary(
        self,
        connection: sqlite3.Connection,
        result: PriceExtractionResult,
    ) -> None:
        if result.extraction_status != "found":
            connection.execute(
                """
                UPDATE salons
                SET
                    verification_status = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result.extraction_status, result.salon_id),
            )
            return

        price_min = None
        price_max = None

        if result.price_type == "range":
            price_min = (
                result.range_min_minor // 100
                if result.range_min_minor is not None
                else None
            )
            price_max = (
                result.range_max_minor // 100
                if result.range_max_minor is not None
                else None
            )
        elif result.amount_minor is not None:
            price_min = result.amount_minor // 100
            price_max = result.amount_minor // 100

        connection.execute(
            """
            UPDATE salons
            SET
                service_name = ?,
                service_price = ?,
                price_min = ?,
                price_max = ?,
                price_source = ?,
                price_source_url = ?,
                verification_status = 'price_found',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                result.service_name_raw,
                self._display_price(result),
                price_min,
                price_max,
                result.source_type,
                result.source_url,
                result.salon_id,
            ),
        )

    def _display_price(self, result: PriceExtractionResult) -> str | None:
        if result.price_type == "range":
            if result.range_min_minor is None or result.range_max_minor is None:
                return None

            return f"{result.range_min_minor // 100}-{result.range_max_minor // 100}"

        if result.amount_minor is None:
            return None

        prefix = "от " if result.price_type == "from" else ""
        return f"{prefix}{result.amount_minor // 100}"

    def peek_next_region(
        self,
        region_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Return a candidate region without mutating region state."""

        with self.connect() as connection:
            if region_id is not None:
                row = connection.execute(
                    """
                    SELECT *
                    FROM regions
                    WHERE id = ?
                    """,
                    (region_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT *
                    FROM regions
                    WHERE status IN ('in_progress', 'pending')
                    ORDER BY
                        CASE
                            WHEN status = 'in_progress' THEN 0
                            ELSE 1
                        END,
                        scan_order
                    LIMIT 1
                    """
                ).fetchone()

        if row is None:
            return None

        return dict(row)

    def claim_region_for_agent(
        self,
        region_id: int | None = None,
    ) -> dict[str, Any] | None:
        """Atomically claim a pending/in-progress region for orchestration."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if region_id is not None:
                row = connection.execute(
                    """
                    SELECT *
                    FROM regions
                    WHERE id = ?
                    """,
                    (region_id,),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT *
                    FROM regions
                    WHERE status IN ('in_progress', 'pending')
                    ORDER BY
                        CASE
                            WHEN status = 'in_progress' THEN 0
                            ELSE 1
                        END,
                        scan_order
                    LIMIT 1
                    """
                ).fetchone()

            region = dict(row) if row is not None else None

            if region is None:
                connection.commit()
                return None

            if region["status"] == "completed":
                connection.commit()
                return None

            if region["status"] == "pending":
                connection.execute(
                    """
                    UPDATE regions
                    SET
                        status = 'in_progress',
                        started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
                    WHERE id = ?
                    """,
                    (region["id"],),
                )

            connection.commit()

        return self.get_region_progress(int(region["id"]))

    def get_region_cell_status_counts(self, region_id: int) -> dict[str, int]:
        """Return grid-cell counts grouped by status."""

        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM grid_cells
                WHERE region_id = ?
                GROUP BY status
                """,
                (region_id,),
            ).fetchall()

        return {str(row["status"]): int(row["total"]) for row in rows}

    def get_next_pending_cell_preview(self, region_id: int) -> dict[str, Any] | None:
        """Return the next pending grid cell without claiming it."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM grid_cells
                WHERE region_id = ?
                  AND status = 'pending'
                ORDER BY cell_order
                LIMIT 1
                """,
                (region_id,),
            ).fetchone()

        if row is None:
            return None

        return dict(row)

    def recover_stale_agent_runs(self, stale_minutes: int) -> int:
        """Mark old running agent runs as interrupted."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE agent_runs
                SET
                    status = 'interrupted',
                    finished_at = CURRENT_TIMESTAMP,
                    error_message = COALESCE(error_message, 'stale run recovered')
                WHERE status = 'running'
                  AND datetime(started_at, '+' || ? || ' minutes') < CURRENT_TIMESTAMP
                """,
                (stale_minutes,),
            )
            connection.commit()

        return int(cursor.rowcount)

    def acquire_agent_lock(
        self,
        lock_name: str,
        owner: str,
        stale_minutes: int,
    ) -> bool:
        """Acquire a SQLite lock, replacing only expired lock rows."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT owner, expires_at
                FROM agent_locks
                WHERE lock_name = ?
                """,
                (lock_name,),
            ).fetchone()

            if row is not None:
                expired = connection.execute(
                    """
                    SELECT datetime(?) <= CURRENT_TIMESTAMP AS expired
                    """,
                    (row["expires_at"],),
                ).fetchone()

                if int(expired["expired"]) != 1:
                    connection.rollback()
                    return False

            connection.execute(
                """
                INSERT INTO agent_locks (
                    lock_name,
                    owner,
                    acquired_at,
                    expires_at
                )
                VALUES (
                    ?,
                    ?,
                    CURRENT_TIMESTAMP,
                    datetime(CURRENT_TIMESTAMP, '+' || ? || ' minutes')
                )
                ON CONFLICT(lock_name)
                DO UPDATE SET
                    owner = excluded.owner,
                    acquired_at = excluded.acquired_at,
                    expires_at = excluded.expires_at
                """,
                (lock_name, owner, stale_minutes),
            )
            connection.commit()

        return True

    def release_agent_lock(self, lock_name: str, owner: str) -> None:
        """Release a lock if it is still owned by the caller."""

        with self.connect() as connection:
            connection.execute(
                """
                DELETE FROM agent_locks
                WHERE lock_name = ?
                  AND owner = ?
                """,
                (lock_name, owner),
            )
            connection.commit()

    def create_agent_run_record(
        self,
        *,
        region_id: int | None,
        dry_run: bool,
        configuration_snapshot: dict[str, Any],
        owner: str,
    ) -> int:
        """Create one live agent run record."""

        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO agent_runs (
                    region_id,
                    status,
                    current_stage,
                    dry_run,
                    configuration_snapshot_json,
                    resume_token
                )
                VALUES (?, 'running', 'select_region', ?, ?, ?)
                """,
                (
                    region_id,
                    1 if dry_run else 0,
                    json.dumps(configuration_snapshot, ensure_ascii=False),
                    owner,
                ),
            )
            run_id = int(cursor.lastrowid)
            connection.commit()

        return run_id

    def update_agent_run_record(
        self,
        run_id: int,
        **fields: Any,
    ) -> None:
        """Update selected mutable agent run fields."""

        if not fields:
            return

        allowed = {
            "status",
            "current_stage",
            "finished_at",
            "cells_attempted",
            "cells_completed",
            "cells_failed",
            "organizations_observed",
            "salons_created",
            "salons_updated",
            "salons_accepted",
            "salons_rejected",
            "enrichments_attempted",
            "enrichments_succeeded",
            "price_checks_attempted",
            "prices_found",
            "export_path",
            "error_stage",
            "error_message",
        }
        assignments = []
        values: list[Any] = []

        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"Unsupported agent_runs field: {key}")

            assignments.append(f"{key} = ?")
            values.append(value)

        values.append(run_id)

        with self.connect() as connection:
            connection.execute(
                f"""
                UPDATE agent_runs
                SET {', '.join(assignments)}
                WHERE id = ?
                """,
                values,
            )
            connection.commit()

    def finish_agent_run_record(
        self,
        run_id: int,
        status: str,
        **fields: Any,
    ) -> None:
        """Finish one live agent run."""

        self.update_agent_run_record(run_id, status=status, **fields)
        with self.connect() as connection:
            connection.execute(
                """
                UPDATE agent_runs
                SET finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (run_id,),
            )
            connection.commit()

    def get_agent_run(self, run_id: int) -> dict[str, Any]:
        """Return one agent run record."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT *
                FROM agent_runs
                WHERE id = ?
                """,
                (run_id,),
            ).fetchone()

        if row is None:
            raise ValueError(f"Agent run with ID {run_id} not found.")

        return dict(row)

    def complete_region_if_terminal(self, region_id: int) -> bool:
        """Mark region complete only when grid exists and all cells are terminal."""

        generation = self.get_grid_generation(region_id)

        if generation is None or generation["status"] != "complete":
            return False

        counts = self.get_region_cell_status_counts(region_id)

        if counts.get("pending", 0) > 0 or counts.get("in_progress", 0) > 0:
            return False

        completed = counts.get("completed", 0)
        total = sum(counts.values())

        with self.connect() as connection:
            accepted = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM salons
                WHERE region_id = ?
                  AND filter_status = 'accepted'
                """,
                (region_id,),
            ).fetchone()
            rejected = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM salons
                WHERE region_id = ?
                  AND filter_status = 'rejected'
                """,
                (region_id,),
            ).fetchone()
            connection.execute(
                """
                UPDATE regions
                SET
                    status = 'completed',
                    completed_at = CURRENT_TIMESTAMP,
                    total_cells = ?,
                    completed_cells = ?,
                    salons_found = ?,
                    comment = ?
                WHERE id = ?
                """,
                (
                    total,
                    completed,
                    int(accepted["total"]),
                    f"Rejected salons: {int(rejected['total'])}; failed cells: {counts.get('failed', 0)}",
                    region_id,
                ),
            )
            connection.commit()

        return True

    def get_table_names(self) -> list[str]:
        with self.connect() as connection:
            rows = connection.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()

        return [row["name"] for row in rows]

    def initialize(self) -> None:
        self.create_tables()
        self.sync_regions()

        tables = self.get_table_names()
        regions_count = self.get_regions_count()

        print(f"✅ База данных готова: {self.db_path}")
        print(f"✅ Таблицы: {', '.join(tables)}")
        print(f"✅ Регионов в базе: {regions_count}")
