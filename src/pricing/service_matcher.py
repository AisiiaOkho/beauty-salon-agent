from __future__ import annotations

import re

from utils.normalization import normalize_text

from .models import ServiceMatch


class ServiceMatcher:
    """Classify service names for the target manicure-with-coating service."""

    MANICURE_SIGNALS = (
        "маникюр",
        "manicure",
    )
    COATING_SIGNALS = (
        "покрыт",
        "гель лак",
        "гель-лак",
        "gel polish",
        "coating",
    )
    STRONG_EQUIVALENTS = (
        "маникюр с покрытием",
        "комбинированный маникюр с покрытием",
        "аппаратный маникюр с покрытием",
        "маникюр + гель лак",
        "маникюр + гель-лак",
        "manicure with gel polish",
        "manicure with coating",
    )
    NEGATIVE_SIGNALS = (
        "снятие",
        "ремонт",
        "дизайн",
        "педикюр",
        "детский",
        "детск",
        "мужской",
        "men",
        "child",
        "kids",
    )
    PACKAGE_SIGNALS = (
        "комплекс",
        "пакет",
        "spa",
        "спа",
    )
    UNRELATED_SIGNALS = (
        "массаж",
        "стриж",
        "окраш",
        "бров",
        "ресниц",
        "косметолог",
    )

    def match(self, service_name: str, context: str | None = None) -> ServiceMatch:
        """Return an explainable target-service decision."""

        combined = " ".join(part for part in (service_name, context or "") if part)
        text = self._normalize(combined)
        service_text = self._normalize(service_name)
        reasons: list[str] = []

        if not text:
            return ServiceMatch("unrelated", None, "low", ["empty_service"])

        has_manicure = any(signal in text for signal in self.MANICURE_SIGNALS)
        has_coating = any(signal in text for signal in self.COATING_SIGNALS)
        strong = any(signal in text for signal in self.STRONG_EQUIVALENTS)

        if any(signal in service_text for signal in self.NEGATIVE_SIGNALS):
            if "мужской" in service_text and has_manicure and has_coating:
                reasons.append("mens_manicure_equivalent")
            else:
                return ServiceMatch(
                    "excluded",
                    service_text,
                    "high",
                    ["excluded_service_signal"],
                )

        if any(signal in service_text for signal in self.PACKAGE_SIGNALS):
            return ServiceMatch(
                "ambiguous",
                service_text,
                "low",
                ["package_service_signal"],
            )

        if strong or (has_manicure and has_coating):
            reasons.extend(["manicure_signal", "coating_signal"])
            return ServiceMatch("matched", service_text, "high", reasons)

        if has_coating and not has_manicure:
            return ServiceMatch(
                "ambiguous",
                service_text,
                "medium",
                ["coating_without_manicure_signal"],
            )

        if has_manicure:
            return ServiceMatch(
                "excluded",
                service_text,
                "high",
                ["manicure_without_coating_signal"],
            )

        if any(signal in service_text for signal in self.UNRELATED_SIGNALS):
            return ServiceMatch("excluded", service_text, "high", ["unrelated_service"])

        return ServiceMatch("unrelated", service_text, "low", ["no_target_signal"])

    def _normalize(self, value: str) -> str:
        normalized = normalize_text(value) or ""
        normalized = normalized.replace("+", " + ")
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()
