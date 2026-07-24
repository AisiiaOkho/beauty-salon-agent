from __future__ import annotations

import re

from .models import PriceValue


class PriceNormalizer:
    """Normalize directly associated price strings into minor units."""

    CURRENCY_ALIASES = {
        "₽": "RUB",
        "руб": "RUB",
        "руб.": "RUB",
        "rub": "RUB",
    }

    RANGE_PATTERN = re.compile(
        r"(?P<first>\d[\d\s]*(?:[,.]\d+)?)\s*(?:-|–|—|до)\s*"
        r"(?P<second>\d[\d\s]*(?:[,.]\d+)?)",
        re.IGNORECASE,
    )
    PRICE_PATTERN = re.compile(
        r"(?P<prefix>от\s+)?(?P<amount>\d[\d\s]*(?:[,.]\d+)?)\s*"
        r"(?P<currency>₽|руб\.?|rub)?",
        re.IGNORECASE,
    )

    def normalize(self, value: str | int | float) -> PriceValue | None:
        """Return a normalized price, preserving exact/from/range semantics."""

        if isinstance(value, (int, float)):
            return PriceValue(
                price_type="exact",
                amount_minor=self._amount_to_minor(str(value)),
                currency="RUB",
            )

        text = value.strip()

        if not text:
            return None

        currency = self._detect_currency(text)
        range_match = self.RANGE_PATTERN.search(text)

        if range_match:
            first = self._amount_to_minor(range_match.group("first"))
            second = self._amount_to_minor(range_match.group("second"))

            if first is None or second is None:
                return None

            return PriceValue(
                price_type="range",
                currency=currency,
                range_min_minor=min(first, second),
                range_max_minor=max(first, second),
            )

        match = self.PRICE_PATTERN.search(text)

        if match is None:
            return None

        amount = self._amount_to_minor(match.group("amount"))

        if amount is None:
            return None

        price_type = "from" if match.group("prefix") else "exact"
        return PriceValue(
            price_type=price_type,
            amount_minor=amount,
            currency=currency,
            range_min_minor=amount if price_type == "from" else None,
        )

    def _amount_to_minor(self, value: str) -> int | None:
        normalized = value.replace(" ", "").replace(",", ".")

        try:
            major = float(normalized)
        except ValueError:
            return None

        if major <= 0:
            return None

        return int(round(major * 100))

    def _detect_currency(self, text: str) -> str:
        lower = text.lower()

        for alias, currency in self.CURRENCY_ALIASES.items():
            if alias in lower:
                return currency

        return "RUB"
