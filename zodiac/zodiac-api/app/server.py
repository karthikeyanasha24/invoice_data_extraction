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
    except:
        pass

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

# CORS middleware — honor CORS_ORIGINS (Phase 10 hardening).
# Set CORS_ALLOW_ALL=true only for ephemeral local debugging (not production).
_DEFAULT_CORS = (
    "https://www.bridgeedi.com,https://bridgeedi.com,"
    "https://zodiac-front.vercel.app,http://localhost:3000"
)
CORS_ORIGINS = os.getenv("CORS_ORIGINS", _DEFAULT_CORS)
CORS_ALLOW_ALL = os.getenv("CORS_ALLOW_ALL", "false").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
origins = [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
if not origins:
    origins = [o.strip() for o in _DEFAULT_CORS.split(",")]
_cors_origins = ["*"] if CORS_ALLOW_ALL else origins
logger.info(
    "[CORS] allow_all=%s origins=%s",
    CORS_ALLOW_ALL,
    _cors_origins if CORS_ALLOW_ALL else origins,
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

# Import and register routers with safe error handling
logger.info("[INIT] Loading API routers...")

try:
    from .api.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")
    logger.info("[OK] Auth router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load auth router: {err_msg}")

try:
    from .api.invoices import router as invoices_router
    app.include_router(invoices_router, prefix="/api/v1")
    logger.info("[OK] Invoices router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load invoices router: {err_msg}")

try:
    from .api.invoices_v2 import router as invoices_v2_router
    app.include_router(invoices_v2_router, prefix="/api/v1")
    logger.info("[OK] Invoices V2 router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load invoices V2 router: {err_msg}")

try:
    from .api.converted_invoices import router as converted_invoices_router
    app.include_router(converted_invoices_router, prefix="/api/v1")
    logger.info("[OK] Converted Invoices router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load converted invoices router: {err_msg}")

try:
    from .api.customers import router as customers_router
    app.include_router(customers_router, prefix="/api/v1")
    logger.info("[OK] Customers router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load customers router: {err_msg}")

try:
    from .api.corrections import router as corrections_router
    app.include_router(corrections_router)
    logger.info("[OK] Corrections router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load corrections router: {err_msg}")

try:
    from .api.dashboard import router as dashboard_router
    app.include_router(dashboard_router, prefix="/api/v1")
    logger.info("[OK] Dashboard router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load dashboard router: {err_msg}")

try:
    from .api.adaptive_query import router as adaptive_query_router
    app.include_router(adaptive_query_router)
    logger.info("[OK] Adaptive query router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load adaptive query router: {err_msg}")
    # Do not return 404 for adaptive-query path when router import fails.
    # Return a clear 503 so the frontend can surface actionable diagnostics.
    @app.api_route("/api/query/adaptive", methods=["GET", "POST"])
    @app.api_route("/api/v1/query/adaptive", methods=["GET", "POST"])
    async def _adaptive_query_unavailable():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Adaptive query router failed to load. Check server logs for import errors.",
        )

try:
    from .api.admin import router as admin_router
    app.include_router(admin_router, prefix="/api/v1")
    logger.info("[OK] Admin router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load admin router: {err_msg}")

try:
    from .api.sat import router as sat_router
    app.include_router(sat_router, prefix="/api/v1")
    logger.info("[OK] SAT router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load SAT router: {err_msg}")

try:
    from .api.sat_canonical import router as sat_canonical_router
    app.include_router(sat_canonical_router, prefix="/api/v1")
    logger.info("[OK] SAT Canonical router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load SAT Canonical router: {err_msg}")

try:
    from .api.sat_supplier_mapping import router as sat_supplier_mapping_router
    app.include_router(sat_supplier_mapping_router, prefix="/api/v1")
    logger.info("[OK] SAT Supplier Mapping router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load SAT Supplier Mapping router: {err_msg}")

try:
    from .api.sat_simple_merge import router as sat_simple_merge_router
    app.include_router(sat_simple_merge_router, prefix="/api/v1")
    logger.info("[OK] SAT Simple Merge router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load SAT Simple Merge router: {err_msg}")

try:
    from .api.supplier_tokens import router as supplier_tokens_router
    app.include_router(supplier_tokens_router, prefix="/api/v1")
    logger.info("[OK] Supplier Tokens router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Supplier Tokens router: {err_msg}")


try:
    from .api.customer_users import router as customer_users_router
    app.include_router(customer_users_router, prefix="/api/v1")
    logger.info("[OK] Customer Users router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Customer Users router: {err_msg}")

try:
    from .api.certificates import router as certificates_router
    app.include_router(certificates_router, prefix="/api/v1")
    logger.info("[OK] Certificates router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Certificates router: {err_msg}")

# Phase 2 — Customer Workspace (additive; does not replace existing customer APIs)
try:
    from .api.workspace import router as workspace_router
    app.include_router(workspace_router, prefix="/api/v1")
    logger.info("[OK] Workspace router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Workspace router: {err_msg}")

# Phase 4 — Invoice Processing Pipeline (opt-in; does not replace /sat/*)
try:
    from .api.pipeline import router as pipeline_router
    app.include_router(pipeline_router, prefix="/api/v1")
    logger.info("[OK] Pipeline router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Pipeline router: {err_msg}")

# Phase 8 — Enterprise Monitoring (additive; observes pipeline only)
try:
    from .api.monitoring import router as monitoring_router
    app.include_router(monitoring_router, prefix="/api/v1")
    logger.info("[OK] Monitoring router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load Monitoring router: {err_msg}")

# Phase 9 — AI Operational Intelligence (additive; monitoring consumer only)
try:
    from .api.ai_ops import router as ai_ops_router
    app.include_router(ai_ops_router, prefix="/api/v1")
    logger.info("[OK] AI Ops router loaded")
except Exception as e:
    err_msg = str(e).encode('ascii', 'replace').decode('ascii')
    logger.error(f"[ERROR] Failed to load AI Ops router: {err_msg}")

logger.info("[OK] Zodiac API initialized successfully")


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
