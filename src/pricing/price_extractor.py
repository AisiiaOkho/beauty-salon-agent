from __future__ import annotations

import html
import json
import re
import socket
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
    PRICE_PARSER_VERSION,
    PRICING_DRY_RUN,
    PRICING_MAX_PAGES_PER_SALON,
    PRICING_MAX_RESPONSE_BYTES,
    PRICING_MAX_SALONS_PER_RUN,
    PRICING_RETRY_LIMIT,
    PRICING_TIMEOUT_SECONDS,
    PRICING_USER_AGENT,
)
from database_manager import Database

from .models import (
    PriceEvidence,
    PriceExtractionResult,
    PricingSummary,
    SERVICE_KEY_BASIC_MANICURE_WITH_COATING,
)
from .price_normalizer import PriceNormalizer
from .service_matcher import ServiceMatcher

ProgressLogger = Callable[[str], None]


class PricingSourceError(RuntimeError):
    """Raised when a pricing source cannot be safely fetched or parsed."""


class LimitedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Redirect handler with a small deterministic redirect budget."""

    def __init__(self, max_redirects: int) -> None:
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> urllib.request.Request | None:
        self.redirect_count += 1

        if self.redirect_count > self.max_redirects:
            raise PricingSourceError("Website redirect limit exceeded.")

        parsed = urllib.parse.urlparse(newurl)

        if parsed.scheme not in ("http", "https"):
            raise PricingSourceError("Unsupported redirect URL scheme.")

        return super().redirect_request(req, fp, code, msg, headers, newurl)


class WebsiteFetcher:
    """Fetch a salon website with conservative HTTP safety limits."""

    INTERNAL_LINK_KEYWORDS = (
        "price",
        "prices",
        "прайс",
        "услуги",
        "service",
        "services",
        "manicure",
        "маникюр",
    )

    def __init__(
        self,
        timeout_seconds: int = PRICING_TIMEOUT_SECONDS,
        max_response_bytes: int = PRICING_MAX_RESPONSE_BYTES,
        retry_limit: int = PRICING_RETRY_LIMIT,
        max_pages: int = PRICING_MAX_PAGES_PER_SALON,
        user_agent: str = PRICING_USER_AGENT,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.retry_limit = retry_limit
        self.max_pages = max_pages
        self.user_agent = user_agent
        self.progress_logger = progress_logger or (lambda message: None)
        self.ssl_context = ssl.create_default_context(cafile=certifi.where())

    def fetch_pages(self, url: str) -> list[tuple[str, str]]:
        """Fetch homepage and up to configured internal price/service links."""

        normalized_url = self._normalize_url(url)
        homepage = self._fetch_one(normalized_url)
        pages = [(self._sanitize_url(normalized_url), homepage)]

        for link in self._extract_internal_links(normalized_url, homepage):
            if len(pages) >= self.max_pages:
                break

            if any(existing_url == self._sanitize_url(link) for existing_url, _ in pages):
                continue

            pages.append((self._sanitize_url(link), self._fetch_one(link)))

        return pages

    def _fetch_one(self, url: str) -> str:
        errors: list[str] = []

        for attempt in range(1, self.retry_limit + 1):
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": self.user_agent},
                    method="GET",
                )
                redirect_handler = LimitedRedirectHandler(max_redirects=3)
                opener = urllib.request.build_opener(
                    redirect_handler,
                    urllib.request.HTTPSHandler(context=self.ssl_context),
                )
                self.progress_logger(
                    "Pricing website request: "
                    f"url={self._sanitize_url(url)} attempt={attempt}/{self.retry_limit}"
                )

                with opener.open(request, timeout=self.timeout_seconds) as response:
                    content_type = response.headers.get("Content-Type", "")

                    if "html" not in content_type.lower() and "json" not in content_type.lower():
                        raise PricingSourceError(
                            f"Unsupported website content type: {content_type}"
                        )

                    payload = response.read(self.max_response_bytes + 1)

                    if len(payload) > self.max_response_bytes:
                        raise PricingSourceError("Website response exceeds size limit.")

                    return payload.decode(
                        response.headers.get_content_charset() or "utf-8",
                        errors="replace",
                    )
            except (
                TimeoutError,
                socket.timeout,
                urllib.error.URLError,
                PricingSourceError,
            ) as error:
                errors.append(str(error))

                if attempt >= self.retry_limit:
                    break

                time.sleep(0.5 * attempt)

        raise PricingSourceError("; ".join(errors) or "Website fetch failed.")

    def _normalize_url(self, url: str) -> str:
        candidate = url.strip()

        if not candidate:
            raise PricingSourceError("Website URL is empty.")

        parsed = urllib.parse.urlparse(candidate)

        if not parsed.scheme:
            candidate = f"https://{candidate}"
            parsed = urllib.parse.urlparse(candidate)

        if parsed.scheme not in ("http", "https"):
            raise PricingSourceError("Unsupported website URL scheme.")

        if not parsed.netloc:
            raise PricingSourceError("Website URL host is missing.")

        return urllib.parse.urlunparse(
            (parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, "")
        )

    def _extract_internal_links(self, base_url: str, page: str) -> list[str]:
        base = urllib.parse.urlparse(base_url)
        links: list[str] = []

        for match in re.finditer(r"<a\s+[^>]*href=[\"']([^\"']+)[\"']", page, re.I):
            href = html.unescape(match.group(1)).strip()

            if not href:
                continue

            absolute = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(absolute)

            if parsed.scheme not in ("http", "https"):
                continue

            if parsed.netloc.lower() != base.netloc.lower():
                continue

            searchable = f"{parsed.path} {parsed.query}".lower()

            if any(keyword in searchable for keyword in self.INTERNAL_LINK_KEYWORDS):
                links.append(
                    urllib.parse.urlunparse(
                        (parsed.scheme, parsed.netloc, parsed.path or "/", "", parsed.query, "")
                    )
                )

        return links

    def _sanitize_url(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        safe_query = [
            (key, "REDACTED" if "key" in key.lower() or "token" in key.lower() else value)
            for key, value in query
        ]
        return urllib.parse.urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                "",
                urllib.parse.urlencode(safe_query),
                "",
            )
        )


class PriceExtractor:
    """Extract manicure-with-coating prices from trusted stored/source data."""

    def __init__(
        self,
        database: Database,
        website_fetcher: WebsiteFetcher | None = None,
        matcher: ServiceMatcher | None = None,
        normalizer: PriceNormalizer | None = None,
        max_salons_per_run: int = PRICING_MAX_SALONS_PER_RUN,
        dry_run: bool = PRICING_DRY_RUN,
        progress_logger: ProgressLogger | None = None,
    ) -> None:
        if max_salons_per_run < 0:
            raise ValueError("max_salons_per_run cannot be negative.")

        self.database = database
        self.website_fetcher = website_fetcher or WebsiteFetcher(
            progress_logger=progress_logger
        )
        self.matcher = matcher or ServiceMatcher()
        self.normalizer = normalizer or PriceNormalizer()
        self.max_salons_per_run = max_salons_per_run
        self.dry_run = dry_run
        self.progress_logger = progress_logger or print

    def extract_next(self) -> PricingSummary:
        """Extract prices for up to the configured number of accepted salons."""

        summary = PricingSummary(dry_run=self.dry_run)

        for _ in range(self.max_salons_per_run):
            salon = self.database.get_next_salon_for_pricing()

            if salon is None:
                break

            self._process_salon(salon, summary)

        return summary

    def extract_salon_id(self, salon_id: int) -> PricingSummary:
        """Extract prices for one explicit salon id."""

        summary = PricingSummary(dry_run=self.dry_run)
        salon = self.database.get_salon_for_pricing_by_id(salon_id)

        if salon is None:
            summary.skipped += 1
            return summary

        self._process_salon(salon, summary)
        return summary

    def _process_salon(
        self,
        salon: dict[str, Any],
        summary: PricingSummary,
    ) -> None:
        salon_id = int(salon["id"])

        if self.dry_run:
            summary.skipped += 1
            self.progress_logger(
                "Pricing dry-run: "
                f"salon_id={salon_id} website_present={bool(salon.get('website'))}"
            )
            return

        summary.processed += 1

        try:
            result = self.extract_for_salon(salon)
        except Exception as error:
            result = self._status_result(
                salon_id=salon_id,
                status="error",
                price_type="not_found",
                confidence="low",
                source_type=None,
                error_message=str(error),
            )

        self.database.save_price_check_result(result)
        self.database.upsert_salon_price(result)

        if result.extraction_status == "found":
            summary.found += 1
        elif result.extraction_status == "ambiguous":
            summary.ambiguous += 1
        elif result.extraction_status == "error":
            summary.errors += 1
        else:
            summary.not_found += 1

        self.progress_logger(
            "Pricing result: "
            f"salon_id={salon_id} status={result.extraction_status} "
            f"price_type={result.price_type}"
        )

    def extract_for_salon(self, salon: dict[str, Any]) -> PriceExtractionResult:
        """Extract one target price from provider details, then website data."""

        salon_id = int(salon["id"])
        provider_evidence = self._provider_price_evidence(salon_id)
        result = self._best_result(salon_id, provider_evidence)

        if result is not None and result.extraction_status == "found":
            return result

        website = salon.get("website")

        if website:
            website_evidence = self._website_price_evidence(str(website))
            website_result = self._best_result(salon_id, website_evidence)

            if website_result is not None:
                return website_result

        if result is not None:
            return result

        return self._status_result(
            salon_id=salon_id,
            status="not_found",
            price_type="not_found",
            confidence="low",
            source_type="none",
            evidence_text="No reliable manicure-with-coating price evidence found.",
        )

    def _provider_price_evidence(self, salon_id: int) -> list[PriceEvidence]:
        payloads = self.database.get_latest_detail_payloads_for_pricing(salon_id)
        evidence: list[PriceEvidence] = []

        for payload_row in payloads:
            payload = payload_row["payload"]
            source_url = payload_row["source_url"]

            for item in payload.get("result", {}).get("items", []) if isinstance(payload, dict) else []:
                if not isinstance(item, dict):
                    continue

                evidence.extend(
                    self._structured_evidence_from_object(
                        item,
                        source_type="provider_structured",
                        source_url=source_url,
                    )
                )

        return evidence

    def _website_price_evidence(self, website_url: str) -> list[PriceEvidence]:
        evidence: list[PriceEvidence] = []

        for source_url, page in self.website_fetcher.fetch_pages(website_url):
            evidence.extend(self._json_ld_evidence(page, source_url))
            evidence.extend(self._plain_text_evidence(page, source_url))

        return evidence

    def _structured_evidence_from_object(
        self,
        data: dict[str, Any],
        source_type: str,
        source_url: str | None,
    ) -> list[PriceEvidence]:
        evidence: list[PriceEvidence] = []

        for key in ("services", "prices", "service_prices", "menu"):
            values = data.get(key)

            if isinstance(values, list):
                for service in values:
                    if not isinstance(service, dict):
                        continue

                    name = self._first_string(service, ("name", "title", "service"))
                    price = service.get("price") or service.get("amount") or service.get("cost")

                    if name and price is not None:
                        evidence.append(
                            PriceEvidence(
                                service_name_raw=name,
                                price_raw=price,
                                source_type=source_type,
                                source_url=source_url,
                                evidence_text=f"{name} {price}",
                                raw_data=service,
                            )
                        )

        return evidence

    def _json_ld_evidence(self, page: str, source_url: str) -> list[PriceEvidence]:
        evidence: list[PriceEvidence] = []

        for match in re.finditer(
            r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
            page,
            re.I | re.S,
        ):
            raw_json = html.unescape(match.group(1)).strip()

            try:
                parsed = json.loads(raw_json)
            except json.JSONDecodeError:
                continue

            for node in self._flatten_json_ld(parsed):
                if not isinstance(node, dict):
                    continue

                name = self._first_string(node, ("name", "title"))
                offers = node.get("offers")
                price: object | None = None

                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                elif "price" in node:
                    price = node.get("price")

                if name and price is not None:
                    evidence.append(
                        PriceEvidence(
                            service_name_raw=name,
                            price_raw=price,
                            source_type="website_json_ld",
                            source_url=source_url,
                            evidence_text=f"{name} {price}",
                            raw_data=node,
                        )
                    )

        return evidence

    def _plain_text_evidence(self, page: str, source_url: str) -> list[PriceEvidence]:
        text = self._visible_text(page)
        evidence: list[PriceEvidence] = []

        for line in self._candidate_lines(text):
            price_match = PriceNormalizer.PRICE_PATTERN.search(line)

            if price_match is None and PriceNormalizer.RANGE_PATTERN.search(line) is None:
                continue

            evidence.append(
                PriceEvidence(
                    service_name_raw=line,
                    price_raw=line,
                    source_type="website_text",
                    source_url=source_url,
                    evidence_text=line,
                    raw_data={"line": line},
                )
            )

        return evidence

    def _best_result(
        self,
        salon_id: int,
        evidence_items: list[PriceEvidence],
    ) -> PriceExtractionResult | None:
        ambiguous: PriceExtractionResult | None = None

        for evidence in evidence_items:
            match = self.matcher.match(
                evidence.service_name_raw,
                evidence.evidence_text,
            )

            if match.status == "excluded" or match.status == "unrelated":
                continue

            price = self.normalizer.normalize(
                evidence.price_raw if evidence.price_raw is not None else evidence.evidence_text
            )

            if match.status == "ambiguous" or price is None:
                ambiguous = ambiguous or self._result_from_evidence(
                    salon_id=salon_id,
                    evidence=evidence,
                    service_name_normalized=match.service_name_normalized,
                    price_type="ambiguous",
                    amount_minor=None,
                    currency=None,
                    range_min_minor=None,
                    range_max_minor=None,
                    confidence=match.confidence,
                    extraction_status="ambiguous",
                )
                continue

            return self._result_from_evidence(
                salon_id=salon_id,
                evidence=evidence,
                service_name_normalized=match.service_name_normalized,
                price_type=price.price_type,
                amount_minor=price.amount_minor,
                currency=price.currency,
                range_min_minor=price.range_min_minor,
                range_max_minor=price.range_max_minor,
                confidence=match.confidence,
                extraction_status="found",
            )

        return ambiguous

    def _result_from_evidence(
        self,
        *,
        salon_id: int,
        evidence: PriceEvidence,
        service_name_normalized: str | None,
        price_type: str,
        amount_minor: int | None,
        currency: str | None,
        range_min_minor: int | None,
        range_max_minor: int | None,
        confidence: str,
        extraction_status: str,
    ) -> PriceExtractionResult:
        return PriceExtractionResult(
            salon_id=salon_id,
            service_name_raw=evidence.service_name_raw,
            service_name_normalized=service_name_normalized,
            amount_minor=amount_minor,
            currency=currency,
            price_type=price_type,
            range_min_minor=range_min_minor,
            range_max_minor=range_max_minor,
            source_type=evidence.source_type,
            source_url=evidence.source_url,
            evidence_text=evidence.evidence_text,
            confidence=confidence,
            extraction_status=extraction_status,
            checked_at=datetime.now(UTC).isoformat(),
            parser_version=PRICE_PARSER_VERSION,
            raw_evidence=evidence.raw_data,
        )

    def _status_result(
        self,
        *,
        salon_id: int,
        status: str,
        price_type: str,
        confidence: str,
        source_type: str | None,
        evidence_text: str | None = None,
        error_message: str | None = None,
    ) -> PriceExtractionResult:
        return PriceExtractionResult(
            salon_id=salon_id,
            service_name_raw=None,
            service_name_normalized=None,
            amount_minor=None,
            currency=None,
            price_type=price_type,
            range_min_minor=None,
            range_max_minor=None,
            source_type=source_type,
            source_url=None,
            evidence_text=evidence_text,
            confidence=confidence,
            extraction_status=status,
            checked_at=datetime.now(UTC).isoformat(),
            parser_version=PRICE_PARSER_VERSION,
            raw_evidence={},
            error_message=error_message,
        )

    def _first_string(
        self,
        data: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = data.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

        return None

    def _flatten_json_ld(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            nodes: list[Any] = []

            for item in value:
                nodes.extend(self._flatten_json_ld(item))

            return nodes

        if isinstance(value, dict):
            nodes = [value]

            for key in ("@graph", "hasOfferCatalog", "itemListElement"):
                child = value.get(key)

                if child is not None:
                    nodes.extend(self._flatten_json_ld(child))

            return nodes

        return []

    def _visible_text(self, page: str) -> str:
        page = re.sub(r"<script\b.*?</script>", " ", page, flags=re.I | re.S)
        page = re.sub(r"<style\b.*?</style>", " ", page, flags=re.I | re.S)
        page = re.sub(r"<br\s*/?>", "\n", page, flags=re.I)
        page = re.sub(r"</(p|div|li|tr|td|h\d)>", "\n", page, flags=re.I)
        page = re.sub(r"<[^>]+>", " ", page)
        return html.unescape(page)

    def _candidate_lines(self, text: str) -> list[str]:
        lines: list[str] = []

        for raw_line in re.split(r"[\n\r]+", text):
            line = re.sub(r"\s+", " ", raw_line).strip()

            if 8 <= len(line) <= 220:
                lines.append(line)

        return lines
