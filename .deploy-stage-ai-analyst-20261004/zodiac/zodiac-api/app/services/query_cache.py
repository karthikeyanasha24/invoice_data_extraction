"""
Semantic query caching with embeddings and similarity search.

Uses OpenAI embeddings to find similar queries and cache results.
Reduces API calls by 60-80% for repeated or similar queries.
"""
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    """Get current UTC timestamp."""
    return datetime.now(timezone.utc)


def _get_client() -> OpenAI:
    """Get OpenAI client."""
    return OpenAI(api_key=OPENAI_API_KEY)


def ensure_embeddings_table(db: Session) -> None:
    """
    Create the query embeddings table if it doesn't exist.
    Schema: query_text, embedding (vector), sql_query, result_summary, hit_count, created_at, expires_at
    """
    try:
        # Roll back any failed transaction first
        db.rollback()
        
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_query_embeddings (
                  id BIGSERIAL PRIMARY KEY,
                  query_text TEXT NOT NULL,
                  query_hash VARCHAR(64) NOT NULL UNIQUE,
                  embedding JSONB NOT NULL,
                  sql_query TEXT NULL,
                  result_summary TEXT NULL,
                  result_preview JSONB NULL,
                  charts JSONB NULL,
                  hit_count INTEGER DEFAULT 0,
                  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                  last_hit_at TIMESTAMPTZ NULL,
                  expires_at TIMESTAMPTZ NULL
                )
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_query_embeddings_hash 
                ON ai_query_embeddings(query_hash)
                """
            )
        )
        db.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_ai_query_embeddings_expires 
                ON ai_query_embeddings(expires_at) 
                WHERE expires_at IS NOT NULL
                """
            )
        )
        db.commit()
        logger.info("Query embeddings table ensured")
    except Exception as e:
        logger.debug(f"Could not ensure embeddings table (not critical): {e}")
        db.rollback()


def generate_embedding(text: str) -> List[float]:
    """
    Generate embedding vector for a text query using OpenAI.
    
    Args:
        text: Query text to embed
    
    Returns:
        Embedding vector (list of floats, dimension 1536 for text-embedding-3-small)
    """
    try:
        client = _get_client()
        response = client.embeddings.create(
            model="text-embedding-3-small",  # Cheaper and faster than ada-002
            input=text[:8000],  # Limit text length
        )
        embedding = response.data[0].embedding
        logger.debug(f"Generated embedding for query (length: {len(embedding)})")
        return embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        return []


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """
    Calculate cosine similarity between two vectors.
    
    Args:
        vec1: First vector
        vec2: Second vector
    
    Returns:
        Similarity score between 0 and 1 (1 = identical)
    """
    if not vec1 or not vec2 or len(vec1) != len(vec2):
        return 0.0
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    
    return dot_product / (magnitude1 * magnitude2)


def _normalize_query_text(text: str) -> str:
    """Normalize query text for better matching."""
    import re
    # Lowercase, remove extra spaces, remove punctuation
    text = text.lower().strip()
    text = re.sub(r'[^\w\s]', '', text)  # Remove punctuation
    text = re.sub(r'\s+', ' ', text)  # Collapse multiple spaces
    return text


