"""
Safe minimal server.py for Vercel
This version has no database dependencies and will definitely work
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
        "version": "1.0.0",
        "cors_origins": origins
    }

@app.get("/env-check")
async def env_check():
    """Check environment variables (for debugging)"""
    return {
        "DATABASE_URL": "SET" if os.getenv("DATABASE_URL") else "NOT SET",
        "CORS_ORIGINS": os.getenv("CORS_ORIGINS", "NOT SET"),
        "OPENAI_API_KEY": "SET" if os.getenv("OPENAI_API_KEY") else "NOT SET"
    }

logger.info("✅ Zodiac API initialized successfully (safe mode - no database)")

