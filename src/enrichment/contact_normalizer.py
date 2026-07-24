from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from utils.normalization import normalize_phone

from .models import ContactValue

SOCIAL_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "vk.com",
    "www.vk.com",
    "t.me",
    "telegram.me",
    "wa.me",
    "whatsapp.com",
    "www.whatsapp.com",
    "facebook.com",
    "www.facebook.com",
    "ok.ru",
    "www.ok.ru",
}


class ContactNormalizer:
    """Normalize contact values while preserving display forms."""

    def normalize_contact(
        self,
        *,
        contact_type: str,
        value: str,
        source: str,
        metadata: dict[str, object] | None = None,
    ) -> ContactValue | None:
        """Normalize one provider contact value."""

        display_value = value.strip()

        if not display_value:
            return None

        normalized_type = contact_type.lower().strip()

        if normalized_type in ("phone", "phone_number"):
            normalized_value = normalize_phone(display_value)

            if not normalized_value:
                return None

            return ContactValue(
                contact_type="phone",
                display_value=display_value,
                normalized_value=normalized_value,
                source=source,
                metadata=dict(metadata or {}),
            )

        if normalized_type in ("email", "mail"):
            normalized_email = display_value.lower()

            if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", normalized_email):
                return None

            return ContactValue(
                contact_type="email",
                display_value=display_value,
                normalized_value=normalized_email,
                source=source,
                metadata=dict(metadata or {}),
            )

        url = self.normalize_url(display_value)

        if url is None:
            return None

        parsed = urlparse(url)
        final_type = (
            "social"
            if parsed.netloc.lower() in SOCIAL_HOSTS
            else "website"
        )

        return ContactValue(
            contact_type=final_type,
            display_value=display_value,
            normalized_value=url,
            source=source,
            metadata=dict(metadata or {}),
        )

    def normalize_url(self, value: str) -> str | None:
        """Normalize URL enough for stable contact deduplication."""

        candidate = value.strip()

        if not candidate:
            return None

        if "://" not in candidate:
            candidate = f"https://{candidate}"

        parsed = urlparse(candidate)

        if not parsed.netloc:
            return None

        path = parsed.path.rstrip("/")
        return urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                path,
                "",
                parsed.query,
                "",
            )
        )
