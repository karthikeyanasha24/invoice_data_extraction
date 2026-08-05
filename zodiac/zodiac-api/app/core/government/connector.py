"""
Government Connector implementations (Phase 7).

- MockGovernmentConnector: in-process acknowledgements (tests / sample default)
- AlreadyStampedGovernmentConnector: Mexico-style "no live government call"
- HttpGovernmentConnector: workspace-configured HTTP with auth + retry
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any, Callable, Dict, Optional

from .auth import AuthMaterial, build_auth, is_usable_http_url, redact_endpoint
from ..secrets import SecretResolver, get_default_secret_resolver
from .base import (
    GOV_DUPLICATE,
    GOV_NOT_CONFIGURED,
    GOV_NOT_SUPPORTED,
    GOV_UNAVAILABLE,
    CanonicalGovernmentRequest,
    CanonicalGovernmentResponse,
    GovernmentConnector,
    GovernmentEndpointConfig,
    GovernmentHealthResult,
    GovernmentOperation,
    GovernmentStatus,
)
from .health import evaluate_endpoint_health
from .http_client import government_request
from .normalization import normalize_exception, normalize_http_response
from .retry import DEFAULT_GOV_RETRY, GovernmentRetryPolicy

logger = logging.getLogger("zodiac-api.government.connector")

IDEMPOTENCY_HEADER = "X-Idempotency-Key"


def _log_call(
    request: CanonicalGovernmentRequest,
    *,
    endpoint: Optional[str],
    status: GovernmentStatus,
    latency_ms: Optional[float],
    retry_count: int,
    http_status: Optional[int] = None,
) -> None:
    logger.info(
        "[government] corr=%s customer=%s country=%s op=%s endpoint=%s "
        "status=%s http=%s latency_ms=%s retries=%s submission_id=%s ref=%s",
        request.correlation_id,
        request.customer_id,
        request.country_code,
        request.operation.value if hasattr(request.operation, "value") else request.operation,
        redact_endpoint(endpoint),
        status.value if hasattr(status, "value") else status,
        http_status,
        round(latency_ms, 2) if latency_ms is not None else None,
        retry_count,
        request.submission_id,
        None,
    )


class MockGovernmentConnector(GovernmentConnector):
    """In-process mock — no network. Default for sample_gst and tests."""

    def __init__(self, *, prefix: str = "MOCK-ACK"):
        self.prefix = prefix
        self._cache: Dict[str, CanonicalGovernmentResponse] = {}

    async def submit(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return await self._cached_or_new(request, GovernmentOperation.SUBMIT)

    async def cancel(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.ACCEPTED,
            request,
            government_reference=request.government_reference,
            message="Mock cancel accepted",
            raw_response={"mode": "mock", "operation": "cancel"},
        )

    async def status(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        cached = self._cache.get(self._key(request))
        if cached:
            return CanonicalGovernmentResponse.of(
                cached.status,
                request,
                government_reference=cached.government_reference,
                message="Mock status from cache",
                raw_response=cached.raw_response,
            )
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.UNKNOWN,
            request,
            message="No prior mock submission",
            error_code=GOV_NOT_CONFIGURED,
        )

    async def download(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.ACCEPTED,
            request,
            government_reference=request.government_reference,
            message="Mock download",
            raw_response={"mode": "mock", "content": "<mock/>"},
        )

    async def health(self) -> GovernmentHealthResult:
        return GovernmentHealthResult(healthy=True, message="MockGovernmentConnector", endpoint=None)

    async def _cached_or_new(
        self, request: CanonicalGovernmentRequest, operation: GovernmentOperation
    ) -> CanonicalGovernmentResponse:
        key = self._key(request)
        existing = self._cache.get(key)
        if existing and existing.status is GovernmentStatus.ACCEPTED:
            dup = CanonicalGovernmentResponse.of(
                GovernmentStatus.ACCEPTED,
                request,
                government_reference=existing.government_reference,
                message="Duplicate mock submission",
                raw_response=existing.raw_response,
                error_code=GOV_DUPLICATE,
                retryable=False,
                duplicate=True,
            )
            _log_call(request, endpoint=None, status=dup.status, latency_ms=0.0, retry_count=0)
            return dup

        started = time.perf_counter()
        irn = ""
        if isinstance(request.payload, dict):
            invoice = request.payload.get("invoice") or request.payload
            irn = str(invoice.get("irn") or request.government_reference or "")
        digest = hashlib.sha256(f"ack:{request.submission_id}:{irn}".encode("utf-8")).hexdigest()[:16].upper()
        ref = f"{self.prefix}-{digest}"
        response = CanonicalGovernmentResponse.of(
            GovernmentStatus.ACCEPTED,
            request,
            government_reference=ref,
            message="Mock government acknowledgement",
            raw_response={"mode": "mock", "ack_number": ref, "irn": irn, "status": "ACCEPTED"},
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        self._cache[key] = response
        _log_call(
            request,
            endpoint=None,
            status=response.status,
            latency_ms=response.latency_ms,
            retry_count=0,
        )
        return response

    @staticmethod
    def _key(request: CanonicalGovernmentRequest) -> str:
        return f"{request.customer_id}:{request.submission_id}"


class AlreadyStampedGovernmentConnector(GovernmentConnector):
    """
    For countries (e.g. Mexico CFDI) where the authority stamp is already on
    the inbound document — no live government HTTP is performed.
    """

    async def submit(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        ref = request.government_reference or _stamp_from_payload(request.payload)
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.ACCEPTED,
            request,
            government_reference=ref,
            message="Document already stamped; no live government submission",
            raw_response={"mode": "already_stamped", "reference": ref},
            retryable=False,
        )

    async def cancel(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.REJECTED,
            request,
            message="Cancel via government API is not available for already-stamped flow",
            error_code=GOV_NOT_SUPPORTED,
            retryable=False,
        )

    async def status(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        ref = request.government_reference or _stamp_from_payload(request.payload)
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.ACCEPTED if ref else GovernmentStatus.UNKNOWN,
            request,
            government_reference=ref,
            message="Status derived from inbound stamp only",
            raw_response={"mode": "already_stamped"},
        )

    async def download(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return CanonicalGovernmentResponse.of(
            GovernmentStatus.REJECTED,
            request,
            message="Download not supported for already-stamped connector",
            error_code=GOV_NOT_SUPPORTED,
            retryable=False,
        )

    async def health(self) -> GovernmentHealthResult:
        return GovernmentHealthResult(
            healthy=True,
            message="AlreadyStampedGovernmentConnector (no live government endpoint)",
        )


class HttpGovernmentConnector(GovernmentConnector):
    """Workspace-configured HTTP government client with auth, retry, idempotency."""

    def __init__(
        self,
        config: GovernmentEndpointConfig,
        *,
        retry: Optional[GovernmentRetryPolicy] = None,
        secret_resolver: Optional[SecretResolver] = None,
        http_client: Any = None,
        sleep: Optional[Callable[[float], Any]] = None,
    ):
        self.config = config
        self.retry = retry or DEFAULT_GOV_RETRY
        self.secret_resolver = secret_resolver or get_default_secret_resolver()
        self.http_client = http_client
        self._sleep = sleep or asyncio.sleep
        self._cache: Dict[str, CanonicalGovernmentResponse] = {}

    async def submit(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return await self._execute(request, method="POST")

    async def cancel(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return await self._execute(request, method="POST", path_suffix="/cancel")

    async def status(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return await self._execute(request, method="GET", path_suffix="/status")

    async def download(self, request: CanonicalGovernmentRequest) -> CanonicalGovernmentResponse:
        return await self._execute(request, method="GET", path_suffix="/download")

    async def health(self) -> GovernmentHealthResult:
        return evaluate_endpoint_health(self.config)

    async def _execute(
        self,
        request: CanonicalGovernmentRequest,
        *,
        method: str,
        path_suffix: str = "",
    ) -> CanonicalGovernmentResponse:
        cache_key = f"{request.customer_id}:{request.submission_id}:{request.operation}"
        if request.operation == GovernmentOperation.SUBMIT or (
            isinstance(request.operation, str) and request.operation == "submit"
        ):
            cached = self._cache.get(cache_key)
            if cached and cached.status is GovernmentStatus.ACCEPTED:
                return CanonicalGovernmentResponse.of(
                    GovernmentStatus.ACCEPTED,
                    request,
                    government_reference=cached.government_reference,
                    message="Duplicate government submission",
                    raw_response=cached.raw_response,
                    error_code=GOV_DUPLICATE,
                    retryable=False,
                    duplicate=True,
                )

        url = self.config.endpoint_url
        if not is_usable_http_url(url):
            response = CanonicalGovernmentResponse.of(
                GovernmentStatus.FAILED,
                request,
                message="Government endpoint not configured or not a usable URL",
                error_code=GOV_NOT_CONFIGURED,
                retryable=False,
            )
            _log_call(request, endpoint=url, status=response.status, latency_ms=0.0, retry_count=0)
            return response

        target = f"{url.rstrip('/')}{path_suffix}" if path_suffix else url
        auth = build_auth(self.config, self.secret_resolver)
        attempt = 0
        last: Optional[CanonicalGovernmentResponse] = None

        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                headers = {IDEMPOTENCY_HEADER: request.submission_id}
                json_body = request.payload if request.content_type == "application/json" else None
                content = None if json_body is not None else request.payload
                http_status, body = await government_request(
                    method=method,
                    url=target,
                    headers=headers,
                    json_body=json_body if isinstance(json_body, (dict, list)) else None,
                    content=content if json_body is None or not isinstance(json_body, (dict, list)) else None,
                    content_type=request.content_type,
                    auth=auth,
                    http_client=self.http_client,
                )
                latency = (time.perf_counter() - started) * 1000
                last = normalize_http_response(
                    request, http_status=http_status, body=body, latency_ms=latency
                )
            except Exception as exc:  # noqa: BLE001
                latency = (time.perf_counter() - started) * 1000
                last = normalize_exception(request, exc, latency_ms=latency)

            _log_call(
                request,
                endpoint=target,
                status=last.status,
                latency_ms=last.latency_ms,
                retry_count=attempt - 1,
                http_status=last.http_status,
            )

            if not self.retry.should_retry(attempt, last.error_code or "", last.status):
                break
            delay = self.retry.delay_for(attempt)
            if delay:
                await self._sleep(delay)

        if last and last.status is GovernmentStatus.ACCEPTED:
            self._cache[cache_key] = last
        if last and last.status is GovernmentStatus.RETRY and attempt >= self.retry.max_attempts:
            last = CanonicalGovernmentResponse.of(
                GovernmentStatus.FAILED,
                request,
                government_reference=last.government_reference,
                message=last.message or "Government retries exhausted",
                raw_response=last.raw_response,
                http_status=last.http_status,
                error_code=last.error_code or GOV_UNAVAILABLE,
                retryable=False,
                latency_ms=last.latency_ms,
            )
        return last  # type: ignore[return-value]


def _stamp_from_payload(payload: Any) -> Optional[str]:
    if isinstance(payload, dict):
        for key in ("cfdi_uuid", "uuid", "government_reference", "irn"):
            if payload.get(key):
                return str(payload[key])
    return None
