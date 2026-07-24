from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from shapely.geometry import MultiPolygon, Polygon

from osm.boundary_cache import BoundaryCache
from osm.boundary_client import OverpassBoundaryClient
from osm.models import BoundaryRecord


class BoundaryCacheTests(unittest.TestCase):
    def test_cache_reuse_loads_saved_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = BoundaryCache(Path(directory))
            record = BoundaryRecord(
                region_name="Тестовая область",
                relation_id=123,
                source_endpoint="https://example.test",
                fetched_at=datetime.now(UTC).isoformat(),
                geometry=MultiPolygon(
                    [
                        Polygon(
                            [
                                (30.0, 55.0),
                                (30.01, 55.0),
                                (30.01, 55.01),
                                (30.0, 55.01),
                                (30.0, 55.0),
                            ]
                        )
                    ]
                ),
                osm_version=7,
                osm_timestamp="2026-01-01T00:00:00Z",
                raw_relation={"id": 123},
            )

            saved = cache.save(record)
            loaded = cache.load("Тестовая область")

            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.relation_id, 123)
            self.assertEqual(loaded.cache_path, saved.cache_path)
            self.assertFalse(loaded.geometry.is_empty)


class RetryClient(OverpassBoundaryClient):
    def __init__(self) -> None:
        super().__init__(
            endpoints=["https://example.test"],
            max_retries=2,
            backoff_seconds=0,
            progress_logger=lambda message: None,
        )
        self.calls = 0

    def _perform_request(self, endpoint: str, query: str) -> dict[str, object]:
        self.calls += 1

        if self.calls == 1:
            raise urllib.error.HTTPError(
                url=endpoint,
                code=503,
                msg="busy",
                hdrs={},
                fp=None,
            )

        return {"elements": []}


class OverpassBoundaryClientTests(unittest.TestCase):
    def test_retry_behavior_for_retryable_status(self) -> None:
        client = RetryClient()

        document, endpoint = client._request_overpass("query", "test")

        self.assertEqual(endpoint, "https://example.test")
        self.assertEqual(document, {"elements": []})
        self.assertEqual(client.calls, 2)

    def test_cache_payload_contains_required_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = BoundaryCache(Path(directory))
            cache.save(
                BoundaryRecord(
                    region_name="Тестовая область",
                    relation_id=123,
                    source_endpoint="https://example.test",
                    fetched_at="2026-01-01T00:00:00+00:00",
                    geometry=MultiPolygon(
                        [
                            Polygon(
                                [
                                    (30.0, 55.0),
                                    (30.01, 55.0),
                                    (30.01, 55.01),
                                    (30.0, 55.01),
                                    (30.0, 55.0),
                                ]
                            )
                        ]
                    ),
                    osm_version=5,
                    osm_timestamp="2026-01-01T00:00:00Z",
                )
            )
            payload = json.loads(
                cache.get_path("Тестовая область").read_text(encoding="utf-8")
            )

            self.assertEqual(payload["region_name"], "Тестовая область")
            self.assertEqual(payload["osm_relation_id"], 123)
            self.assertEqual(payload["source_endpoint"], "https://example.test")
            self.assertIn("geometry", payload)
            self.assertEqual(payload["osm_version"], 5)


if __name__ == "__main__":
    unittest.main()
