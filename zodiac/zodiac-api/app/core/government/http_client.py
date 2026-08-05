"""Shared async HTTP helper for government calls (Phase 7)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from .auth import AuthMaterial

logger = logging.getLogger("zodiac-api.government.http")


async def government_request(
    *,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Any = None,
    content: Any = None,
    content_type: str = "application/json",
    auth: Optional[AuthMaterial] = None,
    timeout: float = 30.0,
    http_client: Any = None,
) -> Tuple[int, Any]:
    """
    Perform one HTTP call. Returns (status_code, parsed_body).

    `http_client` may be an object with async `.request(...)` for tests, or None
    to use httpx.AsyncClient.
    """
    hdrs = {"Content-Type": content_type}
    if headers:
        hdrs.update(headers)
    if auth and auth.headers:
        hdrs.update(auth.headers)

    cert = auth.cert if auth else None

    if http_client is not None:
        response = await http_client.request(
            method,
            url,
            headers=hdrs,
            json=json_body if content is None and content_type == "application/json" else None,
            content=content,
            timeout=timeout,
            cert=cert,
        )
        return int(response.status_code), _parse_body(response)

    import httpx

    kwargs: Dict[str, Any] = {
        "headers": hdrs,
        "timeout": timeout,
        "follow_redirects": True,
    }
    if cert:
        kwargs["cert"] = cert

    async with httpx.AsyncClient(**{k: v for k, v in kwargs.items() if k != "headers"}) as client:
        req_kwargs: Dict[str, Any] = {"headers": hdrs}
        if content is not None:
            req_kwargs["content"] = content
        elif json_body is not None:
            req_kwargs["json"] = json_body
        response = await client.request(method, url, **req_kwargs)
        return int(response.status_code), _parse_body(response)


def _parse_body(response: Any) -> Any:
    try:
        return response.json()
    except Exception:  # noqa: BLE001
        return getattr(response, "text", None)
