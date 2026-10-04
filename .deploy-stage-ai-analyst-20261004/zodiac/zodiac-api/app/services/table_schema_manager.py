"""
Table Schema Manager - Persistent schema caching with semantic search.

This service maintains a knowledge base of table schemas, statistics, and query patterns
to dramatically speed up SQL generation and improve query accuracy.
"""
import json
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from openai import OpenAI
from sqlalchemy import text, inspect
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


def _get_client() -> OpenAI:
    """Get OpenAI client."""
    return OpenAI(api_key=OPENAI_API_KEY)


def ensure_schema_tables(db: Session) -> None:
    """
    Create schema management tables if they don't exist.
    """
    try:
        # Roll back any failed transaction first
        db.rollback()
        
        # Table schemas cache
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_table_schemas (
                  id BIGSERIAL PRIMARY KEY,
                  table_name VARCHAR(100) NOT NULL UNIQUE,
                  schema_info JSONB NOT NULL,
                  description TEXT,
                  common_queries JSONB,
                  row_count BIGINT DEFAULT 0,
                  date_range JSONB,
                  last_updated TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                  embedding JSONB
                )
                """
            )
        )
        
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_table_schemas_name 
                ON ai_table_schemas(table_name)
                """
            )
        )
        
        # Query patterns library
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_query_patterns (
                  id BIGSERIAL PRIMARY KEY,
                  pattern_name VARCHAR(200) NOT NULL UNIQUE,
                  pattern_template TEXT NOT NULL,
                  sql_template TEXT NOT NULL,
                  example_queries TEXT[],
                  required_tables TEXT[],
                  usage_count INTEGER DEFAULT 0,
                  avg_execution_time_ms INTEGER,
                  embedding JSONB,
                  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                  last_used_at TIMESTAMPTZ
                )
                """
            )
        )
        
        db.commit()
        logger.info("✅ Schema management tables ensured")
    except Exception as e:
        logger.debug(f"Could not ensure schema tables (not critical): {e}")
        db.rollback()


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for text using OpenAI.
    
    Args:
        text: Text to embed
    
    Returns:
        Embedding vector (1536 dimensions)
    """
    try:
        client = _get_client()
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text[:8000],
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return []


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)


def introspect_table_schema(db: Session, table_name: str, sap_db: Optional[Session] = None) -> Optional[Dict[str, Any]]:
    """
    Introspect a table's schema from the database.
    
    Args:
        db: Main database session (for caching)
        table_name: Name of table to introspect
        sap_db: Optional SAP database session (if using separate SAP DB)
    
    Returns:
        Schema dictionary with columns, types, sample values
    """
    try:
        target_db = sap_db or db
        inspector = inspect(target_db.bind)
        
        if table_name not in inspector.get_table_names():
            logger.warning(f"Table {table_name} not found in database")
            return None
        
        columns = inspector.get_columns(table_name)
        
        # Get sample data
        try:
            sample_query = text(f'SELECT * FROM "{table_name}" LIMIT 5')
            sample_rows = target_db.execute(sample_query).fetchall()
            sample_data = [dict(row._mapping) for row in sample_rows] if sample_rows else []
        except Exception as sample_err:
            logger.warning(f"Failed to get sample data for {table_name}: {sample_err}")
            sample_data = []
        
        # Get row count
        try:
            count_query = text(f'SELECT COUNT(*) as cnt FROM "{table_name}"')
            row_count = target_db.execute(count_query).scalar() or 0
        except:
            row_count = 0
        
        schema_info = {
            "table_name": table_name,
            "columns": [
                {
                    "name": col["name"],
                    "type": str(col["type"]),
                    "nullable": col.get("nullable", True),
                }
                for col in columns
            ],
            "sample_data": sample_data[:3],  # Only keep 3 samples
            "row_count": row_count,
            "column_count": len(columns),
        }
        
        logger.info(f"📋 Introspected {table_name}: {len(columns)} columns, {row_count} rows")
        return schema_info
    
    except Exception as e:
        logger.error(f"❌ Failed to introspect table {table_name}: {e}")
        return None


