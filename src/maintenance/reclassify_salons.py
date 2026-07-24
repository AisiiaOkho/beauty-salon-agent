from __future__ import annotations

import json
from dataclasses import dataclass, field

from config.settings import (
    RECLASSIFICATION_DRY_RUN,
    RECLASSIFICATION_MAX_RECORDS_PER_RUN,
    SALON_CLASSIFIER_VERSION,
)
from database_manager import Database
from filters.salon_classifier import SalonClassifier
from scanner.models import ClassificationResult, RawOrganization


@dataclass(frozen=True)
class ReclassificationChange:
    """One salon classification comparison."""

    salon_id: int
    name: str
    previous_status: str | None
    new_status: str
    previous_business_profile: str | None
    new_business_profile: str
    rejection_reason: str | None
    changed: bool
    reliable: bool
    reason_codes: list[str] = field(default_factory=list)
    issue: str | None = None


@dataclass
class ReclassificationSummary:
    """Counters from one reclassification run."""

    processed: int = 0
    changed: int = 0
    accepted: int = 0
    rejected: int = 0
    unreliable: int = 0
    dry_run: bool = False
    changes: list[ReclassificationChange] = field(default_factory=list)


class SalonReclassifier:
    """Reclassify existing salon rows using the current deterministic classifier."""

    def __init__(
        self,
        database: Database,
        classifier: SalonClassifier | None = None,
        max_records_per_run: int = RECLASSIFICATION_MAX_RECORDS_PER_RUN,
        dry_run: bool = RECLASSIFICATION_DRY_RUN,
        classifier_version: str = SALON_CLASSIFIER_VERSION,
    ) -> None:
        if max_records_per_run < 0:
            raise ValueError("max_records_per_run cannot be negative.")

        self.database = database
        self.classifier = classifier or SalonClassifier()
        self.max_records_per_run = max_records_per_run
        self.dry_run = dry_run
        self.classifier_version = classifier_version

    def reclassify(
        self,
        salon_id: int | None = None,
    ) -> ReclassificationSummary:
        """Reclassify selected existing salon rows."""

        rows = self.database.get_salons_for_reclassification(
            max_records=self.max_records_per_run,
            salon_id=salon_id,
        )
        summary = ReclassificationSummary(dry_run=self.dry_run)

        for row in rows:
            organization, snapshot, reliable, issue = self._organization_from_row(row)
            classification = self.classifier.classify(organization)
            change = self._change_from_result(
                row=row,
                classification=classification,
                reliable=reliable,
                issue=issue,
            )
            summary.processed += 1
            summary.accepted += 1 if classification.accepted else 0
            summary.rejected += 0 if classification.accepted else 1
            summary.changed += 1 if change.changed else 0
            summary.unreliable += 0 if reliable else 1
            summary.changes.append(change)

            if not self.dry_run:
                self.database.save_salon_classification_result(
                    salon_id=int(row["id"]),
                    classification=classification,
                    input_snapshot=snapshot,
                    classifier_version=self.classifier_version,
                )

        return summary

    def _organization_from_row(
        self,
        row: dict[str, object],
    ) -> tuple[RawOrganization, dict[str, object], bool, str | None]:
        payload = self._json_object(row.get("raw_payload"))
        categories = self._categories_from_row(row, payload)
        name = str(payload.get("name") or row.get("name") or "")
        address = self._string_or_none(
            payload.get("address_name")
            or row.get("address")
        )
        point = payload.get("point") if isinstance(payload.get("point"), dict) else {}
        reliable = bool(name and categories)
        issue = None if reliable else "missing_name_or_categories"

        organization = RawOrganization(
            external_source=str(row.get("external_source") or row.get("source") or "2GIS"),
            external_id=self._string_or_none(row.get("external_id")),
            name=name,
            address=address,
            latitude=self._float_or_none(point.get("lat") or row.get("latitude")),
            longitude=self._float_or_none(point.get("lon") or row.get("longitude")),
            phone=self._string_or_none(row.get("phone")),
            website=self._string_or_none(row.get("website")),
            social_links=self._json_list(row.get("social_links")),
            categories=categories,
            description=self._string_or_none(
                payload.get("description") or row.get("description")
            ),
            working_hours=self._string_or_none(payload.get("schedule")),
            branch_info=self._string_or_none(payload.get("org")),
            raw_payload=payload,
            source_url=self._string_or_none(row.get("source_url")),
        )
        snapshot = {
            "salon_id": row.get("id"),
            "name": organization.name,
            "external_source": organization.external_source,
            "external_id_present": bool(organization.external_id),
            "address": organization.address,
            "categories": categories,
            "description": organization.description,
            "source": "salons.raw_payload",
        }
        return organization, snapshot, reliable, issue

    def _categories_from_row(
        self,
        row: dict[str, object],
        payload: dict[str, object],
    ) -> list[str]:
        categories = self._json_list(row.get("categories"))

        if categories:
            return categories

        rubrics = payload.get("rubrics")

        if not isinstance(rubrics, list):
            return []

        result: list[str] = []

        for rubric in rubrics:
            if isinstance(rubric, dict) and rubric.get("name"):
                result.append(str(rubric["name"]))

        return result

    def _change_from_result(
        self,
        *,
        row: dict[str, object],
        classification: ClassificationResult,
        reliable: bool,
        issue: str | None,
    ) -> ReclassificationChange:
        previous_status = self._string_or_none(row.get("filter_status"))
        previous_profile = self._string_or_none(row.get("business_profile"))
        new_status = "accepted" if classification.accepted else "rejected"
        changed = (
            previous_status != new_status
            or previous_profile != classification.business_profile
            or self._string_or_none(row.get("rejection_reason"))
            != classification.rejection_reason
        )

        return ReclassificationChange(
            salon_id=int(row["id"]),
            name=str(row.get("name") or ""),
            previous_status=previous_status,
            new_status=new_status,
            previous_business_profile=previous_profile,
            new_business_profile=classification.business_profile,
            rejection_reason=classification.rejection_reason,
            changed=changed,
            reliable=reliable,
            reason_codes=list(classification.reason_codes),
            issue=issue,
        )

    def _json_object(self, value: object) -> dict[str, object]:
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
