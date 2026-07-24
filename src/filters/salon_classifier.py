from __future__ import annotations

from scanner.models import ClassificationResult, RawOrganization
from utils.normalization import normalize_text


class SalonClassifier:
    """Rule-based manicure salon classifier with explainable category groups."""

    STRONG_MANICURE_CATEGORIES = (
        "ногтевые студии",
        "маникюр",
        "педикюр",
        "nail studio",
        "nail salon",
    )
    ALLOWED_BEAUTY_PRIMARY_CATEGORIES = (
        "салон красоты",
        "салоны красоты",
        "студия красоты",
        "парикмахерская",
        "парикмахерские",
        "косметолог",
        "оформление бровей и ресниц",
        "spa",
        "спа",
        "beauty studio",
    )
    UNRELATED_PRIMARY_CATEGORIES = (
        "фитнес клуб",
        "фитнес клубы",
        "спортивный клуб",
        "спортивные клубы",
        "гостиница",
        "гостиницы",
        "отель",
        "отели",
        "торговый центр",
        "торговые центры",
        "медицинский центр",
        "медицинские центры",
        "стоматология",
        "стоматологии",
        "барбершоп",
        "барбершопы",
        "коворкинг",
        "коворкинги",
        "учебный центр",
        "учебные центры",
        "магазин",
        "магазины",
        "сауна",
        "сауны",
        "баня",
        "бани",
    )
    CLEAR_NAIL_NAME_SIGNALS = (
        "маникюр",
        "ногт",
        "nail",
        "педикюр",
    )
    CLEAR_BEAUTY_NAME_SIGNALS = (
        "салон красоты",
        "студия красоты",
        "beauty studio",
        "beauty space",
        "красот",
    )
    GENERIC_SALON_NAME_SIGNALS = (
        "салон",
        "студия",
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
    TRAINING_SIGNALS = (
        "школа",
        "курсы",
        "обучение",
        "academy",
        "training",
        "учебный центр",
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

        name_text = normalize_text(organization.name) or ""
        category_text = normalize_text(" ".join(organization.categories)) or ""
        description_text = normalize_text(organization.description) or ""
        address_text = normalize_text(organization.address) or ""
        all_text = " ".join(
            value
            for value in (
                name_text,
                category_text,
                description_text,
                address_text,
            )
            if value
        )
        reason_codes: list[str] = []
        manicure_signal = (
            self._contains(category_text, self.STRONG_MANICURE_CATEGORIES)
            or self._contains(name_text, self.CLEAR_NAIL_NAME_SIGNALS)
            or self._contains(description_text, self.CLEAR_NAIL_NAME_SIGNALS)
        )
        allowed_beauty_category = self._contains(
            category_text,
            self.ALLOWED_BEAUTY_PRIMARY_CATEGORIES,
        )
        unrelated_category = self._contains(
            category_text,
            self.UNRELATED_PRIMARY_CATEGORIES,
        )
        unrelated_name = self._contains(
            name_text,
            self.UNRELATED_PRIMARY_CATEGORIES,
        )
        clear_nail_name = self._contains(name_text, self.CLEAR_NAIL_NAME_SIGNALS)
        clear_beauty_name = self._contains(name_text, self.CLEAR_BEAUTY_NAME_SIGNALS)
        generic_salon_name = self._contains(name_text, self.GENERIC_SALON_NAME_SIGNALS)
        standalone_salon_name = clear_nail_name or clear_beauty_name or generic_salon_name

        if self._contains(all_text, self.COWORKING_SIGNALS):
            return self._reject(
                organization,
                reason_codes=["coworking_or_rental_signal"],
                rejection_reason="coworking_or_rental",
                confidence=0.95,
            )

        if self._contains(all_text, self.HOME_MASTER_SIGNALS):
            return self._reject(
                organization,
                reason_codes=["home_or_private_master_signal"],
                rejection_reason="home_or_private_master",
                confidence=0.9,
            )

        if not manicure_signal:
            return self._reject(
                organization,
                reason_codes=["no_manicure_signal"],
                rejection_reason="no_manicure_signal",
                confidence=0.75,
            )

        reason_codes.append("manicure_signal")

        if unrelated_name and unrelated_category and not clear_beauty_name and not clear_nail_name:
            return self._reject(
                organization,
                reason_codes=[
                    *reason_codes,
                    "unrelated_primary_name_signal",
                    "unrelated_primary_category_signal",
                ],
                rejection_reason="mixed_non_salon",
                confidence=0.9,
                business_profile="mixed_non_salon",
            )

        if self._is_training_only(
            all_text=all_text,
            allowed_beauty_category=allowed_beauty_category,
            standalone_salon_name=standalone_salon_name,
        ):
            return self._reject(
                organization,
                reason_codes=[*reason_codes, "training_only_signal"],
                rejection_reason="training_only",
                confidence=0.85,
            )

        if self._is_supply_only(
            all_text=all_text,
            allowed_beauty_category=allowed_beauty_category,
            standalone_salon_name=clear_beauty_name or generic_salon_name,
        ):
            return self._reject(
                organization,
                reason_codes=[*reason_codes, "beauty_supply_without_service_signal"],
                rejection_reason="beauty_supply_without_service",
                confidence=0.85,
            )

        if clear_nail_name:
            return self._accept(
                organization,
                reason_codes=[*reason_codes, "nail_name_signal"],
                business_profile="nail_specialist",
                confidence=0.92,
            )

        if clear_beauty_name or generic_salon_name:
            return self._accept(
                organization,
                reason_codes=[*reason_codes, "salon_or_studio_name_signal"],
                business_profile=(
                    "nail_specialist"
                    if self._contains(name_text, ("ногтевая студия", "nail studio"))
                    else "mixed_beauty_salon"
                ),
                confidence=0.88,
            )

        if allowed_beauty_category and not unrelated_category:
            return self._accept(
                organization,
                reason_codes=[*reason_codes, "allowed_beauty_category_signal"],
                business_profile="mixed_beauty_salon",
                confidence=0.82,
            )

        if allowed_beauty_category and unrelated_category:
            return self._reject(
                organization,
                reason_codes=[
                    *reason_codes,
                    "allowed_beauty_category_signal",
                    "unrelated_primary_category_signal",
                ],
                rejection_reason="mixed_non_salon",
                confidence=0.72,
                business_profile="mixed_non_salon",
            )

        if self._contains(category_text, self.STRONG_MANICURE_CATEGORIES):
            return self._accept(
                organization,
                reason_codes=[*reason_codes, "strong_manicure_category_signal"],
                business_profile="nail_specialist",
                confidence=0.78,
            )

        return self._reject(
            organization,
            reason_codes=[*reason_codes, "no_salon_or_studio_signal"],
            rejection_reason="no_salon_or_studio_signal",
            confidence=0.65,
        )

    def _is_training_only(
        self,
        *,
        all_text: str,
        allowed_beauty_category: bool,
        standalone_salon_name: bool,
    ) -> bool:
        return (
            self._contains(all_text, self.TRAINING_SIGNALS)
            and not allowed_beauty_category
            and not standalone_salon_name
        )

    def _is_supply_only(
        self,
        *,
        all_text: str,
        allowed_beauty_category: bool,
        standalone_salon_name: bool,
    ) -> bool:
        return (
            self._contains(all_text, self.SUPPLY_STORE_SIGNALS)
            and not allowed_beauty_category
            and not standalone_salon_name
        )

    def _accept(
        self,
        organization: RawOrganization,
        *,
        reason_codes: list[str],
        business_profile: str,
        confidence: float,
    ) -> ClassificationResult:
        return ClassificationResult(
            accepted=True,
            confidence=confidence,
            reason_codes=reason_codes,
            business_profile=business_profile,
            decision_name=organization.name,
            decision_categories=list(organization.categories),
        )

    def _reject(
        self,
        organization: RawOrganization,
        *,
        reason_codes: list[str],
        rejection_reason: str,
        confidence: float,
        business_profile: str = "unknown",
    ) -> ClassificationResult:
        return ClassificationResult(
            accepted=False,
            confidence=confidence,
            reason_codes=reason_codes,
            business_profile=business_profile,
            rejection_reason=rejection_reason,
            decision_name=organization.name,
            decision_categories=list(organization.categories),
        )

    def _contains(self, text: str, needles: tuple[str, ...]) -> bool:
        return any((normalize_text(needle) or "") in text for needle in needles)
