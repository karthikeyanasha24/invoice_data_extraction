"""
Zodiac API - FastAPI server optimized for Vercel serverless deployment
"""
import sys
import io

# Fix Windows console encoding for Unicode characters
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

from typing import Any, Callable, Dict, Optional, Sequence, Tuple

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables (Zodiac's .env first)
load_dotenv()

# Option B: load invoice-bot .env so the single backend uses invoice-bot config for Generative AI and shared vars
# Set INVOICE_BOT_ENV_PATH to the full path to invoice-bot's .env, or INVOICE_BOT_CONFIG_DIR to the invoice-bot folder.
# If unset, defaults to repo_root/invoice-bot/.env (repo root = parent of zodiac-api's parent's parent).
_invoice_bot_env = os.getenv("INVOICE_BOT_ENV_PATH")
if not _invoice_bot_env and os.getenv("INVOICE_BOT_CONFIG_DIR"):
    _invoice_bot_env = str(Path(os.getenv("INVOICE_BOT_CONFIG_DIR")).resolve() / ".env")
if not _invoice_bot_env:
    _repo_root = Path(__file__).resolve().parent.parent.parent.parent
    _invoice_bot_env = str(_repo_root / "invoice-bot" / ".env")
_invoice_bot_env_path = Path(_invoice_bot_env)
if _invoice_bot_env_path.exists():
    load_dotenv(_invoice_bot_env, override=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("zodiac-api")
if _invoice_bot_env_path.exists():
    logger.info("Loaded invoice-bot env from %s", _invoice_bot_env)

# Initialize FastAPI app
app = FastAPI(
    title="Zodiac API",
    description="RESTful API for Zodiac invoice data extraction",
    version="1.0.0"
)

from .core.cors_origins import parse_cors_allow_all, resolve_cors_origins, REQUIRED_CORS

# CORS middleware — honor CORS_ORIGINS (Phase 10 hardening).
# Set CORS_ALLOW_ALL=true only for ephemeral local debugging (not production).
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "")
CORS_ALLOW_ALL = parse_cors_allow_all(os.getenv("CORS_ALLOW_ALL", "false"))
origins = resolve_cors_origins(CORS_ORIGINS or "", allow_all=False)  # union list for logs
_cors_origins = resolve_cors_origins(CORS_ORIGINS or "", allow_all=CORS_ALLOW_ALL)
_REQUIRED_CORS = REQUIRED_CORS
logger.info(
    "[CORS] allow_all=%s origins=%s",
    CORS_ALLOW_ALL,
    _cors_origins,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=not CORS_ALLOW_ALL,  # credentials incompatible with "*"
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# NOTE: Do NOT add @app.options("/{full_path:path}") - it matches any path and causes
# 405 Method Not Allowed for GET/POST requests (e.g. /api/v1/dashboard/v2/inbound).
# CORSMiddleware above already handles OPTIONS preflight automatically.

# Health check endpoints
@app.get("/")
async def root():
    return {
        "message": "Zodiac API is running",
        "status": "healthy",
        "version": "1.0.0"
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "zodiac-api",
        "version": "1.0.0"
    }


@app.get("/health/ready")
async def readiness_check():
    """
    Readiness probe for enterprise tables (PR3).
    Liveness remains /health. Returns 503 when required platform tables are missing.
    """
    from fastapi.responses import JSONResponse
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from .database import engine

    required_tables = [
        "workspace_settings",
        "workspace_erp_connections",
        "workspace_adapter_config",
        "erp_push_outbox",
        "pipeline_timelines",
        "pipeline_events",
        "pipeline_metrics",
        "alert_history",
    ]
    try:
        existing = set(sa_inspect(engine).get_table_names())
        missing = [t for t in required_tables if t not in existing]
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        body = {
            "status": "ready" if not missing else "not_ready",
            "service": "zodiac-api",
            "missing_tables": missing,
            "checked_tables": required_tables,
        }
        if missing:
            return JSONResponse(status_code=503, content=body)
        return body
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "zodiac-api",
                "error": str(e)[:500],
                "missing_tables": required_tables,
                "checked_tables": required_tables,
            },
        )


# Import and register routers. Failures are logged with traceback and recorded
# on GET /health/routers so a missing route is diagnosable (not a silent 404).
ROUTER_STATUS: Dict[str, Dict[str, Any]] = {}


def _register_router(
    name: str,
    loader: Callable,
    *,
    prefix: Optional[str] = None,
    unavailable_paths: Optional[Sequence[Tuple[str, Sequence[str]]]] = None,
) -> None:
    try:
        loaded_router = loader()
        if prefix:
            app.include_router(loaded_router, prefix=prefix)
        else:
            app.include_router(loaded_router)
        ROUTER_STATUS[name] = {"loaded": True, "error_type": None}
        logger.info("[OK] %s router loaded", name)
    except Exception as e:
        err_msg = str(e).encode("ascii", "replace").decode("ascii")
        logger.exception("[ERROR] Failed to load %s router: %s", name, err_msg)
        ROUTER_STATUS[name] = {
            "loaded": False,
            "error_type": type(e).__name__,
        }
        if unavailable_paths:
            async def _unavailable(router_name: str = name):
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=(
                        f"{router_name} router failed to load "
                        f"({ROUTER_STATUS[router_name].get('error_type')}). "
                        "See GET /health/routers."
                    ),
                )

            for path, methods in unavailable_paths:
                app.add_api_route(path, _unavailable, methods=list(methods))


