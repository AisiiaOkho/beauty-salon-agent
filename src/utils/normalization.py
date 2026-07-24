from __future__ import annotations

import re


def normalize_text(value: str | None) -> str | None:
    """Normalize text for deterministic duplicate matching."""

    if value is None:
        return None

    normalized = value.lower().replace("ё", "е")
    normalized = re.sub(r"[^0-9a-zа-я]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    return normalized or None


def normalize_phone(value: str | None) -> str | None:
    """Normalize phone number to digits-only form."""

    if value is None:
        return None

    digits = re.sub(r"\D+", "", value)

    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]

    return digits or None


def coordinate_key(
    latitude: float | None,
    longitude: float | None,
    precision: int = 5,
) -> str | None:
    """Return a stable coordinate key for fallback deduplication."""

    if latitude is None or longitude is None:
        return None

    return f"{latitude:.{precision}f},{longitude:.{precision}f}"
