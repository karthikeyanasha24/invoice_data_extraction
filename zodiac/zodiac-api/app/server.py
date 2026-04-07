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

from fastapi import FastAPI
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

# CORS middleware configuration
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS", 
    "https://www.bridgeedi.com,https://bridgeedi.com,https://zodiac-front.vercel.app,http://localhost:3000"
)

origins = [origin.strip() for origin in CORS_ORIGINS.split(",")]
logger.info(f"[CORS] Origins configured: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now (can restrict later if needed)
    allow_credentials=True,
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

logger.info("[OK] Zodiac API initialized successfully")

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("API_DEBUG", "True").lower() == "true"
    
    uvicorn.run(app, host=host, port=port, reload=debug)
