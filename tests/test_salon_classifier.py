from __future__ import annotations

import unittest

from filters.salon_classifier import SalonClassifier
from scanner.models import RawOrganization


class SalonClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = SalonClassifier()

    def test_filtering_accepted_salon(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="1",
                name="Ногтевая студия Лак",
                categories=["Маникюр", "Салоны красоты"],
                description="Маникюр и педикюр",
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.salon_type, "manicure_specialized")

    def test_filtering_home_master(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="2",
                name="Маникюр на дому Анна",
                categories=["Маникюр"],
            )
        )

        self.assertFalse(result.accepted)
        self.assertIn("home_or_private_master_signal", result.reasons)

    def test_filtering_coworking(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="3",
                name="Beauty coworking",
                description="Аренда рабочего места для мастеров маникюра",
            )
        )

        self.assertFalse(result.accepted)
        self.assertIn("coworking_or_rental_signal", result.reasons)

    def test_filtering_beauty_supply_store(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="4",
                name="Магазин материалов для маникюра",
                categories=["Товары для салонов красоты"],
            )
        )

        self.assertFalse(result.accepted)
        self.assertIn("beauty_supply_without_service_signal", result.reasons)


if __name__ == "__main__":
    unittest.main()
