from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import certifi

from config.settings import (
    TWOGIS_API_KEY_ENV,
    TWOGIS_BACKOFF_SECONDS,
    TWOGIS_DETAILS_ENDPOINT,
    TWOGIS_DETAILS_RETRY_LIMIT,
    TWOGIS_DETAILS_TIMEOUT_SECONDS,
    TWOGIS_MAX_RETRIES,
    TWOGIS_PAGE_SIZE,
    TWOGIS_PLACES_ENDPOINT,
    TWOGIS_RATE_LIMIT_DELAY_SECONDS,
    TWOGIS_TIMEOUT_SECONDS,
    TWOGIS_USER_AGENT,
)
from enrichment.contact_normalizer import ContactNormalizer
from enrichment.models import (
    ContactValue,
    OrganizationDetails,
    OrganizationDetailsResult,
)
from scanner.models import RawOrganization, SearchPage

ProgressLogger = Callable[[str], None]


class TwoGisClientError(RuntimeError):
    """Raised when the 2GIS Places client cannot return a valid page."""


class TwoGisDetailsParserError(TwoGisClientError):
    """Raised when a 2GIS details payload cannot be normalized."""


class MissingTwoGisApiKeyError(TwoGisClientError):
    """Raised when the configured 2GIS API key is missing."""


