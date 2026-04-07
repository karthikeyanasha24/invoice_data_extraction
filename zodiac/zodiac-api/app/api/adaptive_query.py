"""
Reference-compatible Adaptive Query API.

Implements an endpoint that mirrors the Node reference project:
  POST /api/query/adaptive
Body:
  {
    "question": "...",
    "tableHint": "dbo.VwAISalesData" | null,
    "contextData": {
      "previousQuestion": "...",
      "previousSQL": "...",
      "data": [ { ...row... }, ... ]
    } | null
  }

Responses:
  - New query: { sql, rowCount, data, summary, retried?, originalSql?, charts? }
  - Follow-up analysis (no new SQL): { type: "analysis", answer }
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config.config import OPENAI_API_KEY, USE_SAP_DB_FOR_AI
from ..database import get_sap_session

router = APIRouter(tags=["adaptive-query"])


def _get_openai_key() -> str:
    # Project convention uses OPEN_AI_KEY (see app.config.config.OPENAI_API_KEY),
    # but some deployments use OPENAI_API_KEY. Accept both.
    k = (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or OPENAI_API_KEY or "").strip()
    if not k:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set OPEN_AI_KEY (or OPENAI_API_KEY) on the server",
        )
    return k


def _looks_like_query_revision_request(followup_question: str) -> bool:
    q = (followup_question or "").lower()
    if not q.strip():
        return False
    # General "please fix/adjust SQL" intent
    keywords = (
        "generate sql",
        "write sql",
        "fix the sql",
        "fix sql",
        "improve the sql",
        "improve sql",
        "revise the sql",
        "revise sql",
        "change the sql",
        "modify the sql",
        "schema-valid",
        "schema valid",
        "no rows",
        "0 rows",
        "empty set",
        "returned no rows",
    )
    if any(k in q for k in keywords):
        return True
    # Common phrasing: "why can't/cant you generate ... sql"
    if re.search(r"why\s+can[’']?t\s+you\s+generate", q) and "sql" in q:
        return True
    # Another common phrasing: "don't stick to the words" (asking for semantic SQL)
    if ("stick to the words" in q or "stick to words" in q) and "sql" in q:
        return True
    return False


def _looks_like_rowcount_question(question: str) -> bool:
    q = (question or "").lower()
    if not q.strip():
        return False
    return any(
        k in q
        for k in (
            "how many rows",
            "row count",
            "rows exist",
            "count rows",
            "number of rows",
            "how many records",
            "record count",
        )
    )


def _extract_known_tables_from_question(question: str) -> List[str]:
    """
    Extract table tokens mentioned in the question, but only keep those that exist
    in the CSV-backed schema catalog.
    """
    q = (question or "").strip()
    if not q:
        return []
    try:
        from ..services.schema_context_builder import load_schema

        schema = load_schema()
        if not schema:
            return []
        all_tables = list(schema.keys())
        table_set_lower = {t.lower(): t for t in all_tables}

        # Capture quoted and bare identifiers like KNA1, "KNA1", public.KNA1
        tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{1,}\b", q))
        out: List[str] = []
        for tok in tokens:
            t = table_set_lower.get(tok.lower())
            if t and t not in out:
                out.append(t)

        # schema-qualified mentions
        for _, tbl in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b", q):
            t = table_set_lower.get(tbl.lower())
            if t and t not in out:
                out.append(t)

        return out
    except Exception:
        return []


@router.get("/api/query/health")
async def adaptive_query_health() -> Dict[str, Any]:
    return {"status": "ok"}


@router.get("/api/query/adaptive")
async def get_query_adaptive() -> Dict[str, Any]:
    """
    The reference project only exposes POST for /api/query/adaptive.
    This exists to make debugging easier (quick 200/405 checks in browsers/tools).
    """
    return {"error": "method_not_allowed", "message": "Use POST /api/query/adaptive"}


@router.post("/api/query/adaptive")
async def post_query_adaptive(
    question: str = Body(..., embed=True),
    tableHint: Optional[str] = Body(default=None, embed=True),
    contextData: Optional[Dict[str, Any]] = Body(default=None, embed=True),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Reference-compatible adaptive query:
    - If contextData provided: answer from provided rows (no new SQL).
    - Else: run the existing Zodiac AI orchestrator to generate SQL + execute + return rows.
    """
    q = (question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail='Send JSON: { "question": "..." }')
    if len(q) > 4000:
        raise HTTPException(status_code=400, detail="question_too_long (max 4000)")

    api_key = _get_openai_key()

    # ── Follow-up analysis: no new SQL ────────────────────────────────────────
    if contextData and isinstance(contextData, dict):
        prev_q = str(contextData.get("previousQuestion") or "").strip()
        prev_sql = str(contextData.get("previousSQL") or "").strip()
        rows = contextData.get("data")
        rows_list: List[Dict[str, Any]] = rows if isinstance(rows, list) else []

        try:
            from openai import OpenAI
            from ..services.schema_context_builder import build_schema_context

            client = OpenAI(api_key=api_key)

            # If the previous query returned no rows, or the follow-up is asking to "fix/generate" SQL,
            # we return an analysis that includes a *suggested* revised SQL (but we do not execute it).
            wants_revision = _looks_like_query_revision_request(q)
            is_empty = len(rows_list) == 0

            # Deterministic "empty result" helper: when the prior query returned 0 rows,
            # users often ask follow-ups like "why can't you generate SQL" — in that case,
            # the fastest, most reliable help is a diagnostic SQL to verify the tables contain data.
            if is_empty:
                prev_blob = f"{prev_q}\n{prev_sql}".upper()
                mentions_kna1 = "KNA1" in prev_blob
                mentions_knvv = "KNVV" in prev_blob
                if mentions_kna1 or mentions_knvv:
                    diag_sql_parts = []
                    # Avoid :: casts because some execution paths use SQLAlchemy text().
                    if mentions_kna1:
                        diag_sql_parts.append("SELECT 'KNA1' AS table_name, CAST(COUNT(*) AS bigint) AS row_count FROM \"KNA1\"")
                    if mentions_knvv:
                        diag_sql_parts.append("SELECT 'KNVV' AS table_name, CAST(COUNT(*) AS bigint) AS row_count FROM \"KNVV\"")
                    diag_sql = "\nUNION ALL\n".join(diag_sql_parts) + "\nLIMIT 10;"
                    answer = (
                        "Your previous query returned **0 rows**, so follow-ups can’t answer from results.\n"
                        "First confirm whether these tables contain data in this database. If they are empty, no SQL rewrite will help.\n\n"
                        "Run this diagnostic SQL as a **New question**:\n\n"
                        "```sql\n"
                        f"{diag_sql}\n"
                        "```"
                    )
                    return {"type": "analysis", "answer": answer}

            schema_context = build_schema_context(
                question=f"{prev_q}\n{q}".strip(),
                focus_tables=None,
                max_tables=45,
                max_cols_per_table=60,
            )

            instructions = (
                "You are a helpful SAP/PostgreSQL data assistant.\n\n"
                "You receive a previous question, the SQL that was executed, and the resulting rows (may be empty).\n"
                "You must answer the user's follow-up.\n\n"
                "Rules:\n"
                "- If the rows are NON-empty and the follow-up can be answered from them, answer using ONLY those rows.\n"
                "- If the rows are empty OR the user is asking to revise/fix the query, do NOT pretend you have data.\n"
                "  Instead: explain the most likely reason the SQL returned 0 rows, and propose ONE improved PostgreSQL SELECT query.\n"
                "  The proposed SQL must use ONLY tables/columns that exist in the provided schema catalog.\n"
                "  Do NOT execute SQL.\n"
                "- When proposing SQL, include LIMIT 100 and sensible ORDER BY.\n"
                "- HARD REQUIREMENT:\n"
                "  If rows_empty=true OR wants_revision=true, you MUST include exactly ONE SQL query in a fenced ```sql block.\n"
                "  The SQL must be a single SELECT statement (no CTEs if possible), no comments, no markdown outside the fence.\n"
                "- Output format:\n"
                "  1) A short answer paragraph.\n"
                "  2) A single ```sql fenced block when required.\n"
            )

            # Keep rows sample bounded for token safety.
            rows_sample = rows_list[:30]
            prompt = (
                f"{instructions}\n\n"
                f"Schema catalog (tables and columns):\n{schema_context}\n\n"
                f"Previous question:\n{prev_q}\n\n"
                f"Previous SQL:\n{prev_sql[:2000]}\n\n"
                f"Row sample (JSON, up to 30 rows):\n{rows_sample}\n\n"
                f"Follow-up question:\n{q}\n\n"
                f"Context flags: rows_empty={is_empty}, wants_revision={wants_revision}\n"
            )
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=900,
            )
            answer = (resp.choices[0].message.content or "").strip()
            if not answer:
                answer = "I couldn't generate a follow-up answer from the provided data. Please rephrase."
            return {"type": "analysis", "answer": answer}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"follow_up_analysis_failed: {e}")

    # ── New query: NL → SQL → execute → rows + summary ───────────────────────
    # We reuse the Zodiac orchestrator (it already handles safe generation, execution, charts, and follow-up threads).
    try:
        # Fast-path: direct row-count diagnostics for explicitly mentioned tables.
        # This avoids the older "approve/suggest SQL" safety UX from the orchestrator for a simple COUNT request.
        if _looks_like_rowcount_question(q):
            tables = _extract_known_tables_from_question(q)
            # Keep it bounded and deterministic
            tables = tables[:10]
            if tables:
                selects = [
                    f"SELECT '{t}' AS table_name, CAST(COUNT(*) AS bigint) AS row_count FROM \"{t}\""
                    for t in tables
                ]
                sql = "\nUNION ALL\n".join(selects) + "\nLIMIT 10;"

                sess = None
                try:
                    sess = get_sap_session() if USE_SAP_DB_FOR_AI else db
                    rows = sess.execute(text(sql)).mappings().all()
                    data = [dict(r) for r in rows]
                finally:
                    # Only close if we opened a separate SAP session
                    if USE_SAP_DB_FOR_AI and sess is not None:
                        sess.close()

                return {
                    "sql": sql,
                    "rowCount": len(data),
                    "data": data,
                    "tableHint": tableHint or None,
                    "summary": "Row counts by table.",
                }

        from ..services.ai_analysis_orchestrator import run_ai_analysis_orchestrator, orchestrator_payload

        sap_session_for_sql = get_sap_session() if USE_SAP_DB_FOR_AI else None
        try:
            orch = run_ai_analysis_orchestrator(
                api_key=api_key,
                user_id=0,  # anonymous compatibility mode
                user_query=q,
                db=db,
                conversation_history=[],
                context_str="",
                sap_db=sap_session_for_sql,
                time_scope="current",
                days=30,
                thread_id=None,
                query_mode="new",
            )
            payload = orchestrator_payload(orch)
        finally:
            if sap_session_for_sql is not None:
                sap_session_for_sql.close()

        data_rows = payload.get("rows") or payload.get("rows_preview") or []
        if not isinstance(data_rows, list):
            data_rows = []

        out: Dict[str, Any] = {
            "sql": payload.get("sql") or "",
            "rowCount": len(data_rows),
            "data": data_rows,
            "tableHint": tableHint or None,
            "summary": payload.get("reply") or None,
        }
        if payload.get("charts"):
            out["charts"] = payload.get("charts")
        return out
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"adaptive_query_failed: {e}")

