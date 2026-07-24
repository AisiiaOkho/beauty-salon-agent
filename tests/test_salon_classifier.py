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
        self.assertEqual(result.business_profile, "nail_specialist")
        self.assertIn("manicure_signal", result.reason_codes)

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
        self.assertIn("home_or_private_master_signal", result.reason_codes)
        self.assertEqual(result.rejection_reason, "home_or_private_master")

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
        self.assertIn("coworking_or_rental_signal", result.reason_codes)

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
        self.assertIn("beauty_supply_without_service_signal", result.reason_codes)

    def test_fitness_club_with_nail_category_is_rejected(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="5",
                name="Xfit, фитнес-клуб",
                categories=["Ногтевые студии", "Фитнес-клубы", "Массажист"],
            )
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.business_profile, "mixed_non_salon")
        self.assertEqual(result.rejection_reason, "mixed_non_salon")

    def test_hotel_with_manicure_service_is_rejected(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="6",
                name="Балтика, отель",
                categories=["Отели", "Ногтевые студии"],
                description="Маникюр в spa-зоне",
            )
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "mixed_non_salon")

    def test_standalone_salon_inside_hotel_name_is_accepted(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="7",
                name="Beauty Studio, студия красоты",
                categories=["Отели", "Ногтевые студии", "Косметолог"],
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.business_profile, "mixed_beauty_salon")

    def test_beauty_salon_with_hair_and_nail_categories_is_accepted(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="8",
                name="Чуб&Чёлка, салон красоты",
                categories=["Ногтевые студии", "Парикмахерские", "Косметолог"],
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.business_profile, "mixed_beauty_salon")

    def test_nail_studio_with_training_category_is_accepted(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="9",
                name="K-Studio, студия маникюра и педикюра",
                categories=[
                    "Ногтевые студии",
                    "Обучение мастеров для салонов красоты",
                ],
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.business_profile, "nail_specialist")

    def test_cosmetology_studio_with_nail_category_is_accepted(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="10",
                name="Beauty Space 107, студия красоты",
                categories=[
                    "Ногтевые студии",
                    "Косметолог",
                    "Оформление бровей и ресниц",
                ],
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.business_profile, "mixed_beauty_salon")

    def test_barber_shop_with_incidental_manicure_category_is_rejected(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="11",
                name="Old Boy, барбершоп",
                categories=["Барбершопы", "Ногтевые студии"],
            )
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "mixed_non_salon")

    def test_generic_organization_with_only_nail_category_is_accepted(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="12",
                name="Лак",
                categories=["Ногтевые студии"],
            )
        )

        self.assertTrue(result.accepted)
        self.assertEqual(result.business_profile, "nail_specialist")

    def test_organization_with_no_manicure_signal_is_rejected(self) -> None:
        result = self.classifier.classify(
            RawOrganization(
                external_source="2GIS",
                external_id="13",
                name="Салон красоты Волна",
                categories=["Парикмахерские", "Косметолог"],
            )
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.rejection_reason, "no_manicure_signal")

    def test_smoke_examples_remain_accepted(self) -> None:
        examples = [
            (
                "Чуб&Чёлка, салон красоты",
                ["Ногтевые студии", "Парикмахерские", "Косметолог"],
            ),
            (
                "Beauty Space 107, студия красоты",
                [
                    "Ногтевые студии",
                    "Парикмахерские",
                    "Оформление бровей и ресниц",
                ],
            ),
            (
                "K-Studio, студия маникюра и педикюра",
                [
                    "Ногтевые студии",
                    "Обучение мастеров для салонов красоты",
                ],
            ),
            ("Only nails, салон", ["Ногтевые студии", "Косметолог"]),
        ]

        for name, categories in examples:
            with self.subTest(name=name):
                result = self.classifier.classify(
                    RawOrganization(
                        external_source="2GIS",
                        external_id="example",
                        name=name,
                        categories=categories,
                    )
                )

                self.assertTrue(result.accepted)


if __name__ == "__main__":
    unittest.main()
