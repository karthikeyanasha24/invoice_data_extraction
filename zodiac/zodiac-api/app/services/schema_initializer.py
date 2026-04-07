"""
Schema Initializer - One-time setup for AI knowledge base.

Run this script to populate the schema cache with table information,
descriptions, and query patterns for faster AI analysis.
"""
import logging
import sys
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from .table_schema_manager import (
    ensure_schema_tables,
    introspect_table_schema,
    cache_table_schema,
    cache_query_pattern,
)
from .query_optimizer import BUILTIN_PATTERNS
from .sap_sql_agent import SAP_TABLE_DESCRIPTIONS

logger = logging.getLogger(__name__)


# Core SAP tables to initialize (most commonly used)
CORE_SAP_TABLES = [
    # Sales and Billing (highest priority)
    "VBRP", "VBRK", "VBAK", "VBAP",
    # Customer Master
    "KNA1", "KNVV", "KNVP",
    # Material Master
    "MAKT", "MARC", "MVKE",
    # Financial
    "BSAD", "BSEG",
    # Outbound Logistics
    "LIKP", "LIPS",
    # Purchasing
    "LFA1", "EKKO", "EKPO",
    # Vendor Invoices
    "RBKP", "RSEG",
]


def initialize_ai_knowledge_base(
    db: Session,
    sap_db: Optional[Session] = None,
    tables: Optional[List[str]] = None,
    skip_patterns: bool = False,
) -> Dict[str, Any]:
    """
    Initialize the AI knowledge base with table schemas and query patterns.
    
    Args:
        db: Main database session (for storing cache)
        sap_db: Optional SAP database session (if using separate SAP DB)
        tables: List of tables to initialize (defaults to CORE_SAP_TABLES)
        skip_patterns: Skip pattern initialization
    
    Returns:
        Summary dictionary with success/failure counts
    """
    logger.info("=" * 70)
    logger.info("🚀 INITIALIZING AI KNOWLEDGE BASE")
    logger.info("=" * 70)
    
    results = {
        "tables_cached": 0,
        "tables_failed": 0,
        "patterns_cached": 0,
        "total_time_ms": 0,
    }
    
    import time
    start_time = time.time()
    
    try:
        # Ensure tables exist
        logger.info("📊 Creating schema management tables...")
        ensure_schema_tables(db)
        
        # Initialize table schemas
        target_tables = tables or CORE_SAP_TABLES
        logger.info(f"📊 Initializing {len(target_tables)} table schemas...")
        
        for idx, table_name in enumerate(target_tables, 1):
            try:
                logger.info(f"[{idx}/{len(target_tables)}] Processing {table_name}...")
                
                # Introspect schema
                schema_info = introspect_table_schema(db, table_name, sap_db)
                
                if not schema_info:
                    logger.warning(f"⚠️ Could not introspect {table_name}")
                    results["tables_failed"] += 1
                    continue
                
                # Get description from SAP_TABLE_DESCRIPTIONS
                description = SAP_TABLE_DESCRIPTIONS.get(table_name, "")
                if not description:
                    # Try lowercase
                    description = SAP_TABLE_DESCRIPTIONS.get(table_name.lower(), f"{table_name} table")
                
                # Cache schema with embedding
                success = cache_table_schema(db, table_name, schema_info, description, sap_db)
                
                if success:
                    results["tables_cached"] += 1
                    logger.info(f"✅ Cached {table_name} ({schema_info.get('row_count', 0)} rows)")
                else:
                    results["tables_failed"] += 1
                    logger.warning(f"⚠️ Failed to cache {table_name}")
            
            except Exception as table_err:
                logger.error(f"❌ Error processing {table_name}: {table_err}")
                results["tables_failed"] += 1
        
        # Initialize query patterns
        if not skip_patterns:
            logger.info(f"📊 Initializing {len(BUILTIN_PATTERNS)} query patterns...")
            
            for pattern in BUILTIN_PATTERNS:
                try:
                    # Extract example queries from pattern
                    example_queries = [
                        pattern["pattern_template"].format(
                            dimension="customer", 
                            year=2024, 
                            n=10,
                            period="month"
                        )
                    ]
                    
                    success = cache_query_pattern(
                        db=db,
                        pattern_name=pattern["pattern_name"],
                        pattern_template=pattern["pattern_template"],
                        sql_template=pattern["sql_template"],
                        example_queries=example_queries,
                        required_tables=pattern["required_tables"],
                    )
                    
                    if success:
                        results["patterns_cached"] += 1
                        logger.info(f"✅ Cached pattern: {pattern['pattern_name']}")
                
                except Exception as pattern_err:
                    logger.error(f"❌ Error caching pattern {pattern.get('pattern_name')}: {pattern_err}")
        
        # Create / refresh sap_billing_lines_v convenience view (VBRP+VBRK pre-joined)
        if sap_db is not None:
            try:
                from .smart_query_learner import ensure_sap_billing_view
                ensure_sap_billing_view(sap_db)
            except Exception as view_err:
                logger.warning("sap_billing_lines_v view creation failed (non-critical): %s", view_err)

        # Calculate total time
        results["total_time_ms"] = int((time.time() - start_time) * 1000)

        logger.info("=" * 70)
        logger.info("✅ AI KNOWLEDGE BASE INITIALIZATION COMPLETE")
        logger.info(f"   Tables cached: {results['tables_cached']}")
        logger.info(f"   Tables failed: {results['tables_failed']}")
        logger.info(f"   Patterns cached: {results['patterns_cached']}")
        logger.info(f"   Total time: {results['total_time_ms']}ms")
        logger.info("=" * 70)
        
        return results
    
    except Exception as e:
        logger.error(f"❌ Knowledge base initialization failed: {e}", exc_info=True)
        results["error"] = str(e)
        return results


