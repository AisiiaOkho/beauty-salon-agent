from __future__ import annotations

from scanner.models import ClassificationResult, RawOrganization
from utils.normalization import normalize_text


class SalonClassifier:
    """Rule-based manicure salon classifier."""

    MANICURE_SIGNALS = (
        "маникюр",
        "ногт",
        "nail",
        "педикюр",
        "шеллак",
        "гель лак",
    )
    SALON_SIGNALS = (
        "салон",
        "студия",
        "beauty",
        "красот",
        "nail studio",
        "центр",
    )
    SPECIALIZED_SIGNALS = (
        "ногтевая студия",
        "студия маникюра",
        "nail studio",
        "маникюр",
    )
    HOME_MASTER_SIGNALS = (
        "частный мастер",
        "мастер на дому",
        "на дому",
        "home master",
        "частная",
    )
    COWORKING_SIGNALS = (
        "коворкинг",
        "coworking",
        "аренда рабочего места",
        "аренда места",
        "аренда кабинета",
        "аренда кресла",
    )
    SCHOOL_ONLY_SIGNALS = (
        "школа",
        "курсы",
        "обучение",
        "academy",
        "training",
    )
    SUPPLY_STORE_SIGNALS = (
        "магазин",
        "товары",
        "материалы",
        "оборудование",
        "поставщик",
        "shop",
        "store",
    )

    def classify(self, organization: RawOrganization) -> ClassificationResult:
        """Classify one raw organization without external services."""

        text = self._organization_text(organization)
        reasons: list[str] = []

        if self._contains(text, self.COWORKING_SIGNALS):
            return ClassificationResult(
                accepted=False,
                confidence=0.95,
                reasons=["coworking_or_rental_signal"],
                salon_type="unknown",
            )

        if self._contains(text, self.HOME_MASTER_SIGNALS):
            return ClassificationResult(
                accepted=False,
                confidence=0.9,
                reasons=["home_or_private_master_signal"],
                salon_type="unknown",
            )

        has_manicure = self._contains(text, self.MANICURE_SIGNALS)
        has_salon = self._contains(text, self.SALON_SIGNALS)
        name_text = normalize_text(organization.name) or ""
        name_has_salon = self._contains(name_text, self.SALON_SIGNALS)
        school_only = self._contains(text, self.SCHOOL_ONLY_SIGNALS) and not has_salon
        supply_only = (
            self._contains(text, self.SUPPLY_STORE_SIGNALS)
            and not name_has_salon
        )

        if school_only:
            return ClassificationResult(
                accepted=False,
                confidence=0.85,
                reasons=["training_only_signal"],
                salon_type="unknown",
            )

        if supply_only:
            return ClassificationResult(
                accepted=False,
                confidence=0.85,
                reasons=["beauty_supply_without_service_signal"],
                salon_type="unknown",
            )

        if not has_manicure:
            return ClassificationResult(
                accepted=False,
                confidence=0.75,
                reasons=["no_manicure_signal"],
                salon_type="unknown",
            )

        if not has_salon:
            return ClassificationResult(
                accepted=False,
                confidence=0.65,
                reasons=["no_salon_or_studio_signal"],
                salon_type="unknown",
            )

        reasons.extend(["manicure_signal", "salon_or_studio_signal"])
        salon_type = (
            "manicure_specialized"
            if self._contains(text, self.SPECIALIZED_SIGNALS)
            else "mixed_beauty_salon"
        )

        return ClassificationResult(
            accepted=True,
            confidence=0.9 if salon_type == "manicure_specialized" else 0.8,
            reasons=reasons,
            salon_type=salon_type,
        )

    def _organization_text(self, organization: RawOrganization) -> str:
        values = [
            organization.name,
            organization.address or "",
            organization.description or "",
            " ".join(organization.categories),
        ]

        return normalize_text(" ".join(values)) or ""

    def _contains(self, text: str, needles: tuple[str, ...]) -> bool:
        return any((normalize_text(needle) or "") in text for needle in needles)
