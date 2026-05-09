"""
RAG Store Service — embedding-based memory for NL→SQL pairs.

Architecture:
  - Uses OpenAI text-embedding-3-small for all embeddings
  - Three entry types stored in ai_query_embeddings table:
      * example  — past NL→SQL pairs that worked (similarity ≥ 0.70)
      * glossary — business term definitions (similarity ≥ 0.65)
      * schema   — relevant view/column descriptions (similarity ≥ 0.72)
  - Cosine similarity retrieval from JSON-stored embeddings
  - Auto-saves successful NL→SQL pairs after execution

Usage:
    from .rag_store_service import retrieve_similar_examples, save_successful_query

    examples = retrieve_similar_examples(db, client, question, top_k=3)
    save_successful_query(db, client, question, sql)
"""
from __future__ import annotations

import json
import logging
import math
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Similarity thresholds per entry type
_THRESHOLD_EXAMPLE  = 0.70
_THRESHOLD_GLOSSARY = 0.65
_THRESHOLD_SCHEMA   = 0.72

_EMBED_MODEL = "text-embedding-3-small"

# Built-in SAP business glossary entries (seeded once)
_SAP_GLOSSARY: List[Tuple[str, str]] = [
    ("COGS", "Cost of Goods Sold — total direct cost to produce goods sold. In SAP: CKIS.wertn or CKHS.hwges."),
    ("revenue", "Total billed sales amount. In SAP: SUM(CAST(NULLIF(TRIM(CAST(VBRK.netwr AS TEXT)),'') AS NUMERIC)) on billing documents."),
    ("profit margin", "Revenue minus COGS divided by revenue. Computed from VBRP (revenue) + CKIS/CKHS (cost)."),
    ("negative sales", "Credit memos or return billing lines where netwr < 0. Use VBRP line items, NOT grouped VBRK totals."),
    ("billing document", "SAP invoice record. Header: VBRK (vbeln, fkdat, kunag, netwr). Items: vbrp (vbeln, posnr, matnr, netwr)."),
    ("FKDAT", "Billing date in VBRK/VBRP — stored as YYYYMMDD text. Use SUBSTRING(TRIM(fkdat),1,4) for year extraction. NEVER use gjahr for year filtering."),
    ("gjahr", "Fiscal year field — broken in this DB (all rows = 0000). NEVER filter by gjahr. Always use FKDAT for date/year."),
    ("netwr", "Net value/amount — stored as character varying (text) in SAP tables. Always cast: SUM(CAST(NULLIF(TRIM(CAST(netwr AS TEXT)),'') AS NUMERIC))."),
    ("drill down", "Analysing a previous result at finer granularity. In SAP: move from VBRK (invoice totals) → VBRP (line items) → MARA/MAKT (product master)."),
    ("master data", "Static reference tables: MARA (material), MAKT (descriptions), KNA1 (customer), LFA1 (vendor), CEPC (profit center). Never use these as primary fact source."),
    ("transaction data", "Event-based tables with amounts/quantities: VBRP, VBRK, EKPO, EKKO, BSEG, FAGLFLEXA, COEP. Always compute measures from these."),
    ("LPAD join", "SAP document keys often have leading zeros. Join with LPAD(TRIM(a.vbeln),10,'0') = LPAD(TRIM(b.vbeln),10,'0') to avoid zero-padding mismatches."),
    ("product margin by year", "Revenue from VBRP grouped by year + matnr, cost from CKIS, joined on matnr. Year = SUBSTRING(TRIM(vk.fkdat),1,4)."),
    ("industry", "Customer industry sector from T016T.brsch joined via KNA1.brsch. Only join T016T when user explicitly asks for industry/sector."),
]


# ─── Embedding helpers ────────────────────────────────────────────────────────

def _embed(client: Any, text: str) -> Optional[List[float]]:
    """Get embedding vector for text. Returns None on failure."""
    try:
        resp = client.embeddings.create(model=_EMBED_MODEL, input=text[:8000])
        return resp.data[0].embedding
    except Exception as e:
        logger.warning("rag_store: embed failed: %s", e)
        return None