def refresh_table_statistics(
    db: Session,
    sap_db: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Refresh statistics for all cached tables.
    Run this periodically (e.g., daily) to keep statistics current.
    
    Args:
        db: Main database session
        sap_db: Optional SAP database session
    
    Returns:
        Summary of updates
    """
    from .table_schema_manager import get_all_cached_schemas, update_table_statistics
    
    logger.info("🔄 Refreshing table statistics...")
    
    results = {
        "tables_updated": 0,
        "tables_failed": 0,
    }
    
    try:
        schemas = get_all_cached_schemas(db)
        
        for schema in schemas:
            table_name = schema["table_name"]
            try:
                success = update_table_statistics(db, table_name, sap_db)
                if success:
                    results["tables_updated"] += 1
                else:
                    results["tables_failed"] += 1
            
            except Exception as e:
                logger.error(f"Failed to update {table_name}: {e}")
                results["tables_failed"] += 1
        
        logger.info(f"✅ Refreshed {results['tables_updated']} tables")
        return results
    
    except Exception as e:
        logger.error(f"❌ Statistics refresh failed: {e}")
        results["error"] = str(e)
        return results


# CLI interface
if __name__ == "__main__":
    """
    Run as: python -m app.services.schema_initializer
    """
    from ..database import SessionLocal, get_sap_session
    from ..config.config import USE_SAP_DB_FOR_AI
    
    print("🚀 AI Knowledge Base Initializer")
    print("=" * 70)
    
    db = SessionLocal()
    sap_db = get_sap_session() if USE_SAP_DB_FOR_AI else None
    
    try:
        results = initialize_ai_knowledge_base(db, sap_db)
        
        print("\n✅ Initialization Complete!")
        print(f"   Tables cached: {results['tables_cached']}")
        print(f"   Patterns cached: {results['patterns_cached']}")
        print(f"   Time: {results['total_time_ms'] / 1000:.1f}s")
        
        if results.get("error"):
            print(f"\n❌ Error: {results['error']}")
            sys.exit(1)
    
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    finally:
        db.close()
        if sap_db:
            sap_db.close()