def cache_table_schema(
    db: Session,
    table_name: str,
    schema_info: Dict[str, Any],
    description: str = "",
    sap_db: Optional[Session] = None
) -> bool:
    """
    Cache a table's schema in the database with embedding.
    
    Args:
        db: Database session
        table_name: Name of table
        schema_info: Schema dictionary from introspection
        description: Human-readable description of table purpose
        sap_db: Optional SAP database for getting date ranges
    
    Returns:
        True if successful
    """
    try:
        ensure_schema_tables(db)
        
        # Generate embedding for semantic search
        embed_text = f"{table_name}: {description}\n"
        embed_text += f"Columns: {', '.join([col['name'] for col in schema_info['columns']])}"
        
        embedding = generate_embedding(embed_text)
        
        # Get date range if table has date columns
        date_range = _detect_date_range(db, table_name, schema_info, sap_db)
        
        # Upsert schema
        db.execute(
            text(
                """
                INSERT INTO ai_table_schemas (
                    table_name, schema_info, description, row_count, 
                    date_range, last_updated, embedding
                )
                VALUES (
                    :table_name, :schema_info::jsonb, :description, :row_count,
                    :date_range::jsonb, :last_updated, :embedding::jsonb
                )
                ON CONFLICT (table_name) DO UPDATE SET
                    schema_info = EXCLUDED.schema_info,
                    description = EXCLUDED.description,
                    row_count = EXCLUDED.row_count,
                    date_range = EXCLUDED.date_range,
                    last_updated = EXCLUDED.last_updated,
                    embedding = EXCLUDED.embedding
                """
            ),
            {
                "table_name": table_name,
                "schema_info": json.dumps(schema_info),
                "description": description,
                "row_count": schema_info.get("row_count", 0),
                "date_range": json.dumps(date_range) if date_range else None,
                "last_updated": _now_utc(),
                "embedding": json.dumps(embedding) if embedding else None,
            },
        )
        db.commit()
        logger.info(f"✅ Cached schema for {table_name}")
        return True
    
    except Exception as e:
        logger.error(f"❌ Failed to cache schema for {table_name}: {e}")
        db.rollback()
        return False


def _detect_date_range(
    db: Session, 
    table_name: str, 
    schema_info: Dict[str, Any],
    sap_db: Optional[Session] = None
) -> Optional[Dict[str, str]]:
    """Detect date range for tables with date columns."""
    try:
        target_db = sap_db or db
        
        # Find date columns
        date_columns = [
            col["name"] for col in schema_info["columns"]
            if "date" in col["name"].lower() or "time" in col["name"].lower()
            or "DATE" in str(col["type"]) or "TIMESTAMP" in str(col["type"])
        ]
        
        if not date_columns:
            return None
        
        # Use first date column
        date_col = date_columns[0]
        
        query = text(f'''
            SELECT 
                MIN("{date_col}") as min_date,
                MAX("{date_col}") as max_date
            FROM "{table_name}"
            WHERE "{date_col}" IS NOT NULL
        ''')
        
        result = target_db.execute(query).fetchone()
        
        if result and result[0] and result[1]:
            return {
                "date_column": date_col,
                "min_date": str(result[0]),
                "max_date": str(result[1]),
            }
        
        return None
    
    except Exception as e:
        logger.warning(f"Failed to detect date range for {table_name}: {e}")
        return None