class TwoGisPlacesClient:
    """Official 2GIS Places API search client."""

    RETRYABLE_STATUS_CODES = {429, 502, 503, 504}

    def __init__(
        self,
        api_key: str | None = None,
        endpoint_url: str = TWOGIS_PLACES_ENDPOINT,
        timeout_seconds: int = TWOGIS_TIMEOUT_SECONDS,
        max_retries: int = TWOGIS_MAX_RETRIES,
        backoff_seconds: float = TWOGIS_BACKOFF_SECONDS,
        page_size: int = TWOGIS_PAGE_SIZE,
        delay_seconds: float = TWOGIS_RATE_LIMIT_DELAY_SECONDS,
        user_agent: str = TWOGIS_USER_AGENT,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv(TWOGIS_API_KEY_ENV)
        self.endpoint_url = endpoint_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.page_size = page_size
        self.delay_seconds = delay_seconds
        self.user_agent = user_agent
        self.progress_logger = progress_logger or (lambda message: None)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())
        self.contact_normalizer = ContactNormalizer()

        if not self.api_key:
            raise MissingTwoGisApiKeyError(
                f"2GIS API key is missing. Set {TWOGIS_API_KEY_ENV}."
            )

    def search(
        self,
        *,
        query: str,
        center_lat: float,
        center_lon: float,
        radius_meters: int,
        page: int,
        grid_cell_id: int,
    ) -> SearchPage:
        """Search organizations through the official Places API."""

        parameters = {
            "q": query,
            "type": "branch",
            "point": f"{center_lon},{center_lat}",
            "radius": str(radius_meters),
            "page": str(page),
            "page_size": str(self.page_size),
            "locale": "ru_RU",
            "fields": ",".join(
                [
                    "items.point",
                    "items.address",
                    "items.contact_groups",
                    "items.rubrics",
                    "items.schedule",
                    "items.org",
                    "items.description",
                ]
            ),
            "key": self.api_key,
        }
        url = f"{self.endpoint_url}?{urllib.parse.urlencode(parameters)}"
        source_url = self._build_source_url(parameters)
        document = self._normalize_document(
            self._request_json(url=url, query=query, page=page)
        )
        self._log_meta_code(document)
        items = document.get("result", {}).get("items", [])

        if not isinstance(items, list):
            raise TwoGisClientError("2GIS response result.items is not a list.")

        organizations = [
            self._parse_item(
                item=item,
                source_url=source_url,
                query=query,
                grid_cell_id=grid_cell_id,
            )
            for item in items
            if isinstance(item, dict)
        ]
        total = int(document.get("result", {}).get("total", len(organizations)))
        has_next_page = page * self.page_size < total and bool(organizations)

        return SearchPage(
            organizations=organizations,
            page=page,
            has_next_page=has_next_page,
        )

    def get_organization_details(
        self,
        external_id: str,
        salon_id: int | None = None,
    ) -> OrganizationDetailsResult:
        """Fetch and parse one organization through 2GIS byid."""

        del salon_id

        parameters = {
            "id": external_id,
            "locale": "ru_RU",
            "fields": ",".join(
                [
                    "items.point",
                    "items.address",
                    "items.full_address_name",
                    "items.contact_groups",
                    "items.rubrics",
                    "items.schedule",
                    "items.org",
                    "items.brand",
                    "items.description",
                    "items.updated_at",
                ]
            ),
            "key": self.api_key,
        }
        url = f"{TWOGIS_DETAILS_ENDPOINT}?{urllib.parse.urlencode(parameters)}"
        sanitized_source_url = self._build_details_source_url(parameters)

        try:
            document, http_status = self._request_details_json(
                url=url,
                external_id=external_id,
            )
            payload_code = self._payload_code(document)
            self.progress_logger(f"2GIS details payload meta.code: {payload_code}")

            if payload_code == 404:
                return OrganizationDetailsResult(
                    external_source="2GIS",
                    external_id=external_id,
                    status="not_found",
                    http_status=http_status,
                    payload_code=payload_code,
                    sanitized_source_url=sanitized_source_url,
                    raw_payload=document,
                    error_message="2GIS organization not found.",
                )

            if payload_code in (401, 403):
                return OrganizationDetailsResult(
                    external_source="2GIS",
                    external_id=external_id,
                    status="unauthorized",
                    http_status=http_status,
                    payload_code=payload_code,
                    sanitized_source_url=sanitized_source_url,
                    raw_payload=document,
                    error_message="2GIS details request is unauthorized.",
                )

            if payload_code is not None and payload_code >= 400:
                return OrganizationDetailsResult(
                    external_source="2GIS",
                    external_id=external_id,
                    status="provider_error",
                    http_status=http_status,
                    payload_code=payload_code,
                    sanitized_source_url=sanitized_source_url,
                    raw_payload=document,
                    error_message=f"2GIS details payload error {payload_code}.",
                )

            details = self._parse_details(external_id, document)

            return OrganizationDetailsResult(
                external_source="2GIS",
                external_id=external_id,
                status="success",
                http_status=http_status,
                payload_code=payload_code,
                sanitized_source_url=sanitized_source_url,
                raw_payload=document,
                details=details,
            )
        except TwoGisClientError as error:
            return OrganizationDetailsResult(
                external_source="2GIS",
                external_id=external_id,
                status=self._details_error_status(error),
                http_status=getattr(error, "http_status", None),
                payload_code=None,
                sanitized_source_url=sanitized_source_url,
                raw_payload={},
                error_message=str(error),
            )

    def _request_json(
        self,
        *,
        url: str,
        query: str,
        page: int,
    ) -> dict[str, Any]:
        errors: list[str] = []

        for attempt in range(1, self.max_retries + 1):
            try:
                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)

                self.progress_logger(
                    f"2GIS request query='{query}' page={page} "
                    f"attempt={attempt}/{self.max_retries}"
                )
                return self._perform_request(url)
            except urllib.error.HTTPError as error:
                errors.append(f"HTTP {error.code}")

                if error.code not in self.RETRYABLE_STATUS_CODES:
                    raise TwoGisClientError(f"2GIS HTTP {error.code}") from error

                self._sleep_before_retry(attempt, error.headers.get("Retry-After"))
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                TwoGisClientError,
            ) as error:
                errors.append(str(error))
                self._sleep_before_retry(attempt, None)

        raise TwoGisClientError(
            f"2GIS request failed after retries: {'; '.join(errors)}"
        )

    def _request_details_json(
        self,
        *,
        url: str,
        external_id: str,
    ) -> tuple[dict[str, Any], int | None]:
        errors: list[str] = []

        for attempt in range(1, TWOGIS_DETAILS_RETRY_LIMIT + 1):
            try:
                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)

                self.progress_logger(
                    "2GIS details request "
                    f"external_id_present={bool(external_id)} "
                    f"attempt={attempt}/{TWOGIS_DETAILS_RETRY_LIMIT}"
                )
                return self._perform_request_with_status(
                    url,
                    timeout_seconds=TWOGIS_DETAILS_TIMEOUT_SECONDS,
                )
            except urllib.error.HTTPError as error:
                errors.append(f"HTTP {error.code}")

                if error.code in (401, 403, 404):
                    raise self._error(
                        f"2GIS details HTTP {error.code}",
                        http_status=error.code,
                    ) from error

                if error.code not in self.RETRYABLE_STATUS_CODES and error.code != 408:
                    raise self._error(
                        f"2GIS details HTTP {error.code}",
                        http_status=error.code,
                    ) from error

                if attempt >= TWOGIS_DETAILS_RETRY_LIMIT:
                    raise self._error(
                        f"2GIS details HTTP {error.code}",
                        http_status=error.code,
                    ) from error

                self._sleep_before_retry(
                    attempt,
                    error.headers.get("Retry-After"),
                    max_attempts=TWOGIS_DETAILS_RETRY_LIMIT,
                )
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
            ) as error:
                errors.append(str(error))
                self._sleep_before_retry(
                    attempt,
                    None,
                    max_attempts=TWOGIS_DETAILS_RETRY_LIMIT,
                )

        raise TwoGisClientError(
            f"2GIS details request failed after retries: {'; '.join(errors)}"
        )

    def _perform_request(self, url: str) -> dict[str, Any]:
        document, _ = self._perform_request_with_status(
            url,
            timeout_seconds=self.timeout_seconds,
        )
        return document

    def _perform_request_with_status(
        self,
        url: str,
        timeout_seconds: int,
    ) -> tuple[dict[str, Any], int]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": self.user_agent},
            method="GET",
        )

        with urllib.request.urlopen(
            request,
            timeout=timeout_seconds,
            context=self.ssl_context,
        ) as response:
            self.progress_logger(f"2GIS HTTP status: {response.status}")
            content_type = response.headers.get("Content-Type", "")

            if "json" not in content_type.lower():
                raise TwoGisClientError(
                    "Unexpected 2GIS content type: "
                    f"{content_type}"
                )

            return json.loads(response.read().decode("utf-8")), int(response.status)

    def _build_source_url(self, parameters: dict[str, str]) -> str:
        safe_parameters = {
            key: value
            for key, value in parameters.items()
            if key != "key"
        }

        return f"{self.endpoint_url}?{urllib.parse.urlencode(safe_parameters)}"

    def _build_details_source_url(self, parameters: dict[str, str]) -> str:
        safe_parameters = {
            key: value
            for key, value in parameters.items()
            if key != "key"
        }

        return f"{TWOGIS_DETAILS_ENDPOINT}?{urllib.parse.urlencode(safe_parameters)}"

    def _normalize_document(self, document: dict[str, Any]) -> dict[str, Any]:
        meta = document.get("meta")

        if isinstance(meta, dict):
            code = meta.get("code")

            if int(code or 0) == 404:
                return {
                    **document,
                    "result": {"items": [], "total": 0},
                }

            if code is not None and int(code) >= 400:
                message = meta.get("error", {}).get("message")
                raise TwoGisClientError(
                    f"2GIS API error {code}: {message or 'unknown error'}"
                )

        if "result" not in document:
            raise TwoGisClientError("2GIS response does not contain result.")

        return document

    def _log_meta_code(self, document: dict[str, Any]) -> None:
        meta = document.get("meta")

        if isinstance(meta, dict) and "code" in meta:
            self.progress_logger(f"2GIS payload meta.code: {meta['code']}")

    def _payload_code(self, document: dict[str, Any]) -> int | None:
        meta = document.get("meta")

        if not isinstance(meta, dict) or "code" not in meta:
            return None

        return int(meta["code"])

    def _parse_details(
        self,
        external_id: str,
        document: dict[str, Any],
    ) -> OrganizationDetails:
        result = document.get("result")

        if not isinstance(result, dict):
            raise TwoGisDetailsParserError(
                "2GIS details payload has no result object."
            )

        items = result.get("items")

        if not isinstance(items, list):
            raise TwoGisDetailsParserError(
                "2GIS details result.items is not a list."
            )

        if not items:
            raise TwoGisDetailsParserError("2GIS details result.items is empty.")

        item = items[0]

        if not isinstance(item, dict):
            raise TwoGisDetailsParserError(
                "2GIS details first item is malformed."
            )

        point = item.get("point") or {}
        organization = item.get("org") if isinstance(item.get("org"), dict) else {}

        return OrganizationDetails(
            external_source="2GIS",
            external_id=external_id,
            name=self._string_or_none(item.get("name")),
            full_address=(
                self._string_or_none(item.get("full_address_name"))
                or self._extract_address(item)
            ),
            latitude=self._optional_float(point.get("lat")),
            longitude=self._optional_float(point.get("lon")),
            categories=self._extract_categories(item),
            description=self._string_or_none(item.get("description")),
            working_hours=self._json_or_string(item.get("schedule")),
            branch_info=self._json_or_string(item.get("org")),
            organization_id=self._string_or_none(organization.get("id")),
            branch_id=self._string_or_none(item.get("id")),
            provider_updated_at=self._string_or_none(
                item.get("updated_at") or item.get("last_update")
            ),
            contacts=self._extract_detail_contacts(item),
        )

    def _extract_detail_contacts(
        self,
        item: dict[str, Any],
    ) -> list[ContactValue]:
        contacts: list[ContactValue] = []
        seen: set[tuple[str, str]] = set()

        for group in item.get("contact_groups") or []:
            if not isinstance(group, dict):
                continue

            for contact in group.get("contacts") or []:
                if not isinstance(contact, dict):
                    continue

                contact_type = str(contact.get("type") or "")
                value = self._string_or_none(
                    contact.get("value") or contact.get("text")
                )

                if value is None:
                    continue

                normalized = self.contact_normalizer.normalize_contact(
                    contact_type=contact_type,
                    value=value,
                    source="2GIS",
                    metadata={
                        "raw_type": contact_type,
                        "comment": contact.get("comment"),
                    },
                )

                if normalized is None:
                    continue

                key = (normalized.contact_type, normalized.normalized_value)

                if key in seen:
                    continue

                seen.add(key)
                contacts.append(normalized)

        return contacts

    def _details_error_status(self, error: TwoGisClientError) -> str:
        if isinstance(error, TwoGisDetailsParserError):
            return "parser_error"

        http_status = getattr(error, "http_status", None)

        if http_status == 404:
            return "not_found"

        if http_status in (401, 403):
            return "unauthorized"

        if http_status == 429:
            return "rate_limited"

        if http_status in (408, 500, 502, 503, 504):
            return "transient_error"

        return "provider_error"

    def _error(self, message: str, http_status: int) -> TwoGisClientError:
        error = TwoGisClientError(message)
        setattr(error, "http_status", http_status)
        return error

    def _sleep_before_retry(
        self,
        attempt: int,
        retry_after: str | None,
        max_attempts: int | None = None,
    ) -> None:
        if attempt >= (max_attempts or self.max_retries):
            return

        seconds = self._retry_after_seconds(retry_after)

        if seconds is None:
            seconds = self.backoff_seconds * (2 ** (attempt - 1))

        self.progress_logger(f"2GIS retry in {seconds:.1f}s")
        time.sleep(seconds)

    def _retry_after_seconds(self, retry_after: str | None) -> float | None:
        if retry_after is None:
            return None

        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    def _parse_item(
        self,
        *,
        item: dict[str, Any],
        source_url: str,
        query: str,
        grid_cell_id: int,
    ) -> RawOrganization:
        point = item.get("point") or {}
        contacts = self._extract_contacts(item)

        return RawOrganization(
            external_source="2GIS",
            external_id=str(item["id"]) if item.get("id") is not None else None,
            name=str(item.get("name") or ""),
            address=self._extract_address(item),
            latitude=self._optional_float(point.get("lat")),
            longitude=self._optional_float(point.get("lon")),
            phone=contacts["phone"],
            website=contacts["website"],
            social_links=contacts["social_links"],
            categories=self._extract_categories(item),
            description=self._string_or_none(item.get("description")),
            working_hours=self._string_or_none(item.get("schedule")),
            branch_info=self._string_or_none(item.get("org")),
            raw_payload=item,
            source_url=source_url,
            discovered_query=query,
            discovered_grid_cell_id=grid_cell_id,
            fetched_at=datetime.now(UTC).isoformat(),
        )

    def _extract_address(self, item: dict[str, Any]) -> str | None:
        address = item.get("address")

        if isinstance(address, dict):
            return self._string_or_none(
                address.get("name") or item.get("address_name")
            )

        return self._string_or_none(address or item.get("address_name"))

    def _extract_categories(self, item: dict[str, Any]) -> list[str]:
        rubrics = item.get("rubrics") or []
        categories: list[str] = []

        if isinstance(rubrics, list):
            for rubric in rubrics:
                if isinstance(rubric, dict) and rubric.get("name"):
                    categories.append(str(rubric["name"]))

        return categories

    def _extract_contacts(self, item: dict[str, Any]) -> dict[str, Any]:
        phone: str | None = None
        website: str | None = None
        social_links: list[str] = []

        for group in item.get("contact_groups") or []:
            if not isinstance(group, dict):
                continue

            for contact in group.get("contacts") or []:
                if not isinstance(contact, dict):
                    continue

                contact_type = str(contact.get("type") or "")
                value = self._string_or_none(
                    contact.get("value") or contact.get("text")
                )

                if value is None:
                    continue

                if contact_type in ("phone", "phone_number") and phone is None:
                    phone = value
                elif contact_type in ("website", "site") and website is None:
                    website = value
                elif contact_type in ("social", "instagram", "vk"):
                    social_links.append(value)

        return {
            "phone": phone,
            "website": website,
            "social_links": social_links,
        }

    def _optional_float(self, value: object) -> float | None:
        if value is None:
            return None

        return float(value)

    def _string_or_none(self, value: object) -> str | None:
        if value is None:
            return None

        return str(value)

    def _json_or_string(self, value: object) -> str | None:
        if value is None:
            return None

        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)

        return str(value)
