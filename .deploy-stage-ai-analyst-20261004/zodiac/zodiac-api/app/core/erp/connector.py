"""
Generic HTTP ERP Connector (Phase 6).

Pushes CanonicalConfirmation to the workspace ERP callback. Never branches on
country. Idempotency via erp_push_outbox + X-Idempotency-Key header.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional, Protocol, runtime_checkable

from sqlalchemy.orm import Session

from . import outbox as outbox_mod
from .models import (
    ERP_AUTH_FAILED,
    ERP_DUPLICATE,
    ERP_NOT_CONFIGURED,
    ERP_REJECTED,
    ERP_TIMEOUT,
    ERP_UPDATE_FAILED,
    DocumentStatus,
    ErpError,
    ErpPushRequest,
    ErpPushResult,
)

logger = logging.getLogger("zodiac-api.erp.connector")

IDEMPOTENCY_HEADER = "X-Idempotency-Key"


@runtime_checkable
class ErpConnector(Protocol):
    def push_confirmation(self, request: ErpPushRequest) -> ErpPushResult: ...

    def health_check(self, connection: Any = None) -> bool: ...


class InMemoryOutboxStore:
    """Test / no-DB fallback. Same semantics as the SQL outbox."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self.rows.get(key)

    def begin(self, key: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        row = self.rows.get(key)
        if row is None:
            row = {**meta, "status": outbox_mod.OUTBOX_PENDING, "attempt_count": 1}
            self.rows[key] = row
        else:
            row["attempt_count"] = int(row.get("attempt_count") or 0) + 1
            row["status"] = outbox_mod.OUTBOX_PENDING
        return row

    def success(self, key: str, body: Any = None) -> None:
        row = self.rows.setdefault(key, {})
        row["status"] = outbox_mod.OUTBOX_SUCCESS
        row["response_body"] = body

    def failed(self, key: str, error: str) -> None:
        row = self.rows.setdefault(key, {})
        row["status"] = outbox_mod.OUTBOX_FAILED
        row["last_error"] = error


class HttpErpConnector:
    """
    POST confirmation JSON to workspace callback_url or base_url.

    Auth secrets are resolved via the platform SecretResolver before headers
    are built — raw `env:` / `vault:` refs are never sent upstream.
    """

    def __init__(
        self,
        db: Optional[Session] = None,
        *,
        memory_store: Optional[InMemoryOutboxStore] = None,
        http_client: Any = None,
        timeout: float = 30.0,
        secret_resolver: Any = None,
    ):
        from ..secrets import get_default_secret_resolver

        self.db = db
        self.memory_store = memory_store
        self.http_client = http_client
        self.timeout = timeout
        self.secret_resolver = secret_resolver or get_default_secret_resolver()

    def health_check(self, connection: Any = None) -> bool:
        url = None
        if connection is not None:
            url = getattr(connection, "callback_url", None) or getattr(connection, "base_url", None)
        return bool(url)

    def push_confirmation(self, request: ErpPushRequest) -> ErpPushResult:
        conf = request.confirmation
        key = conf.idempotency_key

        existing = self._lookup(key)
        if existing and existing.get("status") == outbox_mod.OUTBOX_SUCCESS:
            return ErpPushResult(
                success=True,
                status=DocumentStatus.ERP_ACKNOWLEDGED,
                idempotency_key=key,
                duplicate=True,
                error=ErpError.of(
                    ERP_DUPLICATE,
                    "Confirmation already pushed to ERP",
                    details={"idempotency_key": key},
                    retryable=False,
                ),
                response_body=existing.get("response_body"),
            )

        target = request.target_url
        if not target:
            return ErpPushResult(
                success=False,
                status=DocumentStatus.ERP_FAILED,
                idempotency_key=key,
                error=ErpError.of(
                    ERP_NOT_CONFIGURED,
                    "Workspace ERP has no callback_url or base_url",
                    retryable=False,
                ),
            )

        request_hash = hashlib.sha256(
            json.dumps(conf.erp_payload(), sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        self._begin(
            key,
            customer_id=request.customer_id,
            correlation_id=conf.correlation_id,
            connection_key=request.connection_key,
            request_hash=request_hash,
        )

        try:
            http_status, body = self._http_post(target, request)
        except TimeoutError as exc:
            self._fail(key, str(exc))
            return ErpPushResult(
                success=False,
                status=DocumentStatus.ERP_FAILED,
                idempotency_key=key,
                error=ErpError.of(ERP_TIMEOUT, str(exc) or "ERP request timed out", retryable=True),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("ERP push failed: %s", exc, exc_info=True)
            self._fail(key, str(exc))
            return ErpPushResult(
                success=False,
                status=DocumentStatus.ERP_FAILED,
                idempotency_key=key,
                error=ErpError.of(ERP_UPDATE_FAILED, str(exc), retryable=True),
            )

        if 200 <= http_status < 300:
            self._success(key, body)
            return ErpPushResult(
                success=True,
                status=DocumentStatus.ERP_ACKNOWLEDGED,
                idempotency_key=key,
                http_status=http_status,
                response_body=body,
            )

        if http_status in (401, 403):
            code, retryable = ERP_AUTH_FAILED, False
        elif 400 <= http_status < 500:
            code, retryable = ERP_REJECTED, False
        else:
            code, retryable = ERP_UPDATE_FAILED, True

        self._fail(key, f"HTTP {http_status}")
        return ErpPushResult(
            success=False,
            status=DocumentStatus.ERP_FAILED,
            idempotency_key=key,
            http_status=http_status,
            response_body=body,
            error=ErpError.of(
                code,
                f"ERP returned status {http_status}",
                http_status=http_status,
                retryable=retryable,
            ),
        )

    # -------------------------------------------------------------- storage

    def _lookup(self, key: str) -> Optional[Dict[str, Any]]:
        if self.memory_store is not None:
            return self.memory_store.get(key)
        if self.db is None:
            return None
        row = outbox_mod.get_by_idempotency_key(self.db, key)
        if row is None:
            return None
        return {
            "status": row.status,
            "response_body": row.response_body,
            "attempt_count": row.attempt_count,
        }

    def _begin(
        self,
        key: str,
        *,
        customer_id: str,
        correlation_id: str,
        connection_key: str,
        request_hash: str,
    ) -> None:
        if self.memory_store is not None:
            self.memory_store.begin(
                key,
                {
                    "customer_id": customer_id,
                    "correlation_id": correlation_id,
                    "connection_key": connection_key,
                    "request_hash": request_hash,
                },
            )
            return
        if self.db is None:
            return
        outbox_mod.begin_attempt(
            self.db,
            idempotency_key=key,
            customer_id=customer_id,
            correlation_id=correlation_id,
            connection_key=connection_key,
            request_hash=request_hash,
        )

    def _success(self, key: str, body: Any) -> None:
        if self.memory_store is not None:
            self.memory_store.success(key, body)
            return
        if self.db is None:
            return
        row = outbox_mod.get_by_idempotency_key(self.db, key)
        if row:
            outbox_mod.mark_success(self.db, row, body)

    def _fail(self, key: str, error: str) -> None:
        if self.memory_store is not None:
            self.memory_store.failed(key, error)
            return
        if self.db is None:
            return
        row = outbox_mod.get_by_idempotency_key(self.db, key)
        if row:
            outbox_mod.mark_failed(self.db, row, error)

    # ----------------------------------------------------------------- HTTP

    def _http_post(self, url: str, request: ErpPushRequest) -> tuple[int, Any]:
        headers = {
            "Content-Type": "application/json",
            IDEMPOTENCY_HEADER: request.confirmation.idempotency_key,
        }
        auth_header = self._auth_header(request)
        if auth_header:
            headers["Authorization"] = auth_header

        payload = {
            "event": "invoice.confirmation",
            "confirmation": request.confirmation.erp_payload(),
        }
        # Optional opaque forward when workspace opts in.
        if (request.extra_config or {}).get("include_raw_response"):
            payload["raw_response"] = request.confirmation.raw_response

        if self.http_client is not None:
            response = self.http_client.post(url, json=payload, headers=headers, timeout=self.timeout)
            return int(response.status_code), _response_body(response)

        import httpx

        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=True) as client:
                response = client.post(url, json=payload, headers=headers)
            return int(response.status_code), _response_body(response)
        except httpx.TimeoutException as exc:
            raise TimeoutError(str(exc) or "ERP request timed out") from exc


    def _auth_header(self, request: ErpPushRequest) -> Optional[str]:
        from ..secrets import SecretResolutionError

        extra = request.extra_config or {}
        auth_type = (request.auth_type or "none").lower().replace("-", "_")
        if auth_type in ("none", "", "null") and not extra.get("bearer_token"):
            return None

        def _resolve(ref: Optional[str]) -> Optional[str]:
            if ref is None or str(ref).strip() == "":
                return None
            try:
                return self.secret_resolver.resolve(ref)
            except SecretResolutionError as exc:
                logger.warning(
                    "ERP auth secret resolution failed code=%s provider=%s",
                    exc.code,
                    exc.provider,
                )
                return None

        # Prefer explicit bearer material (literal or env:/vault: ref).
        token = _resolve(extra.get("bearer_token"))
        if token:
            return f"Bearer {token}"

        if auth_type in ("bearer", "jwt"):
            token = _resolve(request.client_secret_ref) or _resolve(
                extra.get("access_token")
            )
            if token:
                return f"Bearer {token}"
            return None

        if auth_type == "basic":
            import base64

            user = _resolve(request.client_id_ref) or _resolve(extra.get("username"))
            password = _resolve(request.client_secret_ref) or _resolve(
                extra.get("password")
            )
            if user and password:
                raw = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
                return f"Basic {raw}"
            return None

        # api_key style via extra
        if auth_type in ("api_key", "apikey"):
            # Header value only — callers that need custom header names use extra.
            return None

        return None


def _response_body(response: Any) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return getattr(response, "text", None)