def get_cached_schema(db: Session, table_name: str) -> Optional[Dict[str, Any]]:
    """
    Get cached schema for a table.
    
    Args:
        db: Database session
        table_name: Table name
    
    Returns:
        Cached schema info or None
    """
    try:
        result = db.execute(
            text(
                """
                SELECT schema_info, description, row_count, date_range, last_updated
                FROM ai_table_schemas
                WHERE table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).fetchone()
        
        if not result:
            return None
        
        return {
            "table_name": table_name,
            "schema_info": json.loads(result[0]) if result[0] else {},
            "description": result[1],
            "row_count": result[2],
            "date_range": json.loads(result[3]) if result[3] else None,
            "last_updated": result[4],
        }
    
    except Exception as e:
        logger.error(f"Failed to get cached schema for {table_name}: {e}")
        return None


def find_relevant_tables(db: Session, user_query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Find most relevant tables for a query using semantic search.
    
    Args:
        db: Database session
        user_query: User's natural language query
        top_k: Number of tables to return
    
    Returns:
        List of table info dictionaries sorted by relevance
    """
    try:
        # Generate query embedding
        query_embedding = generate_embedding(user_query)
        if not query_embedding:
            logger.warning("Failed to generate query embedding")
            return []
        
        # Get all cached schemas with embeddings
        result = db.execute(
            text(
                """
                SELECT table_name, schema_info, description, row_count, 
                       date_range, embedding
                FROM ai_table_schemas
                WHERE embedding IS NOT NULL
                """
            )
        ).fetchall()
        
        if not result:
            logger.warning("No cached schemas found")
            return []
        
        # Calculate similarities
        scored_tables = []
        for row in result:
            table_embedding = json.loads(row[5]) if row[5] else []
            if not table_embedding:
                continue
            
            similarity = cosine_similarity(query_embedding, table_embedding)
            
            scored_tables.append({
                "table_name": row[0],
                "schema_info": json.loads(row[1]) if row[1] else {},
                "description": row[2],
                "row_count": row[3],
                "date_range": json.loads(row[4]) if row[4] else None,
                "similarity": similarity,
            })
        
        # Sort by similarity
        scored_tables.sort(key=lambda x: x["similarity"], reverse=True)
        
        logger.info(f"📊 Found {len(scored_tables)} relevant tables for query")
        return scored_tables[:top_k]
    
    except Exception as e:
        logger.error(f"❌ Failed to find relevant tables: {e}")
        return []


def get_all_cached_schemas(db: Session) -> List[Dict[str, Any]]:
    """Get all cached table schemas."""
    try:
        # Check if table exists first
        result = db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ai_table_schemas'
                )
                """
            )
        ).scalar()
        
        if not result:
            logger.debug("ai_table_schemas table does not exist yet (not critical)")
            return []
        
        result = db.execute(
            text(
                """
                SELECT table_name, schema_info, description, row_count, date_range
                FROM ai_table_schemas
                ORDER BY row_count DESC
                """
            )
        ).fetchall()
        
        return [
            {
                "table_name": row[0],
                "schema_info": json.loads(row[1]) if row[1] else {},
                "description": row[2],
                "row_count": row[3],
                "date_range": json.loads(row[4]) if row[4] else None,
            }
            for row in result
        ]
    
    except Exception as e:
        logger.debug(f"Schema cache not available: {e}")
        return []


def update_table_statistics(db: Session, table_name: str, sap_db: Optional[Session] = None) -> bool:
    """
    Update statistics (row count, date ranges) for a cached table.
    
    Args:
        db: Main database session
        table_name: Table to update
        sap_db: Optional SAP database session
    
    Returns:
        True if successful
    """
    try:
        target_db = sap_db or db
        
        # Get row count
        count_result = target_db.execute(
            text(f'SELECT COUNT(*) as cnt FROM "{table_name}"')
        ).scalar()
        
        row_count = count_result or 0
        
        # Get cached schema to find date columns
        cached = get_cached_schema(db, table_name)
        if not cached:
            logger.warning(f"No cached schema for {table_name}")
            return False
        
        schema_info = cached["schema_info"]
        date_range = _detect_date_range(db, table_name, schema_info, sap_db)
        
        # Update cache
        db.execute(
            text(
                """
                UPDATE ai_table_schemas
                SET row_count = :row_count,
                    date_range = :date_range::jsonb,
                    last_updated = :last_updated
                WHERE table_name = :table_name
                """
            ),
            {
                "table_name": table_name,
                "row_count": row_count,
                "date_range": json.dumps(date_range) if date_range else None,
                "last_updated": _now_utc(),
            },
        )
        db.commit()
        
        logger.info(f"✅ Updated statistics for {table_name}: {row_count} rows")
        return True
    
    except Exception as e:
        logger.error(f"❌ Failed to update statistics for {table_name}: {e}")
        db.rollback()
        return False


def cache_query_pattern(
    db: Session,
    pattern_name: str,
    pattern_template: str,
    sql_template: str,
    example_queries: List[str],
    required_tables: List[str],
) -> bool:
    """
    Cache a query pattern for fast matching.
    
    Args:
        db: Database session
        pattern_name: Unique name for pattern
        pattern_template: Template like "sales by {dimension} for {period}"
        sql_template: SQL template with placeholders
        example_queries: Example queries that match this pattern
        required_tables: Tables needed for this query
    
    Returns:
        True if successful
    """
    try:
        ensure_schema_tables(db)
        
        # Generate embedding from pattern + examples
        embed_text = f"{pattern_name}: {pattern_template}\n"
        embed_text += "\n".join(example_queries[:5])
        
        embedding = generate_embedding(embed_text)
        
        db.execute(
            text(
                """
                INSERT INTO ai_query_patterns (
                    pattern_name, pattern_template, sql_template,
                    example_queries, required_tables, embedding, created_at
                )
                VALUES (
                    :pattern_name, :pattern_template, :sql_template,
                    :example_queries, :required_tables, :embedding::jsonb, :created_at
                )
                ON CONFLICT (pattern_name) DO UPDATE SET
                    pattern_template = EXCLUDED.pattern_template,
                    sql_template = EXCLUDED.sql_template,
                    example_queries = EXCLUDED.example_queries,
                    required_tables = EXCLUDED.required_tables,
                    embedding = EXCLUDED.embedding
                """
            ),
            {
                "pattern_name": pattern_name,
                "pattern_template": pattern_template,
                "sql_template": sql_template,
                "example_queries": example_queries,
                "required_tables": required_tables,
                "embedding": json.dumps(embedding) if embedding else None,
                "created_at": _now_utc(),
            },
        )
        db.commit()
        
        logger.info(f"✅ Cached query pattern: {pattern_name}")
        return True
    
    except Exception as e:
        logger.error(f"❌ Failed to cache query pattern {pattern_name}: {e}")
        db.rollback()
        return False


def find_matching_pattern(db: Session, user_query: str, threshold: float = 0.80) -> Optional[Dict[str, Any]]:
    """
    Find matching query pattern using semantic similarity.
    
    Args:
        db: Database session
        user_query: User's natural language query
        threshold: Minimum similarity threshold (0-1)
    
    Returns:
        Matching pattern info or None
    """
    try:
        # Check if table exists first
        table_exists = db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ai_query_patterns'
                )
                """
            )
        ).scalar()
        
        if not table_exists:
            logger.debug("ai_query_patterns table does not exist yet (not critical)")
            return None
        
        query_embedding = generate_embedding(user_query)
        if not query_embedding:
            return None
        
        # Get all patterns
        result = db.execute(
            text(
                """
                SELECT pattern_name, pattern_template, sql_template,
                       example_queries, required_tables, usage_count,
                       avg_execution_time_ms, embedding
                FROM ai_query_patterns
                WHERE embedding IS NOT NULL
                """
            )
        ).fetchall()
        
        if not result:
            return None
        
        best_match = None
        best_similarity = 0.0
        
        for row in result:
            pattern_embedding = json.loads(row[7]) if row[7] else []
            if not pattern_embedding:
                continue
            
            similarity = cosine_similarity(query_embedding, pattern_embedding)
            
            if similarity > best_similarity and similarity >= threshold:
                best_similarity = similarity
                best_match = {
                    "pattern_name": row[0],
                    "pattern_template": row[1],
                    "sql_template": row[2],
                    "example_queries": row[3],
                    "required_tables": row[4],
                    "usage_count": row[5],
                    "avg_execution_time_ms": row[6],
                    "similarity": similarity,
                }
        
        if best_match:
            logger.info(f"✅ Found matching pattern: {best_match['pattern_name']} (similarity: {best_similarity:.3f})")
            
            # Increment usage count
            try:
                db.execute(
                    text(
                        """
                        UPDATE ai_query_patterns
                        SET usage_count = usage_count + 1,
                            last_used_at = :last_used
                        WHERE pattern_name = :pattern_name
                        """
                    ),
                    {"pattern_name": best_match["pattern_name"], "last_used": _now_utc()},
                )
                db.commit()
            except:
                pass
        
        return best_match
    
    except Exception as e:
        logger.error(f"Failed to find matching pattern: {e}")
        return None


# Missing import
import math
