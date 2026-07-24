from __future__ import annotations

import tempfile
import unittest
import urllib.error
from pathlib import Path
from typing import Any

from database_manager import Database
from enrichment.models import OrganizationDetailsResult
from enrichment.organization_enricher import OrganizationEnricher
from filters.salon_classifier import SalonClassifier
from providers.twogis_client import TwoGisPlacesClient
from scanner.models import RawOrganization


def details_payload(
    *,
    external_id: str = "branch-1",
    contacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload_contacts = contacts

    if payload_contacts is None:
        payload_contacts = [
            {"type": "phone", "value": "+7 4012 11-22-33"},
            {"type": "phone", "value": "+7 (4012) 11-22-33"},
            {"type": "website", "value": "example.ru/beauty"},
            {"type": "website", "value": "vk.com/beauty"},
            {"type": "email", "value": "hello@example.ru"},
        ]

    return {
        "meta": {"code": 200},
        "result": {
            "items": [
                {
                    "id": external_id,
                    "name": "Студия маникюра Лак",
                    "full_address_name": "Калининград, Ленинский проспект, 1",
                    "point": {"lat": 54.7104, "lon": 20.4522},
                    "contact_groups": [{"contacts": payload_contacts}],
                    "rubrics": [{"name": "Ногтевые студии"}],
                    "schedule": {"Mon": {"working_hours": [{"from": "09:00"}]}},
                    "org": {"id": "org-1"},
                    "description": "Маникюр и педикюр",
                    "updated_at": "2026-07-01T12:00:00+03:00",
                }
            ]
        },
    }


class StaticDetailsClient:
    def __init__(self, results: list[OrganizationDetailsResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    def get_organization_details(
        self,
        external_id: str,
        salon_id: int | None = None,
    ) -> OrganizationDetailsResult:
        del salon_id
        self.calls.append(external_id)
        return self.results.pop(0)


class EnrichmentDatabaseMixin:
    def make_database(self, directory: str) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        return database

    def insert_salon(
        self,
        database: Database,
        external_id: str | None = "branch-1",
        name: str = "Студия маникюра Лак",
        accepted: bool = True,
    ) -> int:
        organization = RawOrganization(
            external_source="2GIS",
            external_id=external_id,
            name=name,
            address="Ленина, 1",
            latitude=54.71,
            longitude=20.45,
            categories=["Ногтевые студии"],
            raw_payload={"id": external_id, "name": name},
        )
        classification = SalonClassifier().classify(organization)

        if accepted:
            salon_id, _ = database.upsert_salon(
                region_id=1,
                organization=organization,
                classification=classification,
            )
            return salon_id

        with database.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO salons (
                    region_id,
                    external_source,
                    source,
                    external_id,
                    name,
                    filter_status
                )
                VALUES (1, '2GIS', '2GIS', ?, ?, 'rejected')
                """,
                (external_id, name),
            )
            connection.commit()

        return int(cursor.lastrowid)

    def table_count(self, database: Database, table_name: str) -> int:
        with database.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM {table_name}"
            ).fetchone()

        return int(row["total"])


class ParsedDetailsClient(TwoGisPlacesClient):
    def __init__(self, payloads: list[tuple[dict[str, Any], int]]) -> None:
        super().__init__(
            api_key="test",
            delay_seconds=0,
            backoff_seconds=0,
            progress_logger=lambda message: None,
        )
        self.payloads = payloads
        self.calls = 0

    def _request_details_json(
        self,
        *,
        url: str,
        external_id: str,
    ) -> tuple[dict[str, Any], int | None]:
        del url, external_id
        self.calls += 1
        return self.payloads.pop(0)


class RetryDetailsClient(TwoGisPlacesClient):
    def __init__(self) -> None:
        super().__init__(
            api_key="test",
            delay_seconds=0,
            backoff_seconds=0,
            progress_logger=lambda message: None,
        )
        self.calls = 0

    def _perform_request_with_status(
        self,
        url: str,
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], int]:
        self.calls += 1

        if self.calls == 1:
            raise urllib.error.HTTPError(
                url=url,
                code=429,
                msg="rate limited",
                hdrs={},
                fp=None,
            )

        return details_payload(), 200


class OrganizationDetailsParserTests(unittest.TestCase):
    def test_success_payload_parses_contacts_and_deduplicates_phone(self) -> None:
        client = ParsedDetailsClient([(details_payload(), 200)])

        result = client.get_organization_details("branch-1")

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.details)
        self.assertEqual(result.http_status, 200)
        self.assertEqual(result.payload_code, 200)
        self.assertEqual(result.details.name, "Студия маникюра Лак")
        self.assertEqual(result.details.full_address, "Калининград, Ленинский проспект, 1")
        self.assertEqual(result.details.categories, ["Ногтевые студии"])
        self.assertEqual(len(result.details.contacts), 4)
        self.assertNotIn("key=", result.sanitized_source_url)

    def test_missing_contact_groups_is_valid(self) -> None:
        client = ParsedDetailsClient([(details_payload(contacts=[]), 200)])

        result = client.get_organization_details("branch-1")

        self.assertEqual(result.status, "success")
        self.assertEqual(result.details.contacts, [])

    def test_not_found_payload(self) -> None:
        client = ParsedDetailsClient(
            [({"meta": {"code": 404}, "result": {"items": []}}, 200)]
        )

        result = client.get_organization_details("missing")

        self.assertEqual(result.status, "not_found")

    def test_unauthorized_payload(self) -> None:
        client = ParsedDetailsClient(
            [({"meta": {"code": 403}, "result": {"items": []}}, 200)]
        )

        result = client.get_organization_details("branch-1")

        self.assertEqual(result.status, "unauthorized")

    def test_rate_limit_retries(self) -> None:
        client = RetryDetailsClient()

        result = client.get_organization_details("branch-1")

        self.assertEqual(result.status, "success")
        self.assertEqual(client.calls, 2)

    def test_malformed_payload_returns_parser_error(self) -> None:
        client = ParsedDetailsClient([({"meta": {"code": 200}, "result": {}}, 200)])

        result = client.get_organization_details("branch-1")

        self.assertEqual(result.status, "parser_error")


class OrganizationEnricherTests(EnrichmentDatabaseMixin, unittest.TestCase):
    def test_enrichment_persists_details_and_contacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            result = ParsedDetailsClient([(details_payload(), 200)]).get_organization_details(
                "branch-1"
            )
            enricher = OrganizationEnricher(
                database=database,
                details_client=StaticDetailsClient([result]),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = enricher.enrich_salon_id(salon_id)

            self.assertEqual(summary.succeeded, 1)
            self.assertEqual(summary.contacts_created, 4)
            self.assertEqual(self.table_count(database, "organization_detail_results"), 1)
            self.assertEqual(self.table_count(database, "salon_contacts"), 4)

            with database.connect() as connection:
                salon = connection.execute(
                    "SELECT details_status, address FROM salons WHERE id = ?",
                    (salon_id,),
                ).fetchone()

            self.assertEqual(salon["details_status"], "success")
            self.assertEqual(salon["address"], "Калининград, Ленинский проспект, 1")

    def test_same_salon_twice_updates_contacts_without_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            first = ParsedDetailsClient([(details_payload(), 200)]).get_organization_details(
                "branch-1"
            )
            second = ParsedDetailsClient([(details_payload(), 200)]).get_organization_details(
                "branch-1"
            )
            enricher = OrganizationEnricher(
                database=database,
                details_client=StaticDetailsClient([first, second]),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            first_summary = enricher.enrich_salon_id(salon_id)
            second_summary = enricher.enrich_salon_id(salon_id)

            self.assertEqual(first_summary.contacts_created, 4)
            self.assertEqual(second_summary.contacts_created, 0)
            self.assertEqual(second_summary.contacts_updated, 4)
            self.assertEqual(self.table_count(database, "salon_contacts"), 4)
            self.assertEqual(self.table_count(database, "organization_detail_results"), 2)

    def test_changed_contact_marks_missing_contact_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            first = ParsedDetailsClient(
                [
                    (
                        details_payload(
                            contacts=[
                                {"type": "phone", "value": "+7 4012 11-22-33"},
                            ]
                        ),
                        200,
                    )
                ]
            ).get_organization_details("branch-1")
            second = ParsedDetailsClient(
                [
                    (
                        details_payload(
                            contacts=[
                                {"type": "phone", "value": "+7 4012 44-55-66"},
                            ]
                        ),
                        200,
                    )
                ]
            ).get_organization_details("branch-1")
            enricher = OrganizationEnricher(
                database=database,
                details_client=StaticDetailsClient([first, second]),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            enricher.enrich_salon_id(salon_id)
            summary = enricher.enrich_salon_id(salon_id)

            self.assertEqual(summary.contacts_created, 1)
            self.assertEqual(summary.contacts_deactivated, 1)

            with database.connect() as connection:
                inactive = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM salon_contacts
                    WHERE salon_id = ?
                      AND is_active = 0
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(int(inactive["total"]), 1)

    def test_failed_details_are_audited_and_status_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            result = OrganizationDetailsResult(
                external_source="2GIS",
                external_id="branch-1",
                status="not_found",
                http_status=200,
                payload_code=404,
                sanitized_source_url="https://catalog.api.2gis.com/3.0/items/byid?id=branch-1",
                raw_payload={"meta": {"code": 404}},
                error_message="not found",
            )
            enricher = OrganizationEnricher(
                database=database,
                details_client=StaticDetailsClient([result]),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = enricher.enrich_salon_id(salon_id)

            self.assertEqual(summary.failed, 1)
            self.assertEqual(self.table_count(database, "organization_detail_results"), 1)

            with database.connect() as connection:
                salon = connection.execute(
                    "SELECT details_status, details_error FROM salons WHERE id = ?",
                    (salon_id,),
                ).fetchone()

            self.assertEqual(salon["details_status"], "not_found")
            self.assertEqual(salon["details_error"], "not found")

    def test_rejected_and_missing_external_id_salons_are_not_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_salon(database, external_id="rejected", accepted=False)
            self.insert_salon(database, external_id=None, accepted=True)

            next_salon = database.get_next_salon_for_enrichment(
                refresh_after_days=30
            )

            self.assertIsNone(next_salon)

    def test_dry_run_does_not_call_provider_or_persist_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            client = StaticDetailsClient([])
            enricher = OrganizationEnricher(
                database=database,
                details_client=client,
                dry_run=True,
                progress_logger=lambda message: None,
            )

            summary = enricher.enrich_salon_id(salon_id)

            self.assertEqual(summary.skipped, 1)
            self.assertEqual(client.calls, [])
            self.assertEqual(self.table_count(database, "organization_detail_results"), 0)

    def test_one_organization_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_salon(database, external_id="branch-1")
            self.insert_salon(database, external_id="branch-2", name="Студия два")
            result = ParsedDetailsClient([(details_payload(), 200)]).get_organization_details(
                "branch-1"
            )
            client = StaticDetailsClient([result])
            enricher = OrganizationEnricher(
                database=database,
                details_client=client,
                max_organizations_per_run=1,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = enricher.enrich_next()

            self.assertEqual(summary.processed, 1)
            self.assertEqual(client.calls, ["branch-1"])


if __name__ == "__main__":
    unittest.main()
