from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os
import json
import time
import logging
from dotenv import load_dotenv

from .database import get_db, Base, engine, ensure_columns_exist
from .database_init import initialize_database, get_database_status
from .api.auth import router as auth_router
from .api.invoices import router as invoices_router
from .api.customers import router as customers_router
from .api.corrections import router as corrections_router
from .api.dashboard import router as dashboard_router
from .api.admin import router as admin_router
from .api.sat import router as sat_router
from .api.sat_canonical import router as sat_canonical_router
from .api.sat_supplier_mapping import router as sat_supplier_mapping_router
from .models.user import ZodiacUser
from .models.invoice import ZodiacInvoiceSuccessEdi, ZodiacInvoiceFailedEdi
from .models.correction_cache import CorrectionCache

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("zodiac-api")

# Create database tables (only if database is available)
try:
    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created successfully")
    
    # Ensure all required columns exist (for existing tables or if create_all didn't add all columns)
    try:
        ensure_columns_exist()
        logger.info("✅ All required columns verified/added successfully")
    except Exception as e:
        logger.warning(f"⚠️ Column check failed (non-critical): {e}")
        
except Exception as e:
    logger.error(f"❌ Could not create database tables: {e}")
    logger.error("Make sure PostgreSQL is running and DATABASE_URL is correct in .env")

# Run database migrations
try:
    logger.info("🚀 Starting database initialization and migrations...")
    migration_success = initialize_database()
    if migration_success:
        logger.info("✅ Database initialization completed successfully")
    else:
        logger.error("❌ Database initialization failed")
except Exception as e:
    logger.error(f"❌ Database initialization error: {e}")

# Initialize FastAPI app
app = FastAPI(
    title="Zodiac API",
    description="RESTful API for Zodiac invoice data extraction",
    version="1.0.0"
)

# CORS middleware configuration
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "https://zodiac-front.vercel.app,zodiac-front.vercel.app,http://localhost:3000,http://127.0.0.1:3000")

origins = CORS_ORIGINS.split(",")
logger.info(f"🌐 CORS origins configured: {origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response logging middleware
@app.middleware("http")
async def log_requests_and_responses(request: Request, call_next):
    start_time = time.time()
    
    # Log request details
    logger.info(f"🚀 REQUEST: {request.method} {request.url}")
    logger.info(f"📋 Headers: {dict(request.headers)}")
    
    # Log request body (if not too large and not binary)
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            # Check content type
            content_type = request.headers.get("content-type", "")
            if "application/json" in content_type:
                body = await request.body()
                if len(body) < 10000:  # Only log if body is not too large
                    try:
                        body_json = json.loads(body.decode())
                        logger.info(f"📦 Request Body: {json.dumps(body_json, indent=2)}")
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        logger.info(f"📦 Request Body: <binary or invalid JSON data>")
                else:
                    logger.info(f"📦 Request Body: <too large to log ({len(body)} bytes)>")
            elif "multipart/form-data" in content_type:
                logger.info(f"📦 Request Body: <multipart/form-data - file upload>")
            else:
                logger.info(f"📦 Request Body: <content-type: {content_type}>")
        except Exception as e:
            logger.warning(f"⚠️ Could not log request body: {e}")
    
    # Process request
    response = await call_next(request)
    
    # Calculate processing time
    process_time = time.time() - start_time
    
    # Log response details
    logger.info(f"✅ RESPONSE: {response.status_code} - {process_time:.3f}s")
    logger.info(f"📋 Response Headers: {dict(response.headers)}")
    
    # Log response body (if not too large)
    if hasattr(response, 'body') and response.body:
        try:
            if len(response.body) < 5000:  # Only log if response is not too large
                try:
                    response_json = json.loads(response.body.decode())
                    logger.info(f"📦 Response Body: {json.dumps(response_json, indent=2)}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    logger.info(f"📦 Response Body: <binary or invalid JSON data>")
            else:
                logger.info(f"📦 Response Body: <too large to log ({len(response.body)} bytes)>")
        except Exception as e:
            logger.warning(f"⚠️ Could not log response body: {e}")
    
    return response

# Health check endpoint
@app.get("/")
async def root():
    return {"message": "Zodiac API is running", "status": "healthy"}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Simple database connectivity test
        db_status = get_database_status()
        
        # Only return basic health status
        return {
            "status": "healthy", 
            "service": "zodiac-api"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "zodiac-api", 
            "error": str(e)
        }

# Include routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(invoices_router, prefix="/api/v1")
app.include_router(customers_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(admin_router, prefix="/api/v1")
app.include_router(sat_router, prefix="/api/v1")
app.include_router(sat_canonical_router, prefix="/api/v1")
app.include_router(sat_supplier_mapping_router, prefix="/api/v1")
app.include_router(corrections_router)

if __name__ == "__main__":
    import uvicorn
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", 8000))
    debug = os.getenv("API_DEBUG", "True").lower() == "true"
    
    uvicorn.run(app, host=host, port=port, reload=debug)