logger.info("[INIT] Loading API routers...")


def _load_auth():
    from .api.auth import router as r
    return r


def _load_invoices():
    from .api.invoices import router as r
    return r


def _load_invoices_v2():
    from .api.invoices_v2 import router as r
    return r


def _load_converted_invoices():
    from .api.converted_invoices import router as r
    return r


def _load_customers():
    from .api.customers import router as r
    return r


def _load_corrections():
    from .api.corrections import router as r
    return r


def _load_dashboard():
    from .api.dashboard import router as r
    return r


def _load_adaptive_query():
    from .api.adaptive_query import router as r
    return r


def _load_admin():
    from .api.admin import router as r
    return r


def _load_sat():
    from .api.sat import router as r
    return r


def _load_sat_canonical():
    from .api.sat_canonical import router as r
    return r


def _load_sat_supplier_mapping():
    from .api.sat_supplier_mapping import router as r
    return r


def _load_sat_simple_merge():
    from .api.sat_simple_merge import router as r
    return r


def _load_supplier_tokens():
    from .api.supplier_tokens import router as r
    return r


def _load_customer_users():
    from .api.customer_users import router as r
    return r


def _load_certificates():
    from .api.certificates import router as r
    return r


def _load_workspace():
    from .api.workspace import router as r
    return r


def _load_pipeline():
    from .api.pipeline import router as r
    return r


def _load_monitoring():
    from .api.monitoring import router as r
    return r


def _load_ai_ops():
    from .api.ai_ops import router as r
    return r


_register_router("auth", _load_auth, prefix="/api/v1")
_register_router("invoices", _load_invoices, prefix="/api/v1")
_register_router("invoices_v2", _load_invoices_v2, prefix="/api/v1")
_register_router("converted_invoices", _load_converted_invoices, prefix="/api/v1")
_register_router("customers", _load_customers, prefix="/api/v1")
_register_router("corrections", _load_corrections)
_register_router(
    "dashboard",
    _load_dashboard,
    prefix="/api/v1",
    unavailable_paths=(
        ("/api/v1/dashboard/{full_path:path}", ("GET", "POST", "PUT", "PATCH", "DELETE")),
    ),
)
_register_router(
    "adaptive_query",
    _load_adaptive_query,
    unavailable_paths=(
        ("/api/query/adaptive", ("GET", "POST")),
        ("/api/v1/query/adaptive", ("GET", "POST")),
    ),
)
_register_router("admin", _load_admin, prefix="/api/v1")
_register_router("sat", _load_sat, prefix="/api/v1")
_register_router("sat_canonical", _load_sat_canonical, prefix="/api/v1")
_register_router("sat_supplier_mapping", _load_sat_supplier_mapping, prefix="/api/v1")
_register_router("sat_simple_merge", _load_sat_simple_merge, prefix="/api/v1")
_register_router("supplier_tokens", _load_supplier_tokens, prefix="/api/v1")
_register_router("customer_users", _load_customer_users, prefix="/api/v1")
_register_router("certificates", _load_certificates, prefix="/api/v1")
_register_router("workspace", _load_workspace, prefix="/api/v1")
_register_router("pipeline", _load_pipeline, prefix="/api/v1")
_register_router("monitoring", _load_monitoring, prefix="/api/v1")
_register_router("ai_ops", _load_ai_ops, prefix="/api/v1")

failed_routers = [k for k, v in ROUTER_STATUS.items() if not v.get("loaded")]
if failed_routers:
    logger.error("[INIT] Routers failed to load: %s", ", ".join(failed_routers))
else:
    logger.info("[OK] Zodiac API initialized successfully — all routers loaded")


@app.get("/health/routers")
async def router_health():
    """Diagnose which API routers registered. Does not include secrets or stack traces."""
    failed = [k for k, v in ROUTER_STATUS.items() if not v.get("loaded")]
    return {
        "status": "ok" if not failed else "degraded",
        "loaded_count": sum(1 for v in ROUTER_STATUS.values() if v.get("loaded")),
        "failed": failed,
        "routers": ROUTER_STATUS,
    }


@app.on_event("startup")
async def _bridgeedi_startup():
    """
    Pilot deployability: register adapters, optional schema create, config posture.
    Why: cold pipeline previously relied on lazy bootstrap; missing tables failed ready.
    Risk: low — opt-in schema; config checks log only.
    Rollback: no-op if startup import fails (logged).
    """
    try:
        from .core.startup import run_startup

        report = run_startup()
        logger.info("[startup] BridgeEDI startup complete: %s", report)
    except Exception as e:
        err_msg = str(e).encode("ascii", "replace").decode("ascii")
        logger.error("[startup] BridgeEDI startup failed (non-fatal): %s", err_msg)


if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    # Reason: default True was unsafe for prod-like runs via `python -m app.server`.
    # Risk: low — local `start.py` still uses reload=True explicitly.
    # Rollback: set API_DEBUG=true in .env for local reload via this entrypoint.
    debug = os.getenv("API_DEBUG", "false").lower() == "true"

    uvicorn.run(app, host=host, port=port, reload=debug)
