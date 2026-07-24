from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.settings import (
    GRID_GENERATOR_VERSION,
    GRID_INSERT_BATCH_SIZE,
    GRID_SIZE_METERS,
)
from database_manager import Database
from geometry.grid_generator import ProjectedGridGenerator
from geometry.models import GridCell
from osm.boundary_client import OverpassBoundaryClient

ProgressLogger = Callable[[str], None]


@dataclass(frozen=True)
class GridGenerationResult:
    """Result of ensuring a region has grid cells."""

    cells_count: int
    created: bool
    candidate_cells: int = 0
    elapsed_seconds: float = 0.0


class GridManager:
    """Coordinates boundary loading, projected grid generation, and persistence."""

    def __init__(
        self,
        database: Database,
        boundary_client: OverpassBoundaryClient | None = None,
        grid_generator: ProjectedGridGenerator | None = None,
        batch_size: int = GRID_INSERT_BATCH_SIZE,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if batch_size <= 0:
            raise ValueError("Grid insert batch size must be greater than zero.")

        self.database = database
        self.progress_logger = progress_logger or print
        self.boundary_client = boundary_client or OverpassBoundaryClient(
            progress_logger=self.progress_logger,
        )
        self.grid_generator = grid_generator or ProjectedGridGenerator(
            cell_size_meters=GRID_SIZE_METERS,
            progress_logger=self.progress_logger,
        )
        self.batch_size = batch_size

    def ensure_grid_for_region(
        self,
        region: dict[str, Any],
    ) -> GridGenerationResult:
        """
        Create grid cells for a region unless complete metadata already exists.
        """

        region_id = int(region["id"])
        existing_generation = self.database.get_grid_generation(region_id)

        if self._is_complete_generation(region_id, existing_generation):
            cells_count = int(existing_generation["persisted_cells"])
            return GridGenerationResult(
                cells_count=cells_count,
                created=False,
            )

        started_at = time.monotonic()

        try:
            boundary = self.boundary_client.get_region_boundary(str(region["name"]))
            self.database.start_grid_generation(
                region_id=region_id,
                cell_size_meters=GRID_SIZE_METERS,
                boundary=boundary,
                generator_version=GRID_GENERATOR_VERSION,
            )

            persisted_cells = 0
            batch: list[GridCell] = []

            for cell in self.grid_generator.iter_cells(boundary.geometry):
                batch.append(cell)

                if len(batch) >= self.batch_size:
                    persisted_cells = self.database.insert_grid_cell_batch(
                        region_id,
                        batch,
                    )
                    self.progress_logger(
                        f"Persisted grid cells: {persisted_cells}"
                    )
                    batch = []

            if batch:
                persisted_cells = self.database.insert_grid_cell_batch(
                    region_id,
                    batch,
                )
                self.progress_logger(f"Persisted grid cells: {persisted_cells}")

            accepted_cells = self.grid_generator.last_stats.accepted_cells
            self.database.complete_grid_generation(
                region_id=region_id,
                expected_cells=accepted_cells,
            )
            elapsed_seconds = time.monotonic() - started_at
            self.progress_logger(
                "Grid generation complete: "
                f"candidates={self.grid_generator.last_stats.candidate_cells}, "
                f"accepted={accepted_cells}, "
                f"persisted={persisted_cells}, "
                f"elapsed={elapsed_seconds:.1f}s"
            )

            return GridGenerationResult(
                cells_count=accepted_cells,
                created=True,
                candidate_cells=self.grid_generator.last_stats.candidate_cells,
                elapsed_seconds=elapsed_seconds,
            )
        except Exception as error:
            self.database.fail_grid_generation(region_id, str(error))
            raise

    def _is_complete_generation(
        self,
        region_id: int,
        generation: dict[str, Any] | None,
    ) -> bool:
        if generation is None:
            return False

        if generation["status"] != "complete":
            self.progress_logger(
                "Existing grid generation is not complete; regenerating."
            )
            return False

        if int(generation["cell_size_meters"]) != GRID_SIZE_METERS:
            self.progress_logger("Grid cell size changed; regenerating.")
            return False

        if generation["generator_version"] != GRID_GENERATOR_VERSION:
            self.progress_logger("Grid generator version changed; regenerating.")
            return False

        actual_cells = self.database.get_grid_cells_count(region_id)
        expected_cells = int(generation["expected_cells"])
        persisted_cells = int(generation["persisted_cells"])

        if actual_cells != expected_cells or persisted_cells != expected_cells:
            self.progress_logger("Grid metadata count mismatch; regenerating.")
            return False

        boundary_cache_path = generation.get("boundary_cache_path")

        if boundary_cache_path and Path(str(boundary_cache_path)).exists():
            self.progress_logger(f"Boundary cache hit: {boundary_cache_path}")
        elif boundary_cache_path:
            self.progress_logger(
                f"Boundary cache metadata path missing: {boundary_cache_path}"
            )

        return True