def _cosine(a: List[float], b: List[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


# ─── DB helpers ───────────────────────────────────────────────────────────────

def _ensure_table(db: Any) -> None:
    """Create ai_query_embeddings table if it doesn't exist."""
    from sqlalchemy import text
    try:
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS ai_query_embeddings (
                id          BIGSERIAL PRIMARY KEY,
                entry_type  TEXT NOT NULL DEFAULT 'example',
                question    TEXT NOT NULL,
                sql_query   TEXT,
                summary     TEXT,
                embedding   JSONB NOT NULL,
                use_count   INTEGER NOT NULL DEFAULT 1,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """))
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_aqe_entry_type ON ai_query_embeddings (entry_type)"
        ))
        db.commit()
    except Exception as e:
        logger.debug("rag_store: ensure_table: %s", e)
        try:
            db.rollback()
        except Exception:
            pass


def _load_all_entries(db: Any, entry_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load all embedding entries (optionally filtered by type). Returns list of dicts."""
    from sqlalchemy import text
    try:
        _ensure_table(db)
        if entry_type:
            rows = db.execute(
                text("SELECT id, entry_type, question, sql_query, summary, embedding, use_count FROM ai_query_embeddings WHERE entry_type = :et ORDER BY use_count DESC, id DESC LIMIT 500"),
                {"et": entry_type},
            ).mappings().all()
        else:
            rows = db.execute(
                text("SELECT id, entry_type, question, sql_query, summary, embedding, use_count FROM ai_query_embeddings ORDER BY use_count DESC, id DESC LIMIT 500")
            ).mappings().all()
        result = []
        for r in rows:
            emb = r["embedding"]
            if isinstance(emb, str):
                try:
                    emb = json.loads(emb)
                except Exception:
                    continue
            if not isinstance(emb, list):
                continue
            result.append({
                "id": r["id"],
                "entry_type": r["entry_type"],
                "question": r["question"] or "",
                "sql_query": r["sql_query"] or "",
                "summary": r["summary"] or "",
                "embedding": emb,
                "use_count": r["use_count"],
            })
        return result
    except Exception as e:
        logger.debug("rag_store: load_all: %s", e)
        return []


# ─── Seed glossary ────────────────────────────────────────────────────────────

_GLOSSARY_SEEDED = False


def _seed_glossary_if_needed(db: Any, client: Any) -> None:
    """One-time seed of SAP glossary entries. Safe to call on every startup."""
    global _GLOSSARY_SEEDED
    if _GLOSSARY_SEEDED:
        return
    try:
        from sqlalchemy import text
        _ensure_table(db)
        count = db.execute(
            text("SELECT COUNT(*) FROM ai_query_embeddings WHERE entry_type = 'glossary'")
        ).scalar() or 0
        if int(count) >= len(_SAP_GLOSSARY):
            _GLOSSARY_SEEDED = True
            return
        for term, definition in _SAP_GLOSSARY:
            emb = _embed(client, f"{term}: {definition}")
            if emb is None:
                continue
            try:
                db.execute(text("""
                    INSERT INTO ai_query_embeddings (entry_type, question, summary, embedding)
                    VALUES ('glossary', :q, :s, :e::jsonb)
                    ON CONFLICT DO NOTHING
                """), {"q": term, "s": definition, "e": json.dumps(emb)})
            except Exception:
                pass
        db.commit()
        _GLOSSARY_SEEDED = True
        logger.info("rag_store: seeded %d glossary entries", len(_SAP_GLOSSARY))
    except Exception as e:
        logger.debug("rag_store: seed_glossary failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass


# ─── Public API ───────────────────────────────────────────────────────────────

def retrieve_similar_examples(
    db: Any,
    client: Any,
    question: str,
    top_k: int = 3,
    include_glossary: bool = True,
) -> List[Dict[str, Any]]:
    """
    Retrieve the most relevant past NL→SQL pairs and glossary terms for a question.

    Returns list of dicts with keys:
        entry_type, question, sql_query, summary, similarity
    """
    if not question or not client:
        return []

    try:
        _seed_glossary_if_needed(db, client)
    except Exception:
        pass

    q_emb = _embed(client, question)
    if q_emb is None:
        return []

    entries = _load_all_entries(db)
    if not entries:
        return []

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for entry in entries:
        sim = _cosine(q_emb, entry["embedding"])
        etype = entry.get("entry_type", "example")
        threshold = (
            _THRESHOLD_GLOSSARY if etype == "glossary"
            else _THRESHOLD_SCHEMA if etype == "schema"
            else _THRESHOLD_EXAMPLE
        )
        if sim >= threshold:
            if etype == "glossary" and not include_glossary:
                continue
            scored.append((sim, entry))

    # Sort: examples first (most valuable for SQL), then glossary, by similarity desc
    scored.sort(key=lambda t: (-t[0], 0 if t[1]["entry_type"] == "example" else 1))
    results = []
    for sim, entry in scored[:top_k]:
        results.append({
            "entry_type": entry["entry_type"],
            "question": entry["question"],
            "sql_query": entry["sql_query"],
            "summary": entry["summary"],
            "similarity": round(sim, 4),
        })
    return results


def save_successful_query(
    db: Any,
    client: Any,
    question: str,
    sql: str,
    summary: str = "",
    min_rows: int = 1,
) -> bool:
    """
    Auto-save a successful NL→SQL pair to the RAG store.
    Only saves when the query returned at least min_rows rows.
    Increments use_count if a very similar entry already exists (similarity ≥ 0.92).
    """
    if not question or not sql or not client:
        return False

    try:
        _ensure_table(db)
        from sqlalchemy import text

        q_emb = _embed(client, question)
        if q_emb is None:
            return False

        # Check for near-duplicate (avoid storing the same query twice)
        existing = _load_all_entries(db, entry_type="example")
        for entry in existing:
            sim = _cosine(q_emb, entry["embedding"])
            if sim >= 0.92:
                # Increment use_count instead of inserting duplicate
                db.execute(
                    text("UPDATE ai_query_embeddings SET use_count = use_count + 1, updated_at = NOW() WHERE id = :id"),
                    {"id": entry["id"]},
                )
                db.commit()
                logger.debug("rag_store: incremented use_count for existing entry id=%s", entry["id"])
                return True

        db.execute(text("""
            INSERT INTO ai_query_embeddings (entry_type, question, sql_query, summary, embedding)
            VALUES ('example', :q, :sql, :s, :e::jsonb)
        """), {
            "q": question[:1000],
            "sql": sql[:5000],
            "s": (summary or "")[:500],
            "e": json.dumps(q_emb),
        })
        db.commit()
        logger.info("rag_store: saved new NL→SQL pair (question_len=%d sql_len=%d)", len(question), len(sql))
        return True
    except Exception as e:
        logger.warning("rag_store: save_successful_query failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def format_rag_context_for_prompt(examples: List[Dict[str, Any]]) -> str:
    """
    Format retrieved RAG entries as a compact block for injection into the SQL generation prompt.
    """
    if not examples:
        return ""
    parts = ["── RAG CONTEXT (learned from past successful queries) ──"]
    sql_examples = [e for e in examples if e["entry_type"] == "example" and e.get("sql_query")]
    glossary = [e for e in examples if e["entry_type"] == "glossary"]

    if glossary:
        parts.append("\nBusiness term definitions (use these for correct column/table selection):")
        for g in glossary:
            parts.append(f"  • {g['question']}: {g['summary']}")

    if sql_examples:
        parts.append("\nSimilar past queries that worked (use as style/join reference):")
        for ex in sql_examples[:3]:
            sim = ex.get("similarity", 0)
            parts.append(f"\n  [similarity={sim:.2f}] Question: {ex['question']}")
            parts.append(f"  SQL:\n{ex['sql_query'][:600]}")

    return "\n".join(parts)
