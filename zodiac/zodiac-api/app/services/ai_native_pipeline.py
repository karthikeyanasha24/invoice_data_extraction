"""AI-native Analyst pipeline.

Catalog JSON, metric registry, and example joins are GUIDES only.
The model chooses tables, columns, and SQL. Compilers are not used here.

Stages:
  1. Analyse the user question
  2. Choose tables from the migrated catalog
  3. Choose columns (+ joins) for those tables
  4. Generate SELECT SQL
  5. Execute, then AI summary / findings / chart hints
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from ..data_catalog.physical import column_names, has_column, has_table, sap_business_tables
from ..data_catalog.registry import METRICS, RELATIONSHIPS, TABLE_ENTRIES, get_table_entry
from .adaptive_nl_sql_hardening import repair_generated_sql
from .sql_grain_guard import sql_has_unsafe_monetary_fanout

logger = logging.getLogger("zodiac-api.ai_native_pipeline")

ExecuteSql = Callable[[Session, str, str], List[Dict[str, Any]]]
ChartFn = Callable[[str, str, List[Dict[str, Any]]], List[Dict[str, Any]]]

_SQL_BLOCK = re.compile(r"```sql\s*([\s\S]+?)\s*```", re.I)
_JSON_BLOCK = re.compile(r"```json\s*([\s\S]+?)\s*```", re.I)
_FORBIDDEN = re.compile(
    r"\b(DELETE|UPDATE|DROP|ALTER|TRUNCATE|INSERT|CREATE|EXEC|GRANT|REVOKE|COPY|GRANT)\b",
    re.I,
)


def ai_native_enabled() -> bool:
    return os.getenv("AI_NATIVE_PIPELINE", "true").strip().lower() in {"1", "true", "yes", "on"}


def _openai_key() -> str:
    return (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or "").strip()


def _google_key() -> str:
    return (os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()


def _openai_model() -> str:
    return os.getenv("AI_NATIVE_OPENAI_MODEL") or os.getenv("AI_FAST_MODEL") or "gpt-4o-mini"


def _gemini_model() -> str:
    return os.getenv("AI_NATIVE_GEMINI_MODEL") or os.getenv("GEMINI_CHAT_MODEL") or "gemini-2.5-flash"


def parse_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    m = _JSON_BLOCK.search(raw)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        raw = raw[start : end + 1]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("LLM JSON was not an object")
    return data


def extract_sql(text: str) -> str:
    m = _SQL_BLOCK.search(text or "")
    if m:
        return m.group(1).strip().rstrip(";")
    m2 = re.search(r"(SELECT[\s\S]+)$", text or "", re.I)
    if m2:
        return m2.group(1).strip().rstrip(";")
    return ""


def catalog_guide_text() -> str:
    """Compact migrated-table guide. Not executable SQL."""
    lines = [
        "MIGRATED SAP TABLES (guide only — pick from this list; columns must exist):",
        "VBED is NOT in this extract. Schedule lines are VBEP.",
        "Sales orders = VBAK/VBAP. Billing/invoices = VBRK/vbrp. Do not equate VBAK.vbeln with VBRK.vbeln.",
        "Numeric SAP fields are often TEXT — CAST(NULLIF(TRIM(CAST(col AS TEXT)),'') AS NUMERIC).",
        "Quote identifiers: FROM \"VBAK\" AS v. vbrp is lowercase: FROM \"vbrp\" AS p.",
        "Dates are TEXT YYYYMMDD — compare as strings, do not CAST AS DATE.",
        "",
    ]
    for table in sap_business_tables():
        entry = get_table_entry(table) or TABLE_ENTRIES.get(table) or {}
        cols = entry.get("important_columns") or column_names(table)[:12]
        grain = entry.get("grain") or ""
        name = entry.get("business_name") or table
        domain = entry.get("primary_domain") or entry.get("domain") or ""
        lines.append(
            f"- {table} [{domain}] {name}. grain={grain}. cols={', '.join(cols[:14])}"
        )
    lines.append("")
    lines.append("METRIC GUIDES (hints, not mandatory SQL):")
    for metric in list(METRICS.values())[:18]:
        lines.append(
            f"- {metric.get('metric_name')}: {metric.get('business_meaning')} "
            f"tables={metric.get('authoritative_tables')} agg={metric.get('aggregation')}"
        )
    lines.append("")
    lines.append("JOIN GUIDES (use verified only; skip unverified):")
    for rel in RELATIONSHIPS:
        flag = "OK" if rel.get("usable_in_sql") else "UNSAFE"
        lines.append(
            f"- [{flag}] {rel.get('source_table')}.{rel.get('source_column')} = "
            f"{rel.get('target_table')}.{rel.get('target_column')} "
            f"({rel.get('cardinality')}; {rel.get('fanout')})"
        )
    return "\n".join(lines)


def columns_guide(tables: List[str]) -> str:
    chunks = []
    for table in tables:
        if not has_table(table):
            chunks.append(f"{table}: ABSENT FROM MIGRATED SCHEMA")
            continue
        cols = column_names(table)
        chunks.append(f"{table} ({len(cols)} cols): " + ", ".join(cols[:80]))
        if len(cols) > 80:
            chunks.append(f"  ... {len(cols) - 80} more omitted")
    return "\n".join(chunks)


def _openai_chat(system: str, user: str, *, json_mode: bool = False) -> str:
    from openai import OpenAI
    from ..utils.openai_chat_params import openai_chat_temperature_kwargs, openai_completion_limit_kwargs

    model = _openai_model()
    client = OpenAI(api_key=_openai_key())
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **openai_chat_temperature_kwargs(model, 0.1),
        **openai_completion_limit_kwargs(model, 1200),
    }
    if json_mode and not str(model).lower().startswith("gpt-5"):
        kwargs["response_format"] = {"type": "json_object"}
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def _gemini_chat(system: str, user: str) -> str:
    key = _google_key()
    if not key:
        raise RuntimeError("GOOGLE_API_KEY is not set")
    body = json.dumps(
        {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048},
        }
    ).encode()
    model = _gemini_model()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={key}"
    )
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"Gemini HTTP {exc.code}: {detail}") from exc
    parts = ((((payload.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or [])
    return "".join(str(p.get("text") or "") for p in parts).strip()


def _is_openai_quota(exc: BaseException) -> bool:
    t = str(exc).lower()
    return "insufficient_quota" in t or "credit_balance_exhausted" in t


_SKIP_OPENAI = False


def llm_text(system: str, user: str, *, json_mode: bool = False) -> Tuple[str, str]:
    """Return (text, provider). OpenAI first, Gemini on quota/error if keyed."""
    global _SKIP_OPENAI
    last_err: Optional[BaseException] = None
    if _openai_key() and not _SKIP_OPENAI:
        try:
            return _openai_chat(system, user, json_mode=json_mode), "openai"
        except Exception as exc:
            last_err = exc
            if _is_openai_quota(exc):
                _SKIP_OPENAI = True
            if not _is_openai_quota(exc) and not _google_key():
                raise
            logger.warning("[ai-native] OpenAI failed (%s); trying Gemini", type(exc).__name__)
    if _google_key():
        return _gemini_chat(system, user), "gemini"
    if last_err:
        raise last_err
    raise RuntimeError("No OpenAI or Gemini API key configured")


def llm_json(system: str, user: str) -> Tuple[Dict[str, Any], str]:
    text, provider = llm_text(system, user, json_mode=True)
    try:
        return parse_json_object(text), provider
    except Exception:
        # one repair pass
        text2, provider = llm_text(
            "Return a single JSON object only.",
            f"Convert this into valid JSON object:\n{text[:4000]}",
            json_mode=True,
        )
        return parse_json_object(text2), provider


def _safe_select(sql: str) -> Optional[str]:
    s = (sql or "").strip()
    if not s:
        return None
    if not re.match(r"^SELECT\b", s, re.I):
        return None
    if _FORBIDDEN.search(s):
        return None
    if ";" in s[:-1]:
        return None
    return s


def _schema_violations(sql: str) -> List[str]:
    found = re.findall(r'FROM\s+"?([A-Za-z0-9_]+)"?|JOIN\s+"?([A-Za-z0-9_]+)"?', sql, re.I)
    tables = [a or b for a, b in found]
    bad = []
    for t in tables:
        if t.upper() in {"SELECT", "WHERE", "LATERAL"}:
            continue
        if not has_table(t):
            bad.append(f"unknown table {t}")
    for table, col in re.findall(r'"([A-Za-z0-9_]+)"\s*\.\s*"([A-Za-z0-9_]+)"', sql):
        if has_table(table) and not has_column(table, col):
            bad.append(f"unknown column {table}.{col}")
    return bad[:12]


def run_ai_native_pipeline(
    question: str,
    db: Session,
    execute_sql: ExecuteSql,
    *,
    use_sap: bool = False,
    chart_fn: Optional[ChartFn] = None,
    prior_question: str = "",
    prior_sql: str = "",
    get_sap_session: Optional[Callable[[], Any]] = None,
) -> Optional[Dict[str, Any]]:
    q = (question or "").strip()
    if not q:
        return None

    providers: List[str] = []
    stages: Dict[str, Any] = {}

    # ── Stage 1: analyse ──────────────────────────────────────────────
    analysis, p1 = llm_json(
        "You are the BridgeEDI SAP analyst planner. Reply JSON only.",
        (
            "Analyse this user message.\n"
            "If it is a greeting, chit-chat, or not a data question, set kind=conversation "
            "and put a helpful reply in reply.\n"
            "If it is a business/data question, set kind=data_question.\n"
            "JSON keys: kind, reply, restated_question, metric, dimensions (array), "
            "domain_hints (array), needs_sql (boolean).\n"
            f"User: {q}\n"
            f"Previous question: {prior_question or '(none)'}\n"
        ),
    )
    providers.append(p1)
    stages["analyse"] = analysis
    if str(analysis.get("kind") or "").lower() == "conversation" or analysis.get("needs_sql") is False:
        reply = str(analysis.get("reply") or "").strip() or (
            "Hello. Ask a business question and I will pick tables, write SQL, and answer from the database."
        )
        return {
            "sql": "",
            "rowCount": 0,
            "data": [],
            "summary": reply,
            "answer": reply,
            "keyFindings": [],
            "charts": [],
            "pipeline": "ai_native",
            "sql_generation_method": "ai_native_conversation",
            "llm_calls": 1,
            "answer_status": "SUCCESS",
            "meta": {"ai_native_stages": stages, "providers": providers},
        }

    restated = str(analysis.get("restated_question") or q).strip() or q
    catalog = catalog_guide_text()

    # ── Stage 2: tables ───────────────────────────────────────────────
    table_pick, p2 = llm_json(
        "You choose SAP tables. JSON only. Use only tables from the guide.",
        (
            f"Question: {restated}\nOriginal: {q}\nAnalysis: {json.dumps(analysis)}\n\n"
            f"{catalog}\n\n"
            "Return JSON: {\"tables\": [\"VBAK\"], \"why\": \"...\"}. "
            "2-6 tables. Never invent a table name. Never pick VBED."
        ),
    )
    providers.append(p2)
    stages["tables"] = table_pick
    tables = []
    for t in table_pick.get("tables") or []:
        name = str(t).strip()
        if has_table(name):
            tables.append(name)
    if not tables:
        return {
            "sql": "",
            "rowCount": 0,
            "data": [],
            "summary": "I could not match that question to any migrated table. "
            + str(table_pick.get("why") or ""),
            "keyFindings": [],
            "pipeline": "ai_native",
            "sql_generation_method": "ai_native",
            "llm_calls": len(providers),
            "answer_status": "CANNOT_ANSWER",
            "meta": {"ai_native_stages": stages, "providers": providers},
        }

    # ── Stage 3: columns ──────────────────────────────────────────────
    col_pick, p3 = llm_json(
        "You choose columns and joins. JSON only. Use only real columns listed.",
        (
            f"Question: {restated}\nTables: {tables}\n\n"
            f"{columns_guide(tables)}\n\n"
            f"Join guides:\n"
            + "\n".join(
                f"{r.get('source_table')}.{r.get('source_column')}="
                f"{r.get('target_table')}.{r.get('target_column')} "
                f"usable={r.get('usable_in_sql')}"
                for r in RELATIONSHIPS
            )
            + "\nReturn JSON: {\"columns\": {\"TABLE\": [\"col\"]}, \"joins\": [\"...\"], \"grain_note\": \"...\"}"
        ),
    )
    providers.append(p3)
    stages["columns"] = col_pick

    # ── Stage 4: SQL ──────────────────────────────────────────────────
    sql_system = (
        "You write PostgreSQL SELECT for a migrated SAP extract. "
        "Guides are hints, not copy-paste templates. "
        "Return SQL in a ```sql block only. SELECT only. LIMIT 100 unless an aggregate. "
        "Quote SAP tables. CAST text numerics. Do not join VBAK.vbeln = VBRK.vbeln. "
        "Do not join billing NETWR with EKPO/VBFA/MBEW in the same SUM."
    )
    sql_user = (
        f"Question: {restated}\nOriginal: {q}\n"
        f"Chosen tables: {tables}\n"
        f"Chosen columns: {json.dumps(col_pick)}\n"
        f"Prior SQL (follow-up context, optional):\n{prior_sql[:1500] or '(none)'}\n"
        f"{catalog[:4000]}\n"
        "Generate the SQL."
    )
    sql_raw, p4 = llm_text(sql_system, sql_user)
    providers.append(p4)
    sql = extract_sql(sql_raw)
    sql = repair_generated_sql(sql, restated) if sql else ""
    sql = _safe_select(sql) or ""
    stages["sql_draft"] = sql[:2000]

    if not sql:
        return None  # fall back to compilers
    if sql_has_unsafe_monetary_fanout(sql):
        retry, p4b = llm_text(
            sql_system,
            sql_user
            + "\n\nYour previous SQL mixed incompatible grains (billing NETWR with PO/inventory/order). "
            "Rewrite using one fact grain only.",
        )
        providers.append(p4b)
        sql = _safe_select(repair_generated_sql(extract_sql(retry), restated)) or ""
        if not sql or sql_has_unsafe_monetary_fanout(sql):
            return None
    violations = _schema_violations(sql)
    if violations:
        retry, p4c = llm_text(
            sql_system,
            sql_user + "\n\nSchema errors:\n- " + "\n- ".join(violations) + "\nFix the SQL.",
        )
        providers.append(p4c)
        sql = _safe_select(repair_generated_sql(extract_sql(retry), restated)) or ""
        if not sql or _schema_violations(sql):
            return None

    sess = db
    sap = None
    try:
        if use_sap and get_sap_session:
            sap = get_sap_session()
            if sap is not None:
                sess = sap
        rows = execute_sql(sess, sql, restated)
    except Exception as exc:
        logger.warning("[ai-native] SQL execute failed: %s", exc)
        retry, p4d = llm_text(
            sql_system,
            sql_user + f"\n\nPostgreSQL error:\n{str(exc)[:500]}\nFix the SQL.",
        )
        providers.append(p4d)
        sql = _safe_select(repair_generated_sql(extract_sql(retry), restated)) or ""
        if not sql:
            return None
        try:
            rows = execute_sql(sess, sql, restated)
        except Exception as exc2:
            logger.warning("[ai-native] retry execute failed: %s", exc2)
            return None
    finally:
        if sap is not None:
            try:
                sap.close()
            except Exception:
                pass

    charts: List[Dict[str, Any]] = []
    if chart_fn:
        try:
            charts = chart_fn(restated, sql, rows) or []
        except Exception as chart_err:
            logger.warning("[ai-native] charts failed: %s", chart_err)

    # ── Stage 5: summary / findings ───────────────────────────────────
    narrative, p5 = llm_json(
        "You are a business analyst. JSON only. Use only numbers present in the rows.",
        (
            f"Question: {q}\nRestated: {restated}\nSQL:\n{sql[:1500]}\n"
            f"Row count: {len(rows)}\nSample: {json.dumps(rows[:12], default=str)[:4000]}\n"
            "Return JSON: {\"summary\": \"2-5 sentences\", \"key_findings\": [\"...\"], "
            "\"chart_title\": \"...\"}. If 0 rows, say so honestly. Never invent totals."
        ),
    )
    providers.append(p5)
    stages["narrative"] = {k: narrative.get(k) for k in ("summary", "key_findings", "chart_title")}
    summary = str(narrative.get("summary") or "").strip() or f"Query returned {len(rows)} row(s)."
    findings = narrative.get("key_findings") or []
    if not isinstance(findings, list):
        findings = [str(findings)]
    findings = [str(f).strip() for f in findings if str(f).strip()][:8]

    return {
        "sql": sql,
        "rowCount": len(rows),
        "data": rows,
        "summary": summary,
        "keyFindings": findings,
        "charts": charts,
        "pipeline": "ai_native",
        "sql_generation_method": "ai_native",
        "llm_calls": len(providers),
        "answer_status": "SUCCESS",
        "meta": {
            "ai_native_stages": {
                "analyse": analysis,
                "tables": tables,
                "columns": col_pick,
                "providers": providers,
            },
            "providers": providers,
            "source": "AI-chosen tables/columns/SQL; catalog used as guide only",
        },
        "suggested_followups": [
            "Break that down by a different dimension",
            "Show the underlying table rows",
        ],
    }
