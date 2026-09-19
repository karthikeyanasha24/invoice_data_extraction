"""CORS origin resolution — required live frontends cannot be dropped by a partial env list."""
from __future__ import annotations

from typing import Iterable, List, Sequence

REQUIRED_CORS = (
    "https://www.bridgeedi.com",
    "https://bridgeedi.com",
    "https://zodiac-front.vercel.app",
    "https://zodiac-front-woad.vercel.app",
)

DEFAULT_CORS = (
    "https://www.bridgeedi.com,https://bridgeedi.com,"
    "https://zodiac-front.vercel.app,https://zodiac-front-woad.vercel.app,"
    "http://localhost:3000"
)


def parse_cors_allow_all(value: str) -> bool:
    return (value or "false").strip().lower() in ("1", "true", "yes", "on")


def resolve_cors_origins(
    cors_origins_env: str,
    *,
    allow_all: bool,
    required: Sequence[str] = REQUIRED_CORS,
    default: str = DEFAULT_CORS,
) -> List[str]:
    origins = [o.strip().rstrip("/") for o in (cors_origins_env or "").split(",") if o.strip()]
    if not origins:
        origins = [o.strip() for o in default.split(",") if o.strip()]
    for req in required:
        if req not in origins:
            origins.append(req)
    if allow_all:
        return ["*"]
    return origins


def origin_is_allowed(origin: str, allowed: Iterable[str]) -> bool:
    allowed_list = list(allowed)
    if "*" in allowed_list:
        return True
    o = (origin or "").strip().rstrip("/")
    return o in {a.rstrip("/") for a in allowed_list}
