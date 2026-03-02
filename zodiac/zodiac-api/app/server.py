"""
Zodiac API - FastAPI server optimized for Vercel serverless deployment
"""
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
logger.info(f"🌐 CORS origins configured: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for now (can restrict later if needed)
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

# Explicit OPTIONS handler for CORS preflight requests
@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Handle CORS preflight OPTIONS requests"""
    return {"status": "ok"}

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
logger.info("🔄 Loading API routers...")

try:
    from .api.auth import router as auth_router
    app.include_router(auth_router, prefix="/api/v1")
    logger.info("✅ Auth router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load auth router: {e}")

try:
    from .api.invoices import router as invoices_router
    app.include_router(invoices_router, prefix="/api/v1")
    logger.info("✅ Invoices router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load invoices router: {e}")

try:
    from .api.invoices_v2 import router as invoices_v2_router
    app.include_router(invoices_v2_router, prefix="/api/v1")
    logger.info("✅ Invoices V2 router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load invoices V2 router: {e}")

try:
    from .api.converted_invoices import router as converted_invoices_router
    app.include_router(converted_invoices_router, prefix="/api/v1")
    logger.info("✅ Converted Invoices router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load converted invoices router: {e}")

try:
    from .api.customers import router as customers_router
    app.include_router(customers_router, prefix="/api/v1")
    logger.info("✅ Customers router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load customers router: {e}")

try:
    from .api.corrections import router as corrections_router
    app.include_router(corrections_router)
    logger.info("✅ Corrections router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load corrections router: {e}")

try:
    from .api.dashboard import router as dashboard_router
    app.include_router(dashboard_router, prefix="/api/v1")
    logger.info("✅ Dashboard router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load dashboard router: {e}")

try:
    from .api.admin import router as admin_router
    app.include_router(admin_router, prefix="/api/v1")
    logger.info("✅ Admin router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load admin router: {e}")

try:
    from .api.sat import router as sat_router
    app.include_router(sat_router, prefix="/api/v1")
    logger.info("✅ SAT router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load SAT router: {e}")

try:
    from .api.sat_canonical import router as sat_canonical_router
    app.include_router(sat_canonical_router, prefix="/api/v1")
    logger.info("✅ SAT Canonical router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load SAT Canonical router: {e}")

try:
    from .api.sat_supplier_mapping import router as sat_supplier_mapping_router
    app.include_router(sat_supplier_mapping_router, prefix="/api/v1")
    logger.info("✅ SAT Supplier Mapping router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load SAT Supplier Mapping router: {e}")

try:
    from .api.sat_simple_merge import router as sat_simple_merge_router
    app.include_router(sat_simple_merge_router, prefix="/api/v1")
    logger.info("✅ SAT Simple Merge router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load SAT Simple Merge router: {e}")

try:
    from .api.supplier_tokens import router as supplier_tokens_router
    app.include_router(supplier_tokens_router, prefix="/api/v1")
    logger.info("✅ Supplier Tokens router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load Supplier Tokens router: {e}")


try:
    from .api.customer_users import router as customer_users_router
    app.include_router(customer_users_router, prefix="/api/v1")
    logger.info("✅ Customer Users router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load Customer Users router: {e}")

try:
    from .api.certificates import router as certificates_router
    app.include_router(certificates_router, prefix="/api/v1")
    logger.info("✅ Certificates router loaded")
except Exception as e:
    logger.error(f"❌ Failed to load Certificates router: {e}")

logger.info("✅ Zodiac API initialized successfully")

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("API_DEBUG", "True").lower() == "true"
    
    uvicorn.run(app, host=host, port=port, reload=debug)
