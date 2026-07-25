from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from typing import Any

from config.settings import SALON_CLASSIFIER_VERSION
from database_manager import Database
from scanner.models import ClassificationResult, RawOrganization


@dataclass(frozen=True)
class CanonicalBackfillChange:
    """One canonical organization decision reconstructed from discoveries."""

    external_source: str
    external_id: str
    name: str
    previous_salon_id: int | None
    previous_status: str | None
    new_status: str
    action: str
    rejection_reason: str | None
    business_profile: str
    reason_codes: list[str] = field(default_factory=list)
    observation_count: int = 0
    distinct_cells: int = 0
    conflicting_decisions: bool = False
    conflict_decisions: list[dict[str, object]] = field(default_factory=list)
    issue: str | None = None


@dataclass
class CanonicalBackfillSummary:
    """Counters for one canonical organization backfill run."""

    processed: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped: int = 0
    conflicts: int = 0
    dry_run: bool = True
    changes: list[CanonicalBackfillChange] = field(default_factory=list)


class CanonicalOrganizationBackfiller:
    """Backfill canonical organization rows from stored discovery decisions."""

    def __init__(
        self,
        database: Database,
        *,
        dry_run: bool = True,
        classifier_version: str = SALON_CLASSIFIER_VERSION,
    ) -> None:
        self.database = database
        self.dry_run = dry_run
        self.classifier_version = classifier_version

    def backfill_rejected(
        self,
        *,
        region_id: int | None = None,
        max_records: int | None = None,
    ) -> CanonicalBackfillSummary:
        """Backfill uniquely identified rejected organizations."""

        groups = self._load_rejected_groups(region_id=region_id, max_records=max_records)
        summary = CanonicalBackfillSummary(dry_run=self.dry_run)

        for group in groups:
            change = self._process_group(group)
            summary.processed += 1
            summary.created += 1 if change.action == "create" else 0
            summary.updated += 1 if change.action == "update" else 0
            summary.unchanged += 1 if change.action == "unchanged" else 0
            summary.skipped += 1 if change.action == "skip" else 0
            summary.conflicts += 1 if change.conflicting_decisions else 0
            summary.changes.append(change)

        return summary

    def _load_rejected_groups(
        self,
        *,
        region_id: int | None,
        max_records: int | None,
    ) -> list[dict[str, Any]]:
        parameters: list[Any] = []
        region_filter = ""

        if region_id is not None:
            region_filter = "AND sd.region_id = ?"
            parameters.append(region_id)

        limit_clause = ""

        if max_records is not None:
            limit_clause = "LIMIT ?"
            parameters.append(max_records)

        with self.database.connect() as connection:
            keys = connection.execute(
                f"""
                SELECT sd.external_source, sd.external_id
                FROM salon_discoveries sd
                WHERE sd.filter_status = 'rejected'
                  AND sd.external_id IS NOT NULL
                  AND trim(sd.external_id) != ''
                  {region_filter}
                GROUP BY sd.external_source, sd.external_id
                ORDER BY MAX(sd.id)
                {limit_clause}
                """,
                parameters,
            ).fetchall()

            groups: list[dict[str, Any]] = []

            for key in keys:
                rows = connection.execute(
                    """
                    SELECT
                        sd.*,
                        rr.payload AS raw_payload,
                        rr.name AS raw_name,
                        rr.fetched_at AS raw_fetched_at
                    FROM salon_discoveries sd
                    LEFT JOIN raw_organization_results rr ON rr.id = sd.raw_result_id
                    WHERE sd.external_source = ?
                      AND sd.external_id = ?
                    ORDER BY sd.id
                    """,
                    (key["external_source"], key["external_id"]),
                ).fetchall()
                existing = connection.execute(
                    """
                    SELECT *
                    FROM salons
                    WHERE external_source = ?
                      AND external_id = ?
                    ORDER BY id
                    LIMIT 1
                    """,
                    (key["external_source"], key["external_id"]),
                ).fetchone()
                groups.append(
                    {
                        "external_source": key["external_source"],
                        "external_id": key["external_id"],
                        "rows": [dict(row) for row in rows],
                        "existing": dict(existing) if existing is not None else None,
                    }
                )

        return groups

    def _process_group(self, group: dict[str, Any]) -> CanonicalBackfillChange:
        rows: list[dict[str, Any]] = group["rows"]
        latest = rows[-1]
        existing = group["existing"]
        organization = self._organization_from_discovery(latest)
        classification = self._classification_from_discovery(latest)
        snapshot = self._input_snapshot(organization, latest, len(rows))
        conflict_decisions = self._conflict_decisions(rows)
        conflicting = len(conflict_decisions) > 1
        action = self._planned_action(existing, classification)
        previous_status = existing.get("filter_status") if existing else None
        previous_salon_id = int(existing["id"]) if existing else None
        issue = None

        if not organization.external_id:
            action = "skip"
            issue = "missing_external_id"

        if not self.dry_run and action in {"create", "update"}:
            salon_id, _merged = self.database.upsert_salon(
                region_id=int(latest["region_id"]),
                organization=organization,
                classification=classification,
            )
            self._link_discoveries_to_salon(
                external_source=organization.external_source,
                external_id=organization.external_id or "",
                salon_id=salon_id,
            )
            self.database.save_salon_classification_result(
                salon_id=salon_id,
                classification=classification,
                input_snapshot=snapshot,
                classifier_version=self.classifier_version,
            )
        elif not self.dry_run and action == "unchanged" and previous_salon_id is not None:
            self._link_discoveries_to_salon(
                external_source=organization.external_source,
                external_id=organization.external_id or "",
                salon_id=previous_salon_id,
            )

        return CanonicalBackfillChange(
            external_source=organization.external_source,
            external_id=organization.external_id or "",
            name=organization.name,
            previous_salon_id=previous_salon_id,
            previous_status=str(previous_status) if previous_status else None,
            new_status="accepted" if classification.accepted else "rejected",
            action=action,
            rejection_reason=classification.rejection_reason,
            business_profile=classification.business_profile,
            reason_codes=list(classification.reason_codes),
            observation_count=len(rows),
            distinct_cells=len({int(row["grid_cell_id"]) for row in rows}),
            conflicting_decisions=conflicting,
            conflict_decisions=conflict_decisions,
            issue=issue,
        )

    def _link_discoveries_to_salon(
        self,
        *,
        external_source: str,
        external_id: str,
        salon_id: int,
    ) -> None:
        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE salon_discoveries
                SET salon_id = COALESCE(salon_id, ?)
                WHERE external_source = ?
                  AND external_id = ?
                """,
                (salon_id, external_source, external_id),
            )
            connection.commit()

    def _planned_action(
        self,
        existing: dict[str, Any] | None,
        classification: ClassificationResult,
    ) -> str:
        if existing is None:
            return "create"

        expected_status = "accepted" if classification.accepted else "rejected"
        existing_codes = self._json_list(existing.get("classifier_reason_codes"))

        if (
            existing.get("filter_status") != expected_status
            or existing.get("rejection_reason") != classification.rejection_reason
            or existing.get("business_profile") != classification.business_profile
            or existing_codes != classification.reason_codes
        ):
            return "update"

        return "unchanged"

    def _organization_from_discovery(self, row: dict[str, Any]) -> RawOrganization:
        payload = self._json_object(row.get("raw_payload"))
        point = payload.get("point") if isinstance(payload.get("point"), dict) else {}

        return RawOrganization(
            external_source=str(row["external_source"]),
            external_id=self._string_or_none(row.get("external_id")),
            name=str(payload.get("name") or row.get("raw_name") or ""),
            address=self._string_or_none(payload.get("address_name") or payload.get("address")),
            latitude=self._float_or_none(point.get("lat")),
            longitude=self._float_or_none(point.get("lon")),
            categories=self._categories_from_payload(payload),
            description=self._string_or_none(payload.get("description")),
            working_hours=self._string_or_none(payload.get("schedule")),
            branch_info=self._string_or_none(payload.get("org")),
            raw_payload=payload,
            discovered_query=self._string_or_none(row.get("query")),
            discovered_grid_cell_id=int(row["grid_cell_id"]),
            fetched_at=self._string_or_none(row.get("raw_fetched_at")),
        )

    def _classification_from_discovery(
        self,
        row: dict[str, Any],
    ) -> ClassificationResult:
        accepted = row["filter_status"] == "accepted"
        return ClassificationResult(
            accepted=accepted,
            confidence=float(row.get("filter_confidence") or 0.0),
            reason_codes=self._json_list(
                row.get("classifier_reason_codes") or row.get("filter_reasons")
            ),
            business_profile=str(row.get("business_profile") or "unknown"),
            rejection_reason=self._string_or_none(row.get("rejection_reason")),
            decision_name=self._string_or_none(row.get("classifier_decision_name")),
            decision_categories=self._json_list(row.get("classifier_decision_categories")),
        )

    def _input_snapshot(
        self,
        organization: RawOrganization,
        row: dict[str, Any],
        observation_count: int,
    ) -> dict[str, Any]:
        return {
            "source": "salon_discoveries+raw_organization_results",
            "discovery_id": row.get("id"),
            "raw_result_id": row.get("raw_result_id"),
            "external_source": organization.external_source,
            "external_id_present": bool(organization.external_id),
            "name": organization.name,
            "address": organization.address,
            "categories": organization.categories,
            "query": organization.discovered_query,
            "grid_cell_id": organization.discovered_grid_cell_id,
            "observation_count": observation_count,
        }

    def _conflict_decisions(self, rows: list[dict[str, Any]]) -> list[dict[str, object]]:
        grouped: dict[tuple[object, ...], dict[str, object]] = {}

        for row in rows:
            reason_codes = self._json_list(row.get("classifier_reason_codes"))
            key = (
                row.get("filter_status"),
                row.get("rejection_reason"),
                row.get("business_profile"),
                tuple(reason_codes),
            )
            item = grouped.setdefault(
                key,
                {
                    "filter_status": row.get("filter_status"),
                    "rejection_reason": row.get("rejection_reason"),
                    "business_profile": row.get("business_profile"),
                    "reason_codes": reason_codes,
                    "first_discovery_id": row.get("id"),
                    "last_discovery_id": row.get("id"),
                    "queries": set(),
                    "count": 0,
                },
            )
            item["last_discovery_id"] = row.get("id")
            item["count"] = int(item["count"]) + 1

            if row.get("query"):
                item["queries"].add(str(row["query"]))

        result: list[dict[str, object]] = []

        for item in grouped.values():
            result.append(
                {
                    **item,
                    "queries": sorted(item["queries"]),
                }
            )

        result.sort(key=lambda item: int(item["first_discovery_id"] or 0))
        return result

    def _categories_from_payload(self, payload: dict[str, Any]) -> list[str]:
        result: list[str] = []

        for key in ("rubrics", "categories"):
            values = payload.get(key)

            if not isinstance(values, list):
                continue

            for value in values:
                if isinstance(value, dict):
                    name = value.get("name") or value.get("alias")
                    if name:
                        result.append(str(name))
                elif value:
                    result.append(str(value))

        return result

    def _json_object(self, value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        if not isinstance(value, str) or not value:
            return {}

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}

        return parsed if isinstance(parsed, dict) else {}

    def _json_list(self, value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if item]

        if not isinstance(value, str) or not value:
            return []

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []

        if not isinstance(parsed, list):
            return []

        return [str(item) for item in parsed if item]

    def _string_or_none(self, value: object) -> str | None:
        if value is None:
            return None

        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)

        text = str(value).strip()
        return text or None

    def _float_or_none(self, value: object) -> float | None:
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for the offline canonical backfill."""

    parser = argparse.ArgumentParser(
        description="Backfill canonical rejected organizations from stored discoveries."
    )
    parser.add_argument("--region-id", type=int)
    parser.add_argument("--max-records", type=int)
    parser.add_argument("--apply", action="store_true")
    return parser


def main() -> None:
    """Run the offline canonical rejected organization backfill."""

    args = build_parser().parse_args()
    database = Database()
    database.initialize()
    summary = CanonicalOrganizationBackfiller(
        database,
        dry_run=not args.apply,
    ).backfill_rejected(region_id=args.region_id, max_records=args.max_records)

    print(f"Dry-run: {summary.dry_run}")
    print(f"Processed: {summary.processed}")
    print(f"Created: {summary.created}")
    print(f"Updated: {summary.updated}")
    print(f"Unchanged: {summary.unchanged}")
    print(f"Skipped: {summary.skipped}")
    print(f"Conflicts: {summary.conflicts}")

    for change in summary.changes:
        print(
            f"{change.action}: {change.name} "
            f"[{change.external_source}:{change.external_id}] "
            f"{change.previous_status}->{change.new_status} "
            f"reason={change.rejection_reason}"
        )

        if change.conflicting_decisions:
            print(
                "  conflict_decisions="
                f"{json.dumps(change.conflict_decisions, ensure_ascii=False)}"
            )


if __name__ == "__main__":
    main()
