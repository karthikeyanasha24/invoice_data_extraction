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
ENABLE_SECONDARY_LLM_SQL = os.getenv("ENABLE_SECONDARY_LLM_SQL", "true").lower() == "true"

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

# LangGraph generative SQL + summaries (/dashboard/ai-analysis/chat → multi_stage_planner)
# Prefer GPT-5; override per deploy: LANGGRAPH_OPENAI_MODEL=gpt-5-mini
LANGGRAPH_OPENAI_MODEL = os.getenv(
    "LANGGRAPH_OPENAI_MODEL",
    os.getenv("OPENAI_MODEL", "gpt-5"),
)
# Stronger model for SQL generation/repair vs. summarization (defaults to same as LANGGRAPH_OPENAI_MODEL)
LANGGRAPH_SQL_MODEL = os.getenv("LANGGRAPH_SQL_MODEL", LANGGRAPH_OPENAI_MODEL)
LANGGRAPH_ANSWER_MODEL = os.getenv("LANGGRAPH_ANSWER_MODEL", LANGGRAPH_OPENAI_MODEL)
# Cap unbounded SELECT rows returned from SAP (avoids accidental full scans)
LANGGRAPH_SELECT_ROW_CAP = int(os.getenv("LANGGRAPH_SELECT_ROW_CAP", "500"))
# Max tables included in the prompt schema block (breadth vs. token limit)
LANGGRAPH_MAX_SCHEMA_TABLES = int(os.getenv("LANGGRAPH_MAX_SCHEMA_TABLES", "12"))
# When the question implies multi-table logic, temporarily add this many extra tables (capped below).
LANGGRAPH_SCHEMA_JOIN_BOOST = int(os.getenv("LANGGRAPH_SCHEMA_JOIN_BOOST", "4"))
LANGGRAPH_MAX_SCHEMA_TABLES_HARD_CAP = int(os.getenv("LANGGRAPH_MAX_SCHEMA_TABLES_HARD_CAP", "20"))
# Per-table column lines in the prompt (prioritizes keys, amounts, dates, names)
LANGGRAPH_MAX_COLUMNS_PER_TABLE = int(os.getenv("LANGGRAPH_MAX_COLUMNS_PER_TABLE", "48"))
LANGGRAPH_SQL_MAX_TOKENS = int(os.getenv("LANGGRAPH_SQL_MAX_TOKENS", "4096"))
LANGGRAPH_ANSWER_MAX_TOKENS = int(os.getenv("LANGGRAPH_ANSWER_MAX_TOKENS", "1536"))
# Skip the final fact-check LLM pass (saves one round-trip; slightly higher hallucination risk)
LANGGRAPH_SKIP_VERIFY_ANSWER = os.getenv("LANGGRAPH_SKIP_VERIFY_ANSWER", "false").lower() in (
    "1",
    "true",
    "yes",
)
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

# The web app now uses a single database connection via DATABASE_URL.
# Keep these names as compatibility constants for older imports, but route them
# to the primary database instead of reading SAP_* environment variables.
AI_CONTEXT_SOURCE = os.getenv("AI_CONTEXT_SOURCE", "zodiac").lower().strip()
SAP_DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("\ufeffDATABASE_URL")
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

