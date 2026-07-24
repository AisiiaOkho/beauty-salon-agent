from __future__ import annotations

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import certifi
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from config.region_metadata import REGION_METADATA, RegionMetadata
from config.settings import (
    BOUNDARY_CACHE_DIRECTORY,
    OSM_BACKOFF_SECONDS,
    OSM_MAX_RETRIES,
    OSM_OVERPASS_ENDPOINTS,
    OSM_TIMEOUT_SECONDS,
    OSM_USER_AGENT,
)

from .boundary_cache import BoundaryCache
from .models import BoundaryRecord

ProgressLogger = Callable[[str], None]


class BoundaryResolutionError(RuntimeError):
    """Raised when an OSM boundary cannot be resolved confidently."""


class OverpassRequestError(RuntimeError):
    """Raised when all Overpass endpoints/retries fail."""


class OverpassBoundaryClient:
    """Production-safe OpenStreetMap boundary loader with local caching."""

    RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        endpoints: list[str] | None = None,
        timeout_seconds: int = OSM_TIMEOUT_SECONDS,
        max_retries: int = OSM_MAX_RETRIES,
        backoff_seconds: float = OSM_BACKOFF_SECONDS,
        user_agent: str = OSM_USER_AGENT,
        cache: BoundaryCache | None = None,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        self.endpoints = endpoints or list(OSM_OVERPASS_ENDPOINTS)
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.user_agent = user_agent
        self.cache = cache or BoundaryCache(Path(BOUNDARY_CACHE_DIRECTORY))
        self.progress_logger = progress_logger or (lambda message: None)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def get_region_boundary(self, region_name: str) -> BoundaryRecord:
        """Return a cached or freshly fetched boundary for a region."""

        cached_record = self.cache.load(region_name)

        if cached_record is not None:
            self.progress_logger(
                f"Boundary cache hit: {cached_record.cache_path}"
            )
            return cached_record

        metadata = REGION_METADATA.get(
            region_name,
            RegionMetadata(name=region_name),
        )
        self.progress_logger(f"Boundary cache miss: {region_name}")
        relation, endpoint = self._resolve_relation(metadata)
        geometry = self._relation_to_geometry(relation)
        fetched_at = datetime.now(UTC).isoformat()
        record = BoundaryRecord(
            region_name=region_name,
            relation_id=int(relation["id"]),
            source_endpoint=endpoint,
            fetched_at=fetched_at,
            geometry=geometry,
            osm_version=relation.get("version"),
            osm_timestamp=relation.get("timestamp"),
            raw_relation=relation,
        )

        saved_record = self.cache.save(record)
        self.progress_logger(f"Boundary cached: {saved_record.cache_path}")
        return saved_record

    def _resolve_relation(
        self,
        metadata: RegionMetadata,
    ) -> tuple[dict[str, Any], str]:
        queries = self._build_resolution_queries(metadata)

        for label, query in queries:
            document, endpoint = self._request_overpass(query, label)
            relations = self._extract_administrative_relations(document)

            if len(relations) == 1:
                relation = relations[0]
                relation_id = relation.get("id")
                self.progress_logger(
                    f"Boundary resolved by {label}: relation {relation_id}"
                )
                return relation, endpoint

            if len(relations) > 1:
                relation_ids = [
                    str(relation.get("id"))
                    for relation in relations
                ]
                raise BoundaryResolutionError(
                    "Ambiguous OSM boundary resolution for "
                    f"{metadata.name} via {label}: "
                    f"{', '.join(relation_ids)}."
                )

        raise BoundaryResolutionError(
            f"Could not resolve OSM boundary for {metadata.name}. "
            "Add a pinned osm_relation_id, ISO3166-2, Wikidata, or alias."
        )

    def _build_resolution_queries(
        self,
        metadata: RegionMetadata,
    ) -> list[tuple[str, str]]:
        queries: list[tuple[str, str]] = []

        if metadata.osm_relation_id is not None:
            queries.append(
                (
                    "pinned relation id",
                    self._query_by_relation_id(metadata.osm_relation_id),
                )
            )

        if metadata.iso3166_2:
            queries.append(
                (
                    f"ISO3166-2 {metadata.iso3166_2}",
                    self._query_by_tag("ISO3166-2", metadata.iso3166_2),
                )
            )

        if metadata.wikidata:
            queries.append(
                (
                    f"Wikidata {metadata.wikidata}",
                    self._query_by_tag("wikidata", metadata.wikidata),
                )
            )

        for name in (metadata.name, *metadata.aliases):
            queries.append((f"name:ru {name}", self._query_by_tag("name:ru", name)))
            queries.append((f"name {name}", self._query_by_tag("name", name)))

        return queries

    def _request_overpass(
        self,
        query: str,
        label: str,
    ) -> tuple[dict[str, Any], str]:
        errors: list[str] = []

        for endpoint in self.endpoints:
            for attempt in range(1, self.max_retries + 1):
                try:
                    self.progress_logger(
                        f"Overpass request {label}: {endpoint} "
                        f"(attempt {attempt}/{self.max_retries})"
                    )
                    return self._perform_request(endpoint, query), endpoint
                except urllib.error.HTTPError as error:
                    retry_after = error.headers.get("Retry-After")
                    message = f"{endpoint}: HTTP {error.code}"
                    errors.append(message)

                    if error.code not in self.RETRYABLE_STATUS_CODES:
                        raise OverpassRequestError(message) from error

                    self._sleep_before_retry(attempt, retry_after)
                except (
                    urllib.error.URLError,
                    TimeoutError,
                    json.JSONDecodeError,
                    ValueError,
                ) as error:
                    errors.append(f"{endpoint}: {error}")
                    self._sleep_before_retry(attempt, None)

        raise OverpassRequestError(
            f"Overpass failed for {label}. Attempts: {'; '.join(errors)}"
        )

    def _perform_request(self, endpoint: str, query: str) -> dict[str, Any]:
        payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )

        with urllib.request.urlopen(
            request,
            timeout=self.timeout_seconds,
            context=self.ssl_context,
        ) as response:
            content_type = response.headers.get("Content-Type", "")

            if "json" not in content_type.lower():
                raise ValueError(
                    f"Unexpected Overpass content type: {content_type}"
                )

            return json.loads(response.read().decode("utf-8"))

    def _sleep_before_retry(
        self,
        attempt: int,
        retry_after: str | None,
    ) -> None:
        if attempt >= self.max_retries:
            return

        sleep_seconds = self._retry_after_seconds(retry_after)

        if sleep_seconds is None:
            sleep_seconds = self.backoff_seconds * (2 ** (attempt - 1))

        self.progress_logger(f"Overpass retry in {sleep_seconds:.1f}s")
        time.sleep(sleep_seconds)

    def _retry_after_seconds(self, retry_after: str | None) -> float | None:
        if retry_after is None:
            return None

        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    def _extract_administrative_relations(
        self,
        document: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return [
            element
            for element in document.get("elements", [])
            if element.get("type") == "relation"
            and element.get("tags", {}).get("boundary") == "administrative"
        ]

    def _query_by_relation_id(self, relation_id: int) -> str:
        return f"""
            [out:json][timeout:{self.timeout_seconds}];
            relation({relation_id});
            out meta geom qt;
        """

    def _query_by_tag(self, tag_name: str, tag_value: str) -> str:
        escaped_tag = self._escape_overpass_string(tag_name)
        escaped_value = self._escape_overpass_string(tag_value)

        return f"""
            [out:json][timeout:{self.timeout_seconds}];
            area["ISO3166-1"="RU"][admin_level=2]->.russia;
            relation(area.russia)
              ["boundary"="administrative"]
              ["{escaped_tag}"="{escaped_value}"];
            out meta geom qt;
        """

    def _escape_overpass_string(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    def _relation_to_geometry(self, relation: dict[str, Any]) -> BaseGeometry:
        outer_lines = self._member_lines(relation, role="outer")
        inner_lines = self._member_lines(relation, role="inner")

        if not outer_lines:
            relation_id = relation.get("id", "unknown")
            raise BoundaryResolutionError(
                f"OSM relation {relation_id} has no outer geometry."
            )

        outer_geometry = unary_union(list(polygonize(outer_lines)))

        if outer_geometry.is_empty:
            relation_id = relation.get("id", "unknown")
            raise BoundaryResolutionError(
                f"OSM relation {relation_id} could not be polygonized."
            )

        if inner_lines:
            inner_geometry = unary_union(list(polygonize(inner_lines)))

            if not inner_geometry.is_empty:
                outer_geometry = outer_geometry.difference(inner_geometry)

        valid_geometry = make_valid(outer_geometry)

        if isinstance(valid_geometry, Polygon):
            return MultiPolygon([valid_geometry])

        if isinstance(valid_geometry, MultiPolygon):
            return valid_geometry

        polygon_parts = [
            geometry
            for geometry in getattr(valid_geometry, "geoms", [])
            if isinstance(geometry, Polygon)
        ]

        if polygon_parts:
            return MultiPolygon(polygon_parts)

        relation_id = relation.get("id", "unknown")
        raise BoundaryResolutionError(
            f"OSM relation {relation_id} produced non-polygon geometry: "
            f"{valid_geometry.geom_type}."
        )

    def _member_lines(
        self,
        relation: dict[str, Any],
        role: str,
    ) -> list[LineString]:
        lines: list[LineString] = []

        for member in relation.get("members", []):
            member_role = member.get("role", "")

            if member.get("type") != "way":
                continue

            if role == "outer" and member_role not in ("outer", ""):
                continue

            if role == "inner" and member_role != "inner":
                continue

            geometry = member.get("geometry") or []

            if len(geometry) < 2:
                continue

            coordinates = [
                (float(point["lon"]), float(point["lat"]))
                for point in geometry
            ]
            lines.append(LineString(coordinates))

        return lines
