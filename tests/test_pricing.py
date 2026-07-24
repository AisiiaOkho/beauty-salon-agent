from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from database_manager import Database
from filters.salon_classifier import SalonClassifier
from pricing.models import PriceExtractionResult
from pricing.price_extractor import PriceExtractor, PricingSourceError, WebsiteFetcher
from pricing.price_normalizer import PriceNormalizer
from pricing.service_matcher import ServiceMatcher
from scanner.models import RawOrganization


class FakeWebsiteFetcher:
    def __init__(self, pages: list[tuple[str, str]] | None = None) -> None:
        self.pages = pages or []
        self.calls: list[str] = []

    def fetch_pages(self, url: str) -> list[tuple[str, str]]:
        self.calls.append(url)
        return self.pages


class ErrorWebsiteFetcher:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch_pages(self, url: str) -> list[tuple[str, str]]:
        del url
        raise self.error


class PricingDatabaseMixin:
    def make_database(self, directory: str) -> Database:
        database = Database(db_path=Path(directory) / "test.db")
        database.create_tables()
        database.sync_regions()
        return database

    def insert_salon(
        self,
        database: Database,
        website: str | None = None,
        accepted: bool = True,
    ) -> int:
        organization = RawOrganization(
            external_source="2GIS",
            external_id="branch-1",
            name="Студия маникюра Лак",
            address="Ленина, 1",
            latitude=54.71,
            longitude=20.45,
            website=website,
            categories=["Ногтевые студии"],
            raw_payload={"id": "branch-1"},
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
                VALUES (1, '2GIS', '2GIS', 'rejected', 'Rejected', 'rejected')
                """
            )
            connection.commit()

        return int(cursor.lastrowid)

    def table_count(self, database: Database, table_name: str) -> int:
        with database.connect() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM {table_name}"
            ).fetchone()

        return int(row["total"])


class ServiceMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.matcher = ServiceMatcher()

    def test_exact_manicure_with_coating(self) -> None:
        match = self.matcher.match("Маникюр с покрытием гель-лак")

        self.assertEqual(match.status, "matched")
        self.assertEqual(match.confidence, "high")

    def test_manicure_without_coating_excluded(self) -> None:
        match = self.matcher.match("Маникюр классический")

        self.assertEqual(match.status, "excluded")
        self.assertIn("manicure_without_coating_signal", match.reason_codes)

    def test_coating_only_is_ambiguous(self) -> None:
        match = self.matcher.match("Покрытие гель-лак")

        self.assertEqual(match.status, "ambiguous")

    def test_pedicure_excluded(self) -> None:
        match = self.matcher.match("Педикюр с покрытием")

        self.assertEqual(match.status, "excluded")

    def test_package_ambiguous(self) -> None:
        match = self.matcher.match("Комплекс руки")

        self.assertEqual(match.status, "ambiguous")


class PriceNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = PriceNormalizer()

    def test_exact_price(self) -> None:
        price = self.normalizer.normalize("Маникюр с покрытием — 1 800 ₽")

        self.assertEqual(price.price_type, "exact")
        self.assertEqual(price.amount_minor, 180000)
        self.assertEqual(price.currency, "RUB")

    def test_from_price(self) -> None:
        price = self.normalizer.normalize("от 1500 руб.")

        self.assertEqual(price.price_type, "from")
        self.assertEqual(price.amount_minor, 150000)
        self.assertEqual(price.range_min_minor, 150000)

    def test_range_price(self) -> None:
        price = self.normalizer.normalize("1500–1900 ₽")

        self.assertEqual(price.price_type, "range")
        self.assertEqual(price.range_min_minor, 150000)
        self.assertEqual(price.range_max_minor, 190000)


class PriceExtractorTests(PricingDatabaseMixin, unittest.TestCase):
    def test_website_json_ld(self) -> None:
        page = """
        <script type="application/ld+json">
        {
          "@type": "Service",
          "name": "Маникюр с покрытием гель-лак",
          "offers": {"price": "1800"}
        }
        </script>
        """

        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", page)]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.found, 1)
            self.assertEqual(self.table_count(database, "price_check_results"), 1)
            self.assertEqual(self.table_count(database, "salon_prices"), 1)

    def test_website_direct_text_association(self) -> None:
        page = "<html><body>Маникюр + покрытие 1500–1900 ₽</body></html>"

        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", page)]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.found, 1)
            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT price_type, range_min_minor, range_max_minor
                    FROM salon_prices
                    WHERE salon_id = ?
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["price_type"], "range")
            self.assertEqual(row["range_min_minor"], 150000)
            self.assertEqual(row["range_max_minor"], 190000)

    def test_unrelated_numbers_not_interpreted_as_prices(self) -> None:
        page = "<html><body>Работаем с 9 до 21 каждый день</body></html>"

        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", page)]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.not_found, 1)
            self.assertEqual(self.table_count(database, "salon_prices"), 0)

    def test_no_website_and_no_provider_price_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database)
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.not_found, 1)
            self.assertEqual(self.table_count(database, "price_check_results"), 1)

    def test_duplicate_price_on_rerun(self) -> None:
        page = "<html><body>Маникюр с покрытием — 1800 ₽</body></html>"

        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", page)]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            extractor.extract_salon_id(salon_id)
            extractor.extract_salon_id(salon_id)

            self.assertEqual(self.table_count(database, "price_check_results"), 2)
            self.assertEqual(self.table_count(database, "salon_prices"), 1)

            with database.connect() as connection:
                active = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM salon_prices
                    WHERE salon_id = ?
                      AND is_active = 1
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(int(active["total"]), 1)

    def test_changed_price_on_refresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", "Маникюр с покрытием — 1800 ₽")]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )
            extractor.extract_salon_id(salon_id)
            extractor.website_fetcher = FakeWebsiteFetcher(
                [("https://example.test", "Маникюр с покрытием — 2000 ₽")]
            )

            extractor.extract_salon_id(salon_id)

            self.assertEqual(self.table_count(database, "salon_prices"), 2)
            with database.connect() as connection:
                active = connection.execute(
                    """
                    SELECT amount_minor
                    FROM salon_prices
                    WHERE salon_id = ?
                      AND is_active = 1
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(active["amount_minor"], 200000)

    def test_removed_price_becomes_inactive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(
                    [("https://example.test", "Маникюр с покрытием — 1800 ₽")]
                ),
                dry_run=False,
                progress_logger=lambda message: None,
            )
            extractor.extract_salon_id(salon_id)
            extractor.website_fetcher = FakeWebsiteFetcher(
                [("https://example.test", "Маникюр классический — 900 ₽")]
            )

            extractor.extract_salon_id(salon_id)

            with database.connect() as connection:
                active = connection.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM salon_prices
                    WHERE salon_id = ?
                      AND is_active = 1
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(int(active["total"]), 0)

    def test_provider_structured_price_preferred(self) -> None:
        payload = {
            "result": {
                "items": [
                    {
                        "services": [
                            {
                                "name": "Маникюр с покрытием",
                                "price": "1700 ₽",
                            }
                        ]
                    }
                ]
            }
        }

        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            with database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO organization_detail_results (
                        external_source,
                        external_id,
                        salon_id,
                        status,
                        sanitized_source_url,
                        raw_payload_json,
                        parser_version
                    )
                    VALUES ('2GIS', 'branch-1', ?, 'success', 'https://2gis.test', ?, 'test')
                    """,
                    (salon_id, __import__("json").dumps(payload, ensure_ascii=False)),
                )
                connection.commit()
            fetcher = FakeWebsiteFetcher(
                [("https://example.test", "Маникюр с покрытием — 1900 ₽")]
            )
            extractor = PriceExtractor(
                database,
                website_fetcher=fetcher,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.found, 1)
            self.assertEqual(fetcher.calls, [])

    def test_website_error_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            extractor = PriceExtractor(
                database,
                website_fetcher=ErrorWebsiteFetcher(PricingSourceError("timeout")),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.errors, 1)
            with database.connect() as connection:
                row = connection.execute(
                    """
                    SELECT status, error_message
                    FROM price_check_results
                    WHERE salon_id = ?
                    """,
                    (salon_id,),
                ).fetchone()

            self.assertEqual(row["status"], "error")
            self.assertEqual(row["error_message"], "timeout")

    def test_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            salon_id = self.insert_salon(database, website="https://example.test")
            fetcher = FakeWebsiteFetcher()
            extractor = PriceExtractor(
                database,
                website_fetcher=fetcher,
                dry_run=True,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_salon_id(salon_id)

            self.assertEqual(summary.skipped, 1)
            self.assertEqual(fetcher.calls, [])
            self.assertEqual(self.table_count(database, "price_check_results"), 0)

    def test_one_salon_limit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_salon(database, website="https://one.test")
            self.insert_salon(database, website="https://two.test")
            fetcher = FakeWebsiteFetcher(
                [("https://one.test", "Маникюр с покрытием — 1800 ₽")]
            )
            extractor = PriceExtractor(
                database,
                website_fetcher=fetcher,
                max_salons_per_run=1,
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_next()

            self.assertEqual(summary.processed, 1)
            self.assertEqual(len(fetcher.calls), 1)

    def test_no_accepted_salon(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = self.make_database(directory)
            self.insert_salon(database, accepted=False)
            extractor = PriceExtractor(
                database,
                website_fetcher=FakeWebsiteFetcher(),
                dry_run=False,
                progress_logger=lambda message: None,
            )

            summary = extractor.extract_next()

            self.assertEqual(summary.processed, 0)


class WebsiteFetcherSafetyTests(unittest.TestCase):
    def test_unsupported_url_scheme(self) -> None:
        fetcher = WebsiteFetcher()

        with self.assertRaises(PricingSourceError):
            fetcher.fetch_pages("ftp://example.test/prices")

    def test_oversized_response(self) -> None:
        class OversizedFetcher(WebsiteFetcher):
            def _fetch_one(self, url: str) -> str:
                del url
                raise PricingSourceError("Website response exceeds size limit.")

        with self.assertRaises(PricingSourceError):
            OversizedFetcher().fetch_pages("https://example.test")

    def test_timeout(self) -> None:
        class TimeoutFetcher(WebsiteFetcher):
            def _fetch_one(self, url: str) -> str:
                del url
                raise PricingSourceError("timed out")

        with self.assertRaises(PricingSourceError):
            TimeoutFetcher().fetch_pages("https://example.test")

    def test_redirect_limit(self) -> None:
        class RedirectFetcher(WebsiteFetcher):
            def _fetch_one(self, url: str) -> str:
                del url
                raise PricingSourceError("Website redirect limit exceeded.")

        with self.assertRaises(PricingSourceError):
            RedirectFetcher().fetch_pages("https://example.test")


if __name__ == "__main__":
    unittest.main()
