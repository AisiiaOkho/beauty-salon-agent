from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from config.settings import SALON_CLASSIFIER_VERSION
from database_manager import Database
from pricing.models import SERVICE_KEY_BASIC_MANICURE_WITH_COATING

from .models import (
    ExcludedSalon,
    ExportDataset,
    ExportPrice,
    ExportSalon,
    RegionExportSummary,
)


class ExportQueryService:
    """Build export models from current database state without row multiplication."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def load_dataset(self, region_id: int | None = None) -> ExportDataset:
        """Load accepted, rejected, and report data for the export workbook."""

        with self.database.connect() as connection:
            accepted_rows = self._salon_rows(connection, "accepted", region_id)
            rejected_rows = self._salon_rows(connection, "rejected", region_id)
            salon_ids = [int(row["id"]) for row in accepted_rows]
            contacts = self._contacts_by_salon(connection, salon_ids)
            prices = self._prices_by_salon(connection, salon_ids)
            total_regions = int(
                connection.execute(
                    "SELECT COUNT(*) AS total FROM regions"
                ).fetchone()["total"]
            )
            regions_with_grids = int(
                connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM grid_generations
                    WHERE status = 'complete'
                    """
                ).fetchone()["total"]
            )
            region_summaries = self._region_summaries(connection, region_id)

        accepted = [
            self._accepted_from_row(row, contacts.get(int(row["id"]), []), prices.get(int(row["id"])))
            for row in accepted_rows
        ]
        excluded = [self._excluded_from_row(row) for row in rejected_rows]

        return ExportDataset(
            accepted_salons=accepted,
            excluded_salons=excluded,
            region_summaries=region_summaries,
            database_path=str(self.database.db_path),
            total_regions=total_regions,
            regions_with_grids=regions_with_grids,
            classifier_version=SALON_CLASSIFIER_VERSION,
        )

    def _salon_rows(
        self,
        connection: Any,
        status: str,
        region_id: int | None,
    ) -> list[Any]:
        parameters: list[Any] = [status]
        region_filter = ""

        if region_id is not None:
            region_filter = "AND s.region_id = ?"
            parameters.append(region_id)

        return connection.execute(
            f"""
            SELECT
                s.*,
                r.name AS region_name
            FROM salons s
            JOIN regions r ON r.id = s.region_id
            WHERE s.filter_status = ?
              {region_filter}
            ORDER BY r.scan_order, s.name, s.id
            """,
            parameters,
        ).fetchall()

    def _contacts_by_salon(
        self,
        connection: Any,
        salon_ids: list[int],
    ) -> dict[int, list[dict[str, Any]]]:
        if not salon_ids:
            return {}

        placeholders = ",".join("?" for _ in salon_ids)
        rows = connection.execute(
            f"""
            SELECT salon_id, contact_type, display_value, normalized_value
            FROM salon_contacts
            WHERE is_active = 1
              AND salon_id IN ({placeholders})
            ORDER BY salon_id, contact_type, id
            """,
            salon_ids,
        ).fetchall()
        contacts: dict[int, list[dict[str, Any]]] = {}

        for row in rows:
            contacts.setdefault(int(row["salon_id"]), []).append(dict(row))

        return contacts

    def _prices_by_salon(
        self,
        connection: Any,
        salon_ids: list[int],
    ) -> dict[int, ExportPrice]:
        if not salon_ids:
            return {}

        placeholders = ",".join("?" for _ in salon_ids)
        rows = connection.execute(
            f"""
            SELECT *
            FROM salon_prices
            WHERE is_active = 1
              AND service_key = ?
              AND salon_id IN ({placeholders})
            ORDER BY salon_id, id DESC
            """,
            [SERVICE_KEY_BASIC_MANICURE_WITH_COATING, *salon_ids],
        ).fetchall()
        prices: dict[int, ExportPrice] = {}

        for row in rows:
            salon_id = int(row["salon_id"])

            if salon_id in prices:
                continue

            prices[salon_id] = ExportPrice(
                display_value=self._display_price(row),
                currency=row["currency"],
                price_type=row["price_type"],
                service_name=row["service_name_raw"],
                source_type=row["source_type"],
                source_url=row["source_url"],
                status=row["price_type"],
            )

        return prices

    def _region_summaries(
        self,
        connection: Any,
        region_id: int | None,
    ) -> list[RegionExportSummary]:
        parameters: list[Any] = []
        region_filter = ""

        if region_id is not None:
            region_filter = "WHERE r.id = ?"
            parameters.append(region_id)

        rows = connection.execute(
            f"""
            SELECT
                r.id,
                r.name,
                r.status AS last_scan_status,
                SUM(CASE WHEN s.filter_status = 'accepted' THEN 1 ELSE 0 END) AS accepted,
                SUM(CASE WHEN s.filter_status = 'rejected' THEN 1 ELSE 0 END) AS rejected
            FROM regions r
            LEFT JOIN salons s ON s.region_id = r.id
            {region_filter}
            GROUP BY r.id
            ORDER BY r.scan_order
            """,
            parameters,
        ).fetchall()
        summaries: list[RegionExportSummary] = []

        for row in rows:
            accepted_ids = [
                int(item["id"])
                for item in connection.execute(
                    """
                    SELECT id
                    FROM salons
                    WHERE region_id = ?
                      AND filter_status = 'accepted'
                    """,
                    (row["id"],),
                ).fetchall()
            ]
            with_contacts = self._count_with_contacts(connection, accepted_ids)
            with_prices = self._count_with_prices(connection, accepted_ids)
            summaries.append(
                RegionExportSummary(
                    region=row["name"],
                    accepted=int(row["accepted"] or 0),
                    rejected=int(row["rejected"] or 0),
                    with_contacts=with_contacts,
                    with_prices=with_prices,
                    last_scan_status=row["last_scan_status"],
                )
            )

        return summaries

    def _accepted_from_row(
        self,
        row: Any,
        contacts: list[dict[str, Any]],
        price: ExportPrice | None,
    ) -> ExportSalon:
        phones = self._unique(
            contact["display_value"]
            for contact in contacts
            if contact["contact_type"] == "phone"
        )
        links = self._unique(
            contact["display_value"]
            for contact in contacts
            if contact["contact_type"] in ("website", "social")
        )
        price_status = self._price_status(row, price)
        comment = self._comment(row, contacts, price_status)
        last_checked = self._latest_datetime(
            row["details_enriched_at"],
            row["last_seen_at"],
            row["updated_at"],
        )

        return ExportSalon(
            region=row["region_name"],
            city=row["city"],
            name=row["name"],
            address=row["address"],
            phones=phones,
            links=links,
            price=price or ExportPrice(
                display_value=None,
                currency=None,
                price_type="not_checked",
                service_name=None,
                source_type=None,
                source_url=None,
                status=price_status,
            ),
            masters_count=row["masters_count"],
            business_profile=row["business_profile"] or "unknown",
            verification_status=row["verification_status"],
            comment=comment,
            external_source=row["external_source"] or row["source"],
            external_id=row["external_id"],
            first_seen_at=self._parse_datetime(row["first_seen_at"] or row["created_at"]),
            last_checked_at=last_checked,
            classifier_version=row["classifier_version"],
        )

    def _excluded_from_row(self, row: Any) -> ExcludedSalon:
        return ExcludedSalon(
            region=row["region_name"],
            name=row["name"],
            address=row["address"],
            rejection_reason=row["rejection_reason"],
            business_profile=row["business_profile"],
            reason_codes=row["classifier_reason_codes"],
            external_id=row["external_id"],
            classifier_version=row["classifier_version"],
            classified_at=self._parse_datetime(row["classified_at"]),
        )

    def _count_with_contacts(self, connection: Any, salon_ids: list[int]) -> int:
        if not salon_ids:
            return 0

        placeholders = ",".join("?" for _ in salon_ids)
        row = connection.execute(
            f"""
            SELECT COUNT(DISTINCT salon_id) AS total
            FROM salon_contacts
            WHERE is_active = 1
              AND salon_id IN ({placeholders})
            """,
            salon_ids,
        ).fetchone()
        return int(row["total"])

    def _count_with_prices(self, connection: Any, salon_ids: list[int]) -> int:
        if not salon_ids:
            return 0

        placeholders = ",".join("?" for _ in salon_ids)
        row = connection.execute(
            f"""
            SELECT COUNT(DISTINCT salon_id) AS total
            FROM salon_prices
            WHERE is_active = 1
              AND service_key = ?
              AND price_type IN ('exact', 'from', 'range')
              AND salon_id IN ({placeholders})
            """,
            [SERVICE_KEY_BASIC_MANICURE_WITH_COATING, *salon_ids],
        ).fetchone()
        return int(row["total"])

    def _price_status(
        self,
        row: Any,
        price: ExportPrice | None,
    ) -> str:
        if price is not None:
            return price.status

        status = row["verification_status"]

        if status in ("not_found", "ambiguous", "error"):
            return str(status)

        return "not_checked"

    def _comment(
        self,
        row: Any,
        contacts: list[dict[str, Any]],
        price_status: str,
    ) -> str:
        parts = ["Найден и классифицирован"]

        if row["details_status"] == "success":
            parts.append("Карточка 2ГИС проверена")

        if not contacts:
            if row["details_status"] == "success":
                parts.append("контакты и официальный сайт API не предоставил")
            else:
                parts.append("контакты не проверены")

        if price_status == "not_checked":
            parts.append("цена не проверена")
        elif price_status == "not_found":
            parts.append("цена не найдена")
        elif price_status == "ambiguous":
            parts.append("цена требует ручной проверки")
        elif price_status == "error":
            parts.append("ошибка проверки цены")

        return "; ".join(parts) + "."

    def _display_price(self, row: Any) -> str | None:
        price_type = row["price_type"]

        if price_type == "range":
            if row["range_min_minor"] is None or row["range_max_minor"] is None:
                return None

            return f"{int(row['range_min_minor']) // 100}–{int(row['range_max_minor']) // 100}"

        if row["amount_minor"] is None:
            return None

        amount = int(row["amount_minor"]) // 100

        if price_type == "from":
            return f"от {amount}"

        if price_type == "exact":
            return str(amount)

        return None

    def _unique(self, values: Any) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            if not value:
                continue

            key = str(value).strip()

            if not key or key in seen:
                continue

            seen.add(key)
            result.append(key)

        return result

    def _latest_datetime(self, *values: object) -> datetime | None:
        parsed = [value for value in (self._parse_datetime(item) for item in values) if value]
        return max(parsed) if parsed else None

    def _parse_datetime(self, value: object) -> datetime | None:
        if value is None:
            return None

        if isinstance(value, datetime):
            return value

        text = str(value).strip()

        if not text:
            return None

        for candidate in (text, text.replace("Z", "+00:00")):
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed.replace(tzinfo=None)
            except ValueError:
                pass

        try:
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
