"""
Server with database support and safe error handling for Vercel
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("zodiac-api")

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
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

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

# Import and register routers with error handling
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

logger.info("✅ Zodiac API initialized successfully with database support")

