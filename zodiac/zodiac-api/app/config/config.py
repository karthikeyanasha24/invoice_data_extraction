"""Configuration module for storage and environment setup."""
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger("zodiac-api.config")

# Environment configuration
DEPLOY_ENV = os.getenv("DEPLOY_ENV", "DEV")
BLOB_READ_WRITE_TOKEN = os.getenv("BLOB_READ_WRITE_TOKEN")
OPENAI_API_KEY = os.getenv("OPEN_AI_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
ENABLE_MULTI_MODEL = os.getenv("ENABLE_MULTI_MODEL", "false").lower() == "true"

# AI Analysis Model Configuration
# For insights/summaries, use a more powerful model. Options:
#   "gpt-4o" - OpenAI GPT-4 Optimized (best reasoning, $$$)
#   "gpt-4o-mini" - OpenAI GPT-4 Mini (fast, balanced, $$)
#   "claude-3-5-sonnet" - Anthropic Claude 3.5 (excellent analysis, $$$)
#   "gemini-1.5-pro" - Google Gemini 1.5 Pro (great insights, $$)
#   "gemini-1.5-flash" - Google Gemini Flash (fast, $)
#   "openrouter/anthropic/claude-3.5-sonnet" - Via OpenRouter
AI_INSIGHTS_MODEL = os.getenv("AI_INSIGHTS_MODEL", "gpt-4o-mini")
AI_FAST_MODEL = os.getenv("AI_FAST_MODEL", "gpt-4o-mini")  # For fast ops (action classification, table selection)
# Import Vercel Blob for production file storage
try:
    import vercel_blob
    VERCEL_BLOB_AVAILABLE = True
    logger.info("✅ Vercel Blob package imported successfully")
except ImportError:
    VERCEL_BLOB_AVAILABLE = False
    logger.warning("⚠️ Vercel Blob not available - will use local storage only")

# Determine if we MUST use blob storage (PROD + token provided)
MUST_USE_BLOB_STORAGE = DEPLOY_ENV == "PROD" and bool(BLOB_READ_WRITE_TOKEN)
USE_BLOB_STORAGE = MUST_USE_BLOB_STORAGE and VERCEL_BLOB_AVAILABLE

# Local storage directories
UPLOAD_DIR = Path("uploads")
EDI_DIR = Path("converted")

# Generative AI context source: "zodiac" (default, use app DB) or "sap" (use SAP database)
AI_CONTEXT_SOURCE = os.getenv("AI_CONTEXT_SOURCE", "zodiac").lower().strip()
# SAP database URL for Generative AI context (only used when AI_CONTEXT_SOURCE=sap).
# Examples: SAP HANA "hana://user:pass@host:30015", SQL Server "mssql+pyodbc://...", Oracle "oracle+cx_oracle://..."
SAP_DATABASE_URL = os.getenv("SAP_DATABASE_URL") or os.getenv("SAP_DB_URL")
USE_SAP_DB_FOR_AI = AI_CONTEXT_SOURCE == "sap" and bool(SAP_DATABASE_URL)

# AI Query Optimization Settings
ENABLE_QUERY_PATTERN_MATCHING = os.getenv("ENABLE_QUERY_PATTERN_MATCHING", "true").lower() == "true"
AI_SCHEMA_CACHE_TTL_HOURS = int(os.getenv("AI_SCHEMA_CACHE_TTL_HOURS", "24"))
FORCE_NEW_ACTION_FOR_DATA_QUERIES = os.getenv("FORCE_NEW_ACTION_FOR_DATA_QUERIES", "true").lower() == "true"


def initialize_storage():
    """Initialize storage system (blob or local)."""
    logger.info("=" * 60)
    logger.info("🗂️ FILE STORAGE CONFIGURATION")
    logger.info("=" * 60)
    logger.info(f"🌍 DEPLOY_ENV: {DEPLOY_ENV}")
    logger.info(f"🔑 BLOB_READ_WRITE_TOKEN: {'✅ Set' if BLOB_READ_WRITE_TOKEN else '❌ Not set'}")
    logger.info(f"📦 VERCEL_BLOB_AVAILABLE: {VERCEL_BLOB_AVAILABLE}")
    logger.info(f"🚨 MUST_USE_BLOB_STORAGE: {MUST_USE_BLOB_STORAGE}")
    logger.info(f"✅ FINAL DECISION - USE_BLOB_STORAGE: {USE_BLOB_STORAGE}")
    
    if MUST_USE_BLOB_STORAGE:
        logger.info("🚨 MANDATORY BLOB STORAGE REQUIRED")
        if not VERCEL_BLOB_AVAILABLE:
            logger.error("❌ CRITICAL ERROR: Vercel Blob package not available!")
            raise RuntimeError("Vercel Blob package not available but required for PROD deployment")
    
    if USE_BLOB_STORAGE:
        logger.info("🚀 STORAGE MODE: VERCEL BLOB STORAGE")
        try:
            logger.info("🔧 Initializing Vercel Blob API...")
            logger.info("✅ Vercel Blob API initialized successfully")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Vercel Blob API: {e}")
            if MUST_USE_BLOB_STORAGE:
                raise RuntimeError(f"Failed to initialize mandatory Vercel Blob API: {str(e)}")
    else:
        logger.info("📁 STORAGE MODE: LOCAL FILE STORAGE")
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        EDI_DIR.mkdir(parents=True, exist_ok=True)
    
    logger.info("=" * 60)


# Initialize storage on module import
initialize_storage()