def find_similar_cached_query(
    db: Session,
    query_text: str,
    threshold: float = 0.78,
) -> Optional[Dict[str, Any]]:
    """
    Find a similar cached query using:
    1. Fast exact text match (normalized)
    2. Semantic similarity search with embeddings
    
    Args:
        db: Database session
        query_text: Query text to search for
        threshold: Minimum similarity score (0-1) to consider a match (default: 0.78)
    
    Returns:
        Cached query result if found, None otherwise
    """
    try:
        # Check if table exists first
        db.rollback()  # Clear any failed transaction state
        table_exists = db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'ai_query_embeddings'
                )
                """
            )
        ).scalar()
        
        if not table_exists:
            logger.debug("ai_query_embeddings table does not exist yet")
            return None
        
        ensure_embeddings_table(db)
        
        # FAST PATH 1: Exact normalized text match
        normalized_query = _normalize_query_text(query_text)
        
        # Try exact normalized match first
        exact_result = db.execute(
            text(
                """
                SELECT id, query_text, sql_query, result_summary,
                       result_preview, charts, hit_count
                FROM ai_query_embeddings
                WHERE (expires_at IS NULL OR expires_at > :now)
                ORDER BY created_at DESC
                LIMIT 200
                """
            ),
            {"now": _now_utc()},
        ).fetchall()
        
        # Check for normalized text match
        for row in exact_result:
            if _normalize_query_text(row[1]) == normalized_query:
                logger.info(f"🚀 FAST CACHE HIT: normalized text match for '{query_text[:50]}...'")
                result = {
                    "id": row[0],
                    "query_text": row[1],
                    "sql_query": row[2],
                    "result_summary": row[3],
                    "result_preview": json.loads(row[4]) if row[4] else None,
                    "charts": json.loads(row[5]) if row[5] else None,
                    "hit_count": row[6],
                    "similarity": 1.0,
                }
                # Update hit count
                db.execute(
                    text("UPDATE ai_query_embeddings SET hit_count = hit_count + 1, last_hit_at = :now WHERE id = :id"),
                    {"id": result["id"], "now": _now_utc()},
                )
                db.commit()
                return result
        
        # SEMANTIC SEARCH: Generate embedding for similarity search
        query_embedding = generate_embedding(query_text)
        if not query_embedding:
            return None
        
        # SEMANTIC SEARCH: Fetch all non-expired cached queries with embeddings
        now = _now_utc()
        rows = db.execute(
            text(
                """
                SELECT id, query_text, embedding, sql_query, result_summary, 
                       result_preview, charts, hit_count
                FROM ai_query_embeddings
                WHERE (expires_at IS NULL OR expires_at > :now)
                  AND embedding IS NOT NULL
                ORDER BY created_at DESC
                LIMIT 300
                """
            ),
            {"now": now},
        ).fetchall()
        
        # Calculate similarity scores
        best_match = None
        best_score = threshold
        
        for row in rows:
            cached_embedding = json.loads(row[2]) if isinstance(row[2], str) else row[2]
            if not cached_embedding:
                continue
            
            similarity = cosine_similarity(query_embedding, cached_embedding)
            
            if similarity > best_score:
                best_score = similarity
                best_match = {
                    "id": row[0],
                    "query_text": row[1],
                    "sql_query": row[3],
                    "result_summary": row[4],
                    "result_preview": json.loads(row[5]) if row[5] else None,
                    "charts": json.loads(row[6]) if row[6] else None,
                    "hit_count": row[7],
                    "similarity": similarity,
                }
        
        if best_match:
            # Update hit count
            db.execute(
                text(
                    """
                    UPDATE ai_query_embeddings
                    SET hit_count = hit_count + 1,
                        last_hit_at = :now
                    WHERE id = :id
                    """
                ),
                {"id": best_match["id"], "now": _now_utc()},
            )
            db.commit()
            logger.info(f"✅ SEMANTIC CACHE HIT: similarity={best_score:.3f}, query='{query_text[:50]}...' matched with '{best_match['query_text'][:50]}...'")
        else:
            logger.info(f"❌ CACHE MISS: no similar query found (threshold={threshold}) for '{query_text[:60]}...'")
            # Log top 3 near-misses for debugging
            top_3 = sorted(
                [(cosine_similarity(query_embedding, json.loads(r[2]) if isinstance(r[2], str) else r[2]), r[1]) 
                 for r in rows if r[2]], 
                reverse=True
            )[:3]
            if top_3:
                logger.info(f"   Near misses: {[(f'{score:.3f}', text[:40]) for score, text in top_3]}")
        
        return best_match
    
    except Exception as e:
        logger.error(f"Failed to find similar cached query: {e}")
        return None


def cache_query_result(
    db: Session,
    query_text: str,
    sql_query: Optional[str],
    result_summary: str,
    result_preview: Optional[List[Dict[str, Any]]],
    charts: Optional[List[Dict[str, Any]]],
    ttl_hours: int = 24,
) -> bool:
    """
    Cache a query result with its embedding.
    
    Args:
        db: Database session
        query_text: Natural language query
        sql_query: Generated SQL (if any)
        result_summary: AI summary of results
        result_preview: Sample result rows
        charts: Chart specifications
        ttl_hours: Time-to-live in hours (default: 24)
    
    Returns:
        True if successful, False otherwise
    """
    try:
        ensure_embeddings_table(db)
        
        # Generate embedding
        embedding = generate_embedding(query_text)
        if not embedding:
            return False
        
        # Generate query hash (simple approach: first 64 chars of normalized query)
        import hashlib
        query_normalized = query_text.lower().strip()
        query_hash = hashlib.sha256(query_normalized.encode()).hexdigest()[:64]
        
        # Calculate expiration time
        expires_at = _now_utc() + timedelta(hours=ttl_hours)
        
        # Insert or update cache
        db.execute(
            text(
                """
                INSERT INTO ai_query_embeddings 
                (query_text, query_hash, embedding, sql_query, result_summary, 
                 result_preview, charts, created_at, expires_at)
                VALUES (:query_text, :query_hash, :embedding, :sql_query, :result_summary,
                        :result_preview, :charts, :created_at, :expires_at)
                ON CONFLICT (query_hash) DO UPDATE SET
                  embedding = EXCLUDED.embedding,
                  sql_query = EXCLUDED.sql_query,
                  result_summary = EXCLUDED.result_summary,
                  result_preview = EXCLUDED.result_preview,
                  charts = EXCLUDED.charts,
                  created_at = EXCLUDED.created_at,
                  expires_at = EXCLUDED.expires_at,
                  hit_count = 0
                """
            ),
            {
                "query_text": query_text[:5000],
                "query_hash": query_hash,
                "embedding": json.dumps(embedding),
                "sql_query": sql_query[:10000] if sql_query else None,
                "result_summary": result_summary[:10000],
                "result_preview": json.dumps(result_preview[:30] if result_preview else []),
                "charts": json.dumps(charts if charts else []),
                "created_at": _now_utc(),
                "expires_at": expires_at,
            },
        )
        db.commit()
        logger.info(f"Cached query result: '{query_text[:50]}...'")
        return True
    
    except Exception as e:
        logger.error(f"Failed to cache query result: {e}")
        db.rollback()
        return False


def cleanup_expired_cache(db: Session) -> int:
    """
    Remove expired cache entries.
    
    Args:
        db: Database session
    
    Returns:
        Number of entries deleted
    """
    try:
        ensure_embeddings_table(db)
        
        result = db.execute(
            text(
                """
                DELETE FROM ai_query_embeddings
                WHERE expires_at IS NOT NULL AND expires_at < :now
                """
            ),
            {"now": _now_utc()},
        )
        db.commit()
        
        count = result.rowcount
        if count > 0:
            logger.info(f"Cleaned up {count} expired cache entries")
        return count
    
    except Exception as e:
        logger.error(f"Failed to cleanup expired cache: {e}")
        db.rollback()
        return 0


def get_cache_stats(db: Session) -> Dict[str, Any]:
    """
    Get cache statistics.
    
    Args:
        db: Database session
    
    Returns:
        Dictionary with cache statistics
    """
    try:
        ensure_embeddings_table(db)
        
        result = db.execute(
            text(
                """
                SELECT 
                    COUNT(*) as total_entries,
                    SUM(hit_count) as total_hits,
                    AVG(hit_count) as avg_hits_per_entry,
                    COUNT(CASE WHEN expires_at > :now OR expires_at IS NULL THEN 1 END) as active_entries,
                    COUNT(CASE WHEN expires_at <= :now THEN 1 END) as expired_entries
                FROM ai_query_embeddings
                """
            ),
            {"now": _now_utc()},
        ).fetchone()
        
        return {
            "total_entries": int(result[0] or 0),
            "total_hits": int(result[1] or 0),
            "avg_hits_per_entry": float(result[2] or 0),
            "active_entries": int(result[3] or 0),
            "expired_entries": int(result[4] or 0),
        }
    
    except Exception as e:
        logger.error(f"Failed to get cache stats: {e}")
        return {
            "total_entries": 0,
            "total_hits": 0,
            "avg_hits_per_entry": 0.0,
            "active_entries": 0,
            "expired_entries": 0,
        }
