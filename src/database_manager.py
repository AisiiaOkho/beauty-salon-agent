import sqlite3
import sys
import json
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from config.regions import REGIONS
from config.settings import GRID_GENERATOR_VERSION
from geometry.models import GridCell
from osm.models import BoundaryRecord
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
