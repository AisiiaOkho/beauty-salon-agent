from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class BoundaryRecord:
    """A resolved and cached administrative boundary."""

    region_name: str
    relation_id: int
    source_endpoint: str
    fetched_at: str
    geometry: BaseGeometry
    cache_path: Path | None = None
    osm_version: int | None = None
    osm_timestamp: str | None = None
    raw_relation: dict[str, Any] | None = None
