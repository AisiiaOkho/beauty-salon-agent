from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from shapely.geometry import mapping, shape

from .models import BoundaryRecord


class BoundaryCache:
    """Filesystem cache for normalized OSM boundaries."""

    def __init__(self, cache_directory: Path) -> None:
        self.cache_directory = cache_directory

    def load(self, region_name: str) -> BoundaryRecord | None:
        """Load a cached boundary if it exists and is parseable."""

        cache_path = self.get_path(region_name)

        if not cache_path.exists():
            return None

        with cache_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        geometry = shape(payload["geometry"])

        return BoundaryRecord(
            region_name=payload["region_name"],
            relation_id=int(payload["osm_relation_id"]),
            source_endpoint=payload["source_endpoint"],
            fetched_at=payload["fetched_at"],
            geometry=geometry,
            cache_path=cache_path,
            osm_version=payload.get("osm_version"),
            osm_timestamp=payload.get("osm_timestamp"),
            raw_relation=payload.get("raw_relation"),
        )

    def save(self, record: BoundaryRecord) -> BoundaryRecord:
        """Persist a boundary record and return it with cache_path populated."""

        self.cache_directory.mkdir(parents=True, exist_ok=True)
        cache_path = self.get_path(record.region_name)
        payload: dict[str, Any] = {
            "region_name": record.region_name,
            "osm_relation_id": record.relation_id,
            "source_endpoint": record.source_endpoint,
            "fetched_at": record.fetched_at,
            "osm_version": record.osm_version,
            "osm_timestamp": record.osm_timestamp,
            "geometry": mapping(record.geometry),
            "raw_relation": record.raw_relation,
            "cache_metadata": {
                "cache_schema": 1,
                "saved_at": datetime.now(UTC).isoformat(),
            },
        }

        with cache_path.open("w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False)

        return BoundaryRecord(
            region_name=record.region_name,
            relation_id=record.relation_id,
            source_endpoint=record.source_endpoint,
            fetched_at=record.fetched_at,
            geometry=record.geometry,
            cache_path=cache_path,
            osm_version=record.osm_version,
            osm_timestamp=record.osm_timestamp,
            raw_relation=record.raw_relation,
        )

    def get_path(self, region_name: str) -> Path:
        """Return the cache file path for a region."""

        slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "_", region_name).strip("_")
        return self.cache_directory / f"{slug}.geojson"
