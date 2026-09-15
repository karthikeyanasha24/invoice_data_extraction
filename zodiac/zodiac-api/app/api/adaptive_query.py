"""
Universal Adaptive Query API — answers ANY question about ALL 121 database tables.

POST /api/query/adaptive
Body: { question, tableHint?, contextData?, overrideSql? }

Architecture:
  - Reads tables_columns.csv (121 tables, 9,352 columns) at startup, cached forever
  - Generates a full schema context with data types (text/numeric/date/etc.)
  - Sends complete schema + rich system prompt to GPT-4o
  - Auto-retries up to 3x with exact PostgreSQL error fed back for self-correction
  - Applies all SQL sanitizers (SAP text→numeric cast, HAVING alias fix, :: cast conversion)
  - Fallback to orchestrator if all retries fail
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import threading
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import text

from ..database import get_db
from ..config.config import OPENAI_API_KEY, USE_SAP_DB_FOR_AI
from ..database import get_sap_session
from ..services.ai_followup_routing import (
    TurnIntent,
    classify_turn,
    resolve_follow_up_sql_need,
    should_route_to_general_chat,
)
from ..services.adaptive_nl_sql_hardening import (
    StageTimer,
    apply_plan_sql_deltas,
    apply_statement_timeout,
    clarification_payload,
    customer_not_found_payload,
    deterministic_summary,
    extract_named_customer,
    inject_customer_name_predicate,
    is_capability_or_help_question,
    is_general_knowledge_question,
    is_greeting_or_chitchat,
    local_sql_relation_names,
    public_chart_title,
    question_asks_date_filter,
    question_requires_database,
    repair_generated_sql,
    sanitize_chart_payloads,
    sql_has_customer_name_filter,
)
from ..services.ai_query_plan import (
    compose_nl_from_plan,
    extract_query_plan,
    plan_prompt_directive,
    QueryPlan,
)
from ..api.auth import get_current_user
from ..models.user import ZodiacUser

logger = logging.getLogger("zodiac-api.adaptive_query")
router = APIRouter(tags=["adaptive-query"])

# ─── Paths ────────────────────────────────────────────────────────────────────
_CSV_PATH    = Path(__file__).resolve().parent.parent.parent / "tables_columns.csv"
_SCHEMA_JSON = Path(__file__).resolve().parent.parent.parent / "schema_full.json"


# ─── Schema loader (process-lifetime cache) ───────────────────────────────────

@lru_cache(maxsize=1)
def _load_schema() -> Dict[str, List[Dict[str, str]]]:
    """
    Returns { table_name: [ {col, type}, ... ] }.
    Prefers schema_full.json if present (pre-generated), otherwise reads CSV.
    """
    if _SCHEMA_JSON.exists():
        with open(_SCHEMA_JSON, encoding="utf-8") as f:
            return json.load(f)

    tables: Dict[str, List[Dict[str, str]]] = {}
    with open(_CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tbl = (row.get("table") or "").strip()
            col = (row.get("column") or "").strip()
            dt  = (row.get("data_type") or "text").strip().lower()
            if tbl and col:
                tables.setdefault(tbl, []).append({"col": col, "type": dt})
    return tables


def _table_cols(tbl: str) -> List[str]:
    return [c["col"] for c in _load_schema().get(tbl, [])]


def _col_type(tbl: str, col: str) -> str:
    for c in _load_schema().get(tbl, []):
        if c["col"] == col:
            return c["type"]
    return "text"


def _table_has_column(table: str, column: str) -> bool:
    """True if schema lists `column` on `table` (case-insensitive). Schema is source of truth."""
    want_t = (table or "").strip().lower()
    want_c = (column or "").strip().lower()
    if not want_t or not want_c:
        return False
    schema = _load_schema()
    for tname, cols in schema.items():
        if str(tname).lower() != want_t:
            continue
        for c in cols or []:
            if str(c.get("col") or "").lower() == want_c:
                return True
    return False


def _looks_like_schema_structure_question(question: str) -> bool:
    q = (question or "").lower()
    if re.search(r"\b(top|highest|lowest|biggest)\b.*\b(sales|revenue|customer)", q):
        return False
    return bool(
        re.search(
            r"\b(which tables?|what tables?|tables? contain|shared columns?|"
            r"columns? (?:in|on|of|for)|data type|datatype|schema lookup|show columns)\b",
            q,
        )
    )


def _extract_known_columns_from_question(question: str) -> List[str]:
    q = (question or "").lower()
    found: List[str] = []
    seen = set()
    schema = _load_schema()
    for cols in schema.values():
        for c in cols or []:
            name = str(c.get("col") or "")
            key = name.lower()
            if key and key not in seen and re.search(rf"\b{re.escape(key)}\b", q):
                seen.add(key)
                found.append(name)
    return found


def _build_schema_structure_answer(question: str) -> str:
    q = question or ""
    tables = re.findall(r"\b(VBRK|VBRP|KNA1|T016T|MAKT|MARA)\b", q, re.I)
    tables_u = list(dict.fromkeys(t.upper() for t in tables))
    schema = _load_schema()
    schema_ci = {t.lower(): t for t in schema}
    lines = ["Schema lookup"]
    if len(tables_u) >= 2:
        a, b = tables_u[0], tables_u[1]
        ca = {c["col"].lower() for c in schema.get(schema_ci.get(a.lower(), a), [])}
        cb = {c["col"].lower() for c in schema.get(schema_ci.get(b.lower(), b), [])}
        shared = sorted(ca & cb)
        lines.append(f"Shared columns between {a} and {b}: " + (", ".join(shared[:20]) or "(none)"))
        lines.append(a.lower())
        lines.append(b.lower())
    cols = _extract_known_columns_from_question(q)
    if cols:
        lines.append("Known columns in the question: " + ", ".join(cols[:12]))
    return "\n".join(lines)


def _schema_intent_type(question: str) -> str:
    q = (question or "").lower()
    if re.search(r"\bdata\s*type|datatype\b", q):
        return "datatype_lookup"
    if re.search(r"\bshared columns?|common columns?|join\b", q):
        return "join_candidates"
    if re.search(r"\bwhich tables?|tables? contain|column_lookup\b", q):
        return "column_lookup"
    if re.search(r"\bcolumns? in|table profile|show columns\b", q):
        return "table_profile"
    if re.search(r"\bexplain this business domain|coverage gap\b", q) and not _extract_known_columns_from_question(q):
        return "coverage_gap"
    return "schema_lookup"


def _recover_near_miss_token(token: str, choices: List[str]) -> Optional[str]:
    import difflib
    t = (token or "").lower()
    if not t or not choices:
        return None
    hits = difflib.get_close_matches(t, [c.lower() for c in choices], n=1, cutoff=0.72)
    return hits[0] if hits else None


def _build_schema_structure_payload(question: str) -> Dict[str, Any]:
    schema = _load_schema()
    table_names = list(schema.keys())
    col_names: List[str] = []
    for cols in schema.values():
        for c in cols or []:
            n = str(c.get("col") or "")
            if n:
                col_names.append(n)
    intent = _schema_intent_type(question)
    q_tokens = re.findall(r"[A-Za-z][A-Za-z0-9_]{2,}", question or "")
    recovered_tables = []
    recovered_cols = []
    for tok in q_tokens:
        nt = _recover_near_miss_token(tok, table_names)
        if nt:
            recovered_tables.append(nt)
        nc = _recover_near_miss_token(tok, col_names)
        if nc:
            recovered_cols.append(nc)
    answer = _build_schema_structure_answer(question)
    if recovered_tables:
        answer += "\nTables: " + ", ".join(dict.fromkeys(recovered_tables))
    if recovered_cols:
        answer += "\nColumns: " + ", ".join(dict.fromkeys(recovered_cols))
    clarifying = None
    if intent == "coverage_gap":
        clarifying = "Which SAP process should I look at — billing, customers, products, or invoices?"
        answer += "\nThis question is too broad for a schema lookup."
    payload: Dict[str, Any] = {
        "type": "analysis",
        "schemaIntentType": intent,
        "confidence": 0.82 if intent != "coverage_gap" else 0.35,
        "answer": answer,
        "summary": answer,
        "suggestions": [
            "Which tables contain netwr?",
            "What common columns are shared between VBRK and VBRP?",
        ],
        "matches": {
            "tables": list(dict.fromkeys(recovered_tables))[:12],
            "columns": list(dict.fromkeys(recovered_cols))[:20],
        },
    }
    if clarifying:
        payload["clarifyingQuestion"] = clarifying
    return payload


def _guardrail_intent_text(question: str, plan: Optional[QueryPlan] = None) -> str:
    """
    Extract the user's real question for intent-sensitive guardrails.

    Follow-up prompts embed instructional text (e.g. 'For invoice zero/negative: …')
    which must NOT trigger zero/negative invoice rules on ordinary sales queries.
    """
    q = question or ""
    m = re.search(
        r"New request \(generate ONE new PostgreSQL SELECT for this\):\s*(.+?)(?:\nRules:|\Z)",
        q,
        re.I | re.S,
    )
    if m:
        return m.group(1).strip()
    m2 = re.search(r"(?im)^Question:\s*(.+)$", q.strip())
    if m2:
        return m2.group(1).strip()
    # Drop continuation boilerplate / embedded SQL rules
    skip_frags = (
        "continuation of an analysis",
        "previous sql",
        "previous question:",
        "sample of prior",
        "semantic query plan",
        "for invoice zero/negative",
        "generate one new postgresql",
        "rules:",
        "scope change:",
        "product drill-down:",
    )
    lines: List[str] = []
    for line in q.splitlines():
        ll = line.lower().strip()
        if not ll:
            continue
        if any(f in ll for f in skip_frags):
            continue
        if ll.startswith("```"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    if cleaned:
        return cleaned
    if plan is not None:
        # Last resort: reconstruct a short intent phrase from the plan
        parts = [plan.metric or "sales"]
        if plan.dimensions:
            parts.append("by " + ", ".join(plan.dimensions))
        years = (plan.filters or {}).get("years") or []
        if years:
            parts.append("years " + ",".join(str(y) for y in years))
        return " ".join(parts)
    return q


def _is_sap_erp_intent(question: str, plan: Optional[QueryPlan] = None) -> bool:
    """
    True when the question must stay in SAP/ERP (VBRK/KNA1/T016T/…) domain.

    Prevents failed SAP generation from silently answering via Zodiac EDI tables.
    """
    q = _guardrail_intent_text(question, plan).lower()
    # Explicit EDI / portal ops without SAP sales semantics may use invoice_v2_* intentionally
    edi_only = any(
        tok in q
        for tok in (
            "edi", "cfdi", "sat document", "zodiac invoice", "invoice_v2",
            "portal invoice", "failed edi", "success edi",
        )
    )
    sap_tokens = (
        "sales", "revenue", "turnover", "billing", "industry", "sector",
        "vbrk", "vbrp", "kna1", "t016t", "mara", "makt", "material", "matnr",
        "sap", "fkdat", "kunag", "brsch", "brtxt", "highest sales", "total sales",
        "by customer", "by industry", "product",
        "top customers", "biggest customers", "largest customers",
        "top 10 customers", "top 5 customers",
    )
    has_sap = any(tok in q for tok in sap_tokens)
    if plan is not None:
        if plan.metric == "sales":
            has_sap = True
        if any(d in (plan.dimensions or []) for d in ("industry", "product", "customer")):
            if plan.metric in ("sales", "quantity", "average") or (plan.filters or {}).get("years"):
                has_sap = True
        if plan.grain == "line":
            has_sap = True
        if (plan.filters or {}).get("years") and plan.metric in ("sales", "count", "average"):
            # year-scoped sales/count on follow-up stays SAP unless clearly EDI-only
            if "invoice count" in q and not any(t in q for t in ("sales", "revenue", "billing", "industry")):
                pass
            else:
                has_sap = True
    if not has_sap:
        return False
    if edi_only and not any(t in q for t in ("sales", "revenue", "industry", "vbrk", "billing", "sap")):
        return False
    # "invoice count by customer" without year/sales/industry → allow EDI domain
    if "invoice count" in q and not any(
        t in q for t in ("sales", "revenue", "billing", "industry", "vbrk", "2004", "2005", "2003")
    ):
        if not (plan and (plan.filters or {}).get("years") and plan.metric == "sales"):
            return False
    return True


def _cannot_answer_payload(
    question: str,
    *,
    reason: str,
    plan: Optional[QueryPlan] = None,
    follow_up_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Explicit inability-to-answer — never an unrelated EDI row count."""
    summary = (
        "I couldn't reliably answer this SAP/ERP question because the required query "
        "could not be generated against the connected billing/customer/industry tables. "
        f"({reason}) Please rephrase or narrow the request — I will not substitute an "
        "unrelated EDI invoice count."
    )
    out: Dict[str, Any] = {
        "type": "cannot_answer",
        "answer_status": "CANNOT_ANSWER",
        "sql": "",
        "rowCount": 0,
        "data": [],
        "summary": summary,
        "answer": summary,
        "keyFindings": [
            "SAP/ERP query generation failed — no unrelated EDI fallback was used.",
            reason,
        ],
        "charts": [],
        "degraded_fallback": False,
        "domain_locked": "sap_erp",
        "failure_reason": reason,
        "question": (question or "")[:500],
    }
    if plan is not None:
        out["query_plan"] = plan.to_dict()
        out["plan_fingerprint"] = plan.fingerprint()
    if follow_up_mode:
        out["follow_up_mode"] = follow_up_mode
    return out


def _annotate_answer_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Attach answer_status without breaking older frontend fields."""
    if not isinstance(payload, dict):
        return payload
    # Cancellation must win over timeout-shaped payloads (type=timeout is reused).
    cancelled = (
        str(payload.get("answer_status") or "").upper() == "CANCELLED"
        or str(payload.get("status") or "").lower() in {"cancelled", "cancelling"}
        or str(payload.get("mode") or "").lower() in {"cancelled", "cancelling"}
        or str(payload.get("pipeline_stage") or "").upper() in {"CANCELLED", "CANCELLING"}
        or bool((payload.get("query_plan") or {}).get("investigation_cancelled"))
        or bool((payload.get("meta") or {}).get("investigation_cancelled"))
    )
    if cancelled:
        from ..services.investigation_budget import CANCELLED_USER_MESSAGE

        payload["answer_status"] = "CANCELLED"
        payload["status"] = "cancelled"
        payload["mode"] = "cancelled"
        payload["type"] = "cancelled"
        payload["pipeline_stage"] = "CANCELLED"
        if not (payload.get("summary") or "").strip() or "exceeded the allowed" in str(
            payload.get("summary") or ""
        ):
            payload["summary"] = CANCELLED_USER_MESSAGE
            payload["answer"] = CANCELLED_USER_MESSAGE
        payload["data"] = []
        payload["rowCount"] = 0
        return payload
    if (
        payload.get("status") == "timeout"
        or payload.get("mode") == "timeout"
        or payload.get("type") == "timeout"
        or payload.get("timeout")
        or str(payload.get("answer_status") or "").upper() == "TIMEOUT"
        or str(payload.get("error") or "") == "timeout"
    ):
        payload["answer_status"] = "TIMEOUT"
        payload["status"] = "timeout"
        payload["mode"] = "timeout"
        if not (payload.get("summary") or "").strip():
            from ..services.investigation_budget import TIMEOUT_USER_MESSAGE

            payload["summary"] = TIMEOUT_USER_MESSAGE
            payload["answer"] = TIMEOUT_USER_MESSAGE
        payload["data"] = []
        payload["rowCount"] = 0
        return payload
    if payload.get("answer_status"):
        return payload
    if payload.get("type") == "clarification":
        payload["answer_status"] = "CLARIFICATION"
        return payload
    if payload.get("type") == "cannot_answer" or payload.get("answer_status") == "CANNOT_ANSWER":
        payload["answer_status"] = "CANNOT_ANSWER"
        return payload
    if payload.get("degraded_fallback") or payload.get("follow_up_mode") == "analysis_fallback":
        payload["answer_status"] = "CANNOT_ANSWER"
        return payload
    if payload.get("type") == "analysis" and not (payload.get("sql") or "").strip():
        payload["answer_status"] = "PARTIAL"
        return payload
    if payload.get("execution_error") or payload.get("error_code"):
        payload["answer_status"] = "ERROR"
        return payload
    sql = (payload.get("sql") or "").strip().lower()
    if "total_rows" in sql and (
        "invoice_v2_business_data" in sql or "invoice_business_data" in sql
    ):
        # Legacy degraded count shape — never SUCCESS
        payload["answer_status"] = "CANNOT_ANSWER"
        payload["degraded_fallback"] = True
        return payload
    if payload.get("data") is not None or payload.get("sql"):
        payload["answer_status"] = "SUCCESS"
        return payload
    payload["answer_status"] = "ERROR"
    return payload


# ─── Numeric TEXT columns that need CAST in aggregate functions ───────────────
# These are columns the CSV says are TEXT but represent numeric values.
# Any SUM/AVG/MIN/MAX on these needs: CAST(NULLIF(TRIM(CAST(x AS TEXT)),'') AS NUMERIC)

_NUMERIC_TEXT_COLS: frozenset = frozenset({
    # Finance / GL
    "hsl","ksl","msl","wsl","hsl0","ksl0","msl0","wsl0",
    "dmbtr","wrbtr","dmbe2","hwbe2","pswbt","pswsl","pyamt",
    # Billing / Sales
    "netwr","mwsbp","wavwr","stawn","kwert","kbetr","kwert_k","kaqty",
    "kzwi1","kzwi2","kzwi3","kzwi4","kzwi5","kzwi6",
    "fkimg","fklmg","kwmeng","zmeng","amtbl","valtg",
    # Purchasing / Invoice
    "rmwwr","rmwsk","netpr","brtwr","zwert","gnetwr","dpamt",
    "wwert","otb_value","otb_res_value","otb_spec_value",
    # Quantities
    "menge","ktmng","abmng","lmein","cnfm_qty","fsh_salloc_qty","fsh_ralloc_qty",
    # Material weight/volume
    "brgew","ntgew","volum","sumbd","kcbrgew","kcntgew","kcvolum",
    # Costing
    "gpreis","fpreis","dpreis","preis1","preis2","preis3","preis4","preis5",
    "opreis","tpreis","wertb","wertn","summ1","summ2","summ3",
    "me_summ1","summ1_kpf","summ2_kpf","summ3_kpf",
    # Material valuation
    "stprs","verpr","salk3","absalk3","lbkum","eiprice",
    # Stock
    "labst","insme","einme",
    # CO amounts
    "wkg001","wkg002","wkg003","wkg004","wkg005",
    "wkg006","wkg007","wkg008","wkg009","wkg010","wkg011","wkg012",
    # Misc
    "naucost","nopcost","bmenge","retamt_fc","diff_amount","customs_val",
    "ocs_count","sumziffr",
})


# ─── Business context for every table ─────────────────────────────────────────

_TABLE_CONTEXT: Dict[str, str] = {
    # SAP Sales & Billing
    "VBRK":   "Billing document HEADER. One row = one invoice. vbeln=doc#, kunag=customer(payer), fkdat=billing date(YYYYMMDD), waerk=currency, netwr=net total(TEXT→CAST), fkart=doc type, vkorg=sales org, fktyp=billing category",
    "vbrp":   "Billing document ITEMS (stored lowercase). Many rows per invoice. vbeln=billing doc (links VBRK.vbeln), posnr=item#, matnr=material, arktx=description, netwr=item net value(TEXT→CAST), fkimg=billed qty(TEXT→CAST), fklmg=qty in sales UOM(TEXT→CAST), mwsbp=tax(TEXT→CAST), vgbel=ref sales order, vgpos=ref sales item",
    "VBAK":   "Sales order HEADER. vbeln=SO#, audat=order date(YYYYMMDD), kunnr=customer, netwr=SO net value(TEXT→CAST), vkorg=sales org, vtweg=distribution channel, auart=order type, erdat=created date",
    "VBAP":   "Sales order ITEMS. vbeln=SO#, posnr=item#, matnr=material, arktx=description, kwmeng=confirmed order qty(TEXT→CAST), zmeng=target qty(TEXT→CAST), netwr=item value(TEXT→CAST), werks=plant, vgbel=ref doc",
    "VBEP":   "Sales order schedule lines. vbeln=SO#, posnr=item#, etenr=schedule line#, edatu=delivery date(YYYYMMDD), wmeng=confirmed qty",
    "VBFA":   "Document flow (traceability). vbelv=source doc, vbeln=target doc, vbtyp_n=target doc type (C=order, J=billing, L=delivery), posnv=source item, posnn=target item",
    "KONV":   "Pricing conditions. knumv=condition record#, kposn=item#, kschl=condition type (PR00=price, MWST=tax), kwert=condition value(TEXT→CAST), kbetr=rate(TEXT→CAST)",
    # SAP Delivery & Logistics
    "LIKP":   "Delivery HEADER. vbeln=delivery#, lfart=delivery type, lfdat=planned delivery date(YYYYMMDD), kunnr=customer, lifsk=delivery block, waerk=currency, netwr=total weight",
    "LIPS":   "Delivery ITEMS. vbeln=delivery#, posnr=item#, matnr=material, arktx=description, lfimg=delivery qty, vgbel=ref sales order, vgpos=ref SO item, werks=plant, lgort=storage location",
    "LSEG":   "Delivery segments (picking). vbeln=delivery#, posnr=item#, menge=picked qty",
    # SAP Purchasing
    "EKKO":   "Purchase order HEADER. ebeln=PO#, lifnr=vendor, bedat=PO creation date(YYYYMMDD), ekgrp=purch group, ekorg=purch org, waers=currency, loekz=deletion flag(''=active), kdatb=contract start, kdate=contract end, gwldt=GR deadline",
    "EKPO":   "Purchase order ITEMS. ebeln=PO#, ebelp=item#, matnr=material, txz01=description, menge=ordered qty(TEXT→CAST), meins=UOM, netpr=net price(TEXT→CAST), netwr=net value(TEXT→CAST), brtwr=gross value(TEXT→CAST), werks=plant, lgort=storage loc, agdat=expected delivery date(YYYYMMDD TEXT), elikz=delivery complete flag('X'=done), loekz=deletion flag, matkl=material group, infnr=info record#",
    "EBAN":   "Purchase requisition. banfn=req#, bnfpo=item#, matnr=material, menge=qty(TEXT→CAST), bsart=req type, afnam=requestor, badat=req date(YYYYMMDD), werks=plant",
    "EINA":   "Purchasing info record (general). infnr=info record#, matnr=material, lifnr=vendor",
    "EINE":   "Purchasing info record (org data). infnr=info record#, ekorg=purch org, netpr=net price(TEXT→CAST), peinh=price unit, waers=currency",
    "RBKP":   "Invoice receipt HEADER (MM-IV). belnr=doc#, gjahr=fiscal year, lifnr=vendor, budat=posting date(YYYYMMDD), rmwwr=gross amount(TEXT→CAST), rmwsk=tax amount(TEXT→CAST), waers=currency, bstat=status",
    "RSEG":   "Invoice receipt ITEMS. belnr=doc#, gjahr=fiscal year, buzei=item#, ebeln=PO#, ebelp=PO item#, matnr=material, menge=invoiced qty(TEXT→CAST), wrbtr=amount(TEXT→CAST), lbkum=stock qty(TEXT→CAST)",
    "RESB":   "Reservation / dependent requirements. matnr=material, werks=plant, menge=required qty, gpreis=planned price(TEXT→CAST)",
    # SAP Finance / Accounting
    "BKPF":   "Accounting document HEADER. belnr=doc#, bukrs=company code, gjahr=fiscal year, blart=doc type (SA=GL, KR=vendor invoice, DR=customer), budat=posting date(YYYYMMDD), bldat=doc date(YYYYMMDD), cpudt=entry date(YYYYMMDD), cputm=entry time, waers=currency, stblg=reversal doc#(''or'0000000000'=not reversed), stjah=reversal fiscal year, bktxt=header text, xstov=void flag",
    "BSEG":   "Accounting document SEGMENT (line items). belnr=doc#, bukrs=company, gjahr=fiscal year, buzei=line#, hkont=GL account, kunnr=customer#, lifnr=vendor#, dmbtr=local currency amount(TEXT→CAST), wrbtr=doc currency amount(TEXT→CAST), shkzg='S'=debit/'H'=credit, mwskz=tax code, kostl=cost center, prctr=profit center, menge=quantity(TEXT→CAST), meins=UOM, zuonr=assignment, sgtxt=line text, budat=posting date",
    "BSAD":   "Customer cleared items (open item accounting). belnr=doc#, kunnr=customer, dmbtr=cleared amount(TEXT→CAST), wrbtr=doc currency amount(TEXT→CAST), shkzg=D/C, budat=clearing date(YYYYMMDD), augdt=clearing date",
    "FAGLFLEXA": "General ledger ACTUAL line items (new GL). prctr=profit center, rbukrs=company code, racct=GL account, docnr=doc#, ryear=fiscal year, poper=period('001'-'012'), hsl=local amount(TEXT→CAST), ksl=2nd currency amount(TEXT→CAST), msl=quantity(TEXT→CAST), rtcur=currency, rclnt=client",
    "DFKKOP":  "FI-CA document item (contract accounts). faedn=due date(YYYYMMDD), betrw=amount, waers=currency",
    "T016T":   "Industry sector TEXTS (KNA1.brsch = T016T.brsch). Columns in THIS schema: brsch, brtxt (spras may be ABSENT — never invent spras). Use ONLY when the user explicitly asks for industry/sector; join via KNA1",
    # SAP Controlling
    "COEP":   "CO document line items (actual). kokrs=controlling area, belnr=doc#, buzei=item#, objnr=cost object, kstar=cost element, kostl=cost center, lstar=activity type, wkg001-wkg012=period amounts (need CAST if TEXT)",
    "COSP":   "Cost totals external postings. kokrs=controlling area, objnr=cost object, kstar=cost element, gjahr=fiscal year",
    "COSS":   "Cost totals internal postings. kokrs=controlling area, objnr, kstar, gjahr",
    "CEPC":   "Profit center master. prctr=profit center ID, kokrs=controlling area, name1=name, abtei=department, verak=manager, datbi=valid to(YYYYMMDD), datab=valid from",
    "CSKS":   "Cost center master. kostl=cost center ID, kokrs=controlling area, datbi=valid to, datab=valid from, ktext=description",
    "CSKT":   "Cost center texts. kostl=cost center, spras=language, ktext=name",
    "CRHD":   "Work center / resource header. arbid=resource ID, werks=plant, arbpl=work center, verwe=usage",
    "AUFK":   "Order master data. aufnr=order#, auart=order type, bukrs=company, werks=plant, erdat=created date",
    "AFKO":   "Production order header. aufnr=order#, plnbez=routing, stlnr=BOM, gstrs=scheduled start, gltrs=scheduled finish",
    "AFPO":   "Production order item. aufnr=order#, posnr=item#, matnr=material, plmng=planned qty, wemng=goods receipt qty",
    # SAP Costing
    "CKHS":   "Costing run header. kalnr=cost estimate#, menge=lot size(TEXT→CAST)",
    "CKIS":   "Cost estimate items. kalnr=cost estimate#, kkzma=item type, wertn=total value(TEXT→CAST), menge=qty(TEXT→CAST), gpreis=unit price(TEXT→CAST)",
    "CKIT":   "Costing item detail. kalnr, kkzma, matnr, kostl",
    "KEKO":   "Product costing header. kalnr=cost estimate#, matnr=material, werks=plant, lhkos=lot size, kadat=cost estimate date",
    "KEPH":   "Cost components. kalnr=cost estimate#, kkzma=cost component split",
    "CKMLCR": "Material ledger: currency and quantity. bwkey=valuation area, matnr=material, stprs=standard price(TEXT→CAST), salk3=total stock value(TEXT→CAST)",
    "CKMLHD": "Material ledger header. bwkey, matnr, bwtar, poper=period, bdatj=fiscal year",
    "CKMLPP": "Material ledger period data. bwkey, matnr, poper, lbkum=stock qty(TEXT→CAST)",
    "CKMLPR": "Material ledger prices. bwkey, matnr, poper, eiprice=entry price(TEXT→CAST)",
    "TCKH1":  "Cost element hierarchy. kokrs=controlling area, hierachie=hierarchy name",
    "TCKH2":  "Cost element hierarchy nodes. kokrs, hierachie, kstar=cost element",
    # CO-PA
    "CE1BGIS":"CO-PA actuals BGIS. prctr=profit center, kndnr=customer, artnr=product, ww001-ww080=value fields",
    "CE1IDEA":"CO-PA actuals IDEA. prctr, kndnr, artnr, ww001-ww080=value fields",
    "CE1INT1":"CO-PA actuals INT1. prctr, kndnr, artnr, value fields",
    "CE1PR22":"CO-PA actuals PR22. prctr, kndnr, artnr, value fields",
    "CE1R300":"CO-PA actuals R300. value fields per profit center and product",
    "CE1S_AL":"CO-PA actuals S_AL. value fields",
    "CE1S_CP":"CO-PA actuals S_CP. value fields",
    "CE1S_GO":"CO-PA actuals S_GO. value fields",
    "CE2BGIS":"CO-PA plan BGIS. same structure as CE1BGIS but plan data",
    "CE2IDEA":"CO-PA plan IDEA. plan value fields",
    "CE2S_AL":"CO-PA plan S_AL.",
    "CE2S_CP":"CO-PA plan S_CP.",
    "CS2S_GO":"CO-PA segment S_GO.",
    # SAP Master Data
    "KNA1":   "Customer master GENERAL. kunnr=customer ID, name1=name, name2=name2, land1=country code, regio=region, ort01=city, pstlz=postal code, ktokd=account group, sperr=order block flag, telf1=phone",
    "KNVV":   "Customer master SALES DATA. kunnr=customer, vkorg=sales org, vtweg=dist channel, spart=division, kdgrp=customer group, zterm=payment terms, vkbur=sales office, vkgrp=sales group",
    "KNVP":   "Customer partner functions. kunnr, vkorg, vtweg, spart, parvw=partner function (AG=sold-to, WE=ship-to, RE=bill-to, RG=payer)",
    "KNBK":   "Customer bank data. kunnr=customer, banks=bank country, bankl=bank key, bankn=bank account",
    "LFA1":   "Vendor master GENERAL. lifnr=vendor ID, name1=name, land1=country, regio=region, ort01=city, sperr=purchase block, loevm=deletion flag",
    "LFB1":   "Vendor master COMPANY CODE. lifnr=vendor, bukrs=company, zterm=payment terms, akont=reconciliation account",
    "LFM1":   "Vendor master PURCHASING ORG. lifnr=vendor, ekorg=purch org, waers=currency, zterm=payment terms",
    "MARA":   "Material master GENERAL. matnr=material ID, mtart=material type (FERT=finished,ROH=raw,HALB=semi), matkl=material group, meins=base UOM, brgew=gross weight(TEXT→CAST), ntgew=net weight(TEXT→CAST), volum=volume(TEXT→CAST), normt=industry standard, bismt=old material#, spart=division",
    "MAKT":   "Material DESCRIPTIONS. matnr=material ID, spras=language, maktx=description text",
    "MARC":   "Material PLANT DATA. matnr=material, werks=plant, beskz=procurement type (E=in-house, F=external), eisbe=safety stock, minbe=reorder point, mtvfp=checking rule, mmsta=plant status",
    "MARD":   "Material STORAGE LOCATION STOCK. matnr=material, werks=plant, lgort=storage location, labst=unrestricted stock(TEXT→CAST), insme=quality inspection stock(TEXT→CAST), einme=restricted-use stock(TEXT→CAST)",
    "MARM":   "Material UNITS OF MEASURE. matnr=material, meinh=alt UOM, umren=numerator, umrez=denominator, brgew=gross weight(TEXT→CAST), volum=volume(TEXT→CAST)",
    "MBEW":   "Material VALUATION. matnr=material, bwkey=valuation area, bwtar=valuation type, lbkum=total stock(TEXT→CAST), salk3=total stock value(TEXT→CAST), stprs=standard price(TEXT→CAST), verpr=moving avg price(TEXT→CAST), vprsv='S'=standard/'V'=moving avg",
    "MBEWH":  "Material valuation HISTORY. same as MBEW with period data",
    "MCHB":   "Batch STOCKS. matnr=material, werks=plant, lgort=storage loc, charg=batch, clabs=unrestricted stock",
    "MEAN":   "International article numbers (EAN/barcode). matnr=material, meinh=UOM, ean11=EAN code",
    "MKPF":   "Material document HEADER. mblnr=doc#, mjahr=year, bldat=doc date, budat=posting date",
    "MLAN":   "Tax classification for material. matnr=material, aland=departure country, taxkm=tax category",
    "MSLB":   "Special stocks at vendor. matnr=material, lifnr=vendor, werks=plant",
    "MVKE":   "Material SALES DATA. matnr=material, vkorg=sales org, vtweg=dist channel, dpppp=material pricing group, kondm=price group",
    "STKO":   "BOM HEADER. stlnr=BOM#, stlal=alternative, matnr=material, werks=plant, stlan=BOM usage",
    "STPO":   "BOM ITEMS. stlnr=BOM#, stlal=alternative, posnr=item#, idnrk=component material, menge=qty(TEXT→CAST), meins=UOM",
    "CABN":   "Characteristic definition. atinn=internal char#, atnam=char name, atfor=data type, atmlt=char length",
    "AUSP":   "Characteristic values. objek=object#, atinn=char#, atwrt=value, atflv=numeric from, atflb=numeric to",
    "KLAH":   "Class header. klart=class type, class=class name, spras=language",
    # Zodiac App Tables
    "invoice_business_data": "V1 invoice processing records. tracking_id=tracking ID, customer_name, customer_country, supplier_name, supplier_id, failure_reason, current_stage (pending/processing/completed/failed), total_amount NUMERIC, tax_amount NUMERIC, currency, invoice_number, industry, industry_confidence NUMERIC, invoice_date DATE, uploaded_at TIMESTAMP",
    "invoice_v2_business_data": "V2 extracted invoice data. validated_invoice_id FK, customer_name, customer_country, supplier_name, total_amount NUMERIC, tax_amount NUMERIC, currency, invoice_date DATE, fiscal_year INT, fiscal_quarter INT, season TEXT, industry TEXT, industry_confidence NUMERIC, user_id",
    "invoice_v2_documents": "V2 uploaded invoice documents. id UUID, filename, source, validation_status ('pending'/'valid'/'invalid'/'corrected'), uploaded_at TIMESTAMP, uploaded_by",
    "invoice_v2_validated": "V2 validation results. document_id FK→invoice_v2_documents.id, status ('valid'/'invalid'/'corrected'), validation_errors JSONB, missing_fields JSONB, correction_applied BOOL, validated_at TIMESTAMP",
    "v2_invoice_documents": "V2 document tracking. tracking_id, user_id, filename, xml_path, validation_status, uploaded_at TIMESTAMP, deleted_at",
    "v2_validated_invoices": "V2 validated invoice output. document_id FK, status, validation_errors JSONB, validation_notes, correction_applied BOOL, correction_cache_id, validated_at TIMESTAMP",
    "converted_invoices": "Conversion results. validated_invoice_id FK, customer_id, target_format (UBL/EDIFACT/X12/PEPPOL), conversion_status ('pending'/'success'/'failed'), conversion_notes TEXT, converted_at TIMESTAMP, validation_overridden BOOL",
    "zodiac_invoice_failed_edi": "Failed EDI invoice processing. tracking_id, user_id, invoice_number, uploaded_at, xml_validation_pass BOOL, xml_convert_message TEXT, edi_convert_pass BOOL, edi_convert_message TEXT, processing_steps_error TEXT, processing_steps JSONB, request_type, target_file_format",
    "zodiac_invoice_success_edi": "Successful EDI invoices. tracking_id, user_id, invoice_number, uploaded_at, xml_validation_pass BOOL, edi_convert_pass BOOL, external_status TEXT, external_message TEXT, processing_steps JSONB, target_file_format",
    "sat_documents": "SAT/CFDI inbound documents (Mexico tax). id, user_id, portal_ref_id, cfdi_uuid, doc_type (INVOICE/CREDIT_NOTE/PAYMENT), supplier_rfc, supplier_name, receiver_rfc, receiver_name, serie, folio, fecha TIMESTAMP (invoice date from XML), subtotal NUMERIC, total NUMERIC, moneda (currency code), tipo_cambio NUMERIC, forma_pago, metodo_pago, related_cfdi_uuid, status (VALIDATED/FAILED), source (admin/supplier), received_at TIMESTAMP (when document arrived in the portal - USE THIS for 'this week/month/recent' queries), fiscal_year INT, fiscal_period INT. IMPORTANT: always use received_at for date-based filtering, NOT fecha.",
    "sat_simple_merged": "SAT documents merged for SAP posting. vendor_rfc, vendor_name, fiscal_year INT, fiscal_period INT, document_count INT, total_amount NUMERIC, currency, sent_to_sap BOOL, sap_document_number, sent_to_sap_at TIMESTAMP",
    "sat_canonical_merged": "Canonical SAT merges with GL accounts. company_code, vendor_rfc, vendor_name, total_invoices INT, total_credits INT, net_amount NUMERIC, currency, sap_gl_account, status, sap_document_number, sent_to_sap_at TIMESTAMP",
    "sat_duplicate_checks": "UUID/folio duplicate detection. cfdi_uuid, sat_document_id, user_id, supplier_id, document_type, first_received_at TIMESTAMP",
    "sat_processing_logs": "SAT processing event log. sat_document_id, user_id, action, status, message, created_at TIMESTAMP",
    "sat_sap_account_mapping": "SAT product code → SAP GL account. clave_prod_serv, sap_gl_account, description, is_active BOOL, is_default BOOL",
    "sat_supplier_account_mapping": "Supplier RFC → SAP GL account. supplier_rfc, sap_gl_account, is_active BOOL, is_default BOOL, company_code, fiscal_year, currency, opening_balance NUMERIC, credit_amount NUMERIC, debit_amount NUMERIC, closing_balance NUMERIC",
    "sat_company_mappings": "Company code mappings. company_code, company_name, rfc, is_active BOOL",
    "customers": "Registered customer accounts. customer_id TEXT, format TEXT, api_address TEXT, validation_rules JSONB, created_at TIMESTAMP",
    "supplier_tokens": "Supplier API authentication tokens. supplier_rfc, supplier_name, is_active BOOL, expires_at TIMESTAMP, last_used_at TIMESTAMP, created_at TIMESTAMP, created_by, notes TEXT",
    "customer_tokens": "Customer API authentication tokens. customer_id, is_active BOOL, expires_at TIMESTAMP, last_used_at TIMESTAMP",
    "customer_receiver_rfc": "Customer → RFC mappings for SAT delivery. customer_id, receiver_rfc",
    "customer_delivery_settings": "Customer EDI delivery configuration. customer_id, settings JSONB",
    "customer_certificates": "Customer digital certificates. customer_id, certificate_data, expiry_date, is_active BOOL",
    "certificate_renewal_requests": "Certificate renewal tracking. customer_id, requested_at, status",
    "certificate_revocation_list": "Revoked certificates log. serial_number, revoked_at, reason",
    "user_customers": "User ↔ customer access mapping. user_id, customer_id",
    "zodiac_users": "Zodiac user accounts. email, name, role, is_active BOOL, created_at",
    "zodiac_customers": "Zodiac customer records. customer_id, name, country, validation_rules JSONB",
    "ai_query_memory": "Approved Q→SQL pairs for reuse. question_pattern, sql_query TEXT, source ('chatgpt'/'user'/'assistant_sql'), use_count INT, approved_by_user_id, created_at",
    "ai_analysis_memory": "AI conversation memory per user. user_id, last_user_query, last_sql, last_rows_json JSONB, last_reply, updated_at",
    "ai_chat_threads": "AI chat conversation threads. thread_id TEXT, user_id, title, turn_count INT, last_active_at TIMESTAMP",
    "ai_chat_turns": "Individual AI conversation turns. thread_id, turn_index INT, role ('user'/'assistant'), content TEXT, sql_executed TEXT, result_rows JSONB, key_metrics JSONB, warnings TEXT, charts JSONB",
    "ai_learned_patterns": "AI learned query patterns. pattern TEXT, sql TEXT, success_count INT",
    "ai_query_embeddings": "AI query vector embeddings. question TEXT, embedding JSONB",
    "ai_training_data": "AI training examples. question TEXT, sql TEXT, result_summary TEXT",
    "correction_cache": "V1 correction rules cache. field_name, original_value, corrected_value, confidence NUMERIC",
    "invoice_v2_correction_cache": "V2 correction rules cache. field_name, original_value, corrected_value TEXT, applied_count INT",
    "v2_correction_cache": "V2 correction cache. field_name, field_value TEXT, corrected_value TEXT, customer_id",
    "sat_sap_account_mapping": "SAT product codes to SAP GL accounts. clave_prod_serv, sap_gl_account, code_group, description, is_active BOOL",
}


@lru_cache(maxsize=1)
def _build_schema_prompt() -> str:
    """
    Build a complete schema prompt for GPT — all 121 tables with all their columns and types.
    Shows which columns need CAST for numeric aggregates.
    Cached for process lifetime (same source as `_load_schema`).
    """
    schema = _load_schema()
    lines: List[str] = []

    sap_tables = sorted(t for t in schema if t and t[0].isupper())
    app_tables = sorted(t for t in schema if t and (t[0].islower() or t[0].isdigit()))

    lines.append("=== FULL DATABASE SCHEMA (121 TABLES) ===\n")
    lines.append("── APP TABLES (Zodiac app data, lowercase, no quoting needed) ──")

    for tbl in app_tables:
        cols = schema[tbl]
        ctx = _TABLE_CONTEXT.get(tbl, "")
        col_parts = []
        for c in cols:
            dt = c["type"]
            marker = ""
            if dt in ("numeric", "double precision", "integer", "bigint"):
                marker = "ℕ"  # native numeric
            elif dt in ("timestamp with time zone", "timestamp without time zone"):
                marker = "📅"
            elif dt == "date":
                marker = "📅"
            elif dt == "boolean":
                marker = "🔘"
            elif dt in ("jsonb", "json"):
                marker = "📋"
            elif dt == "uuid":
                marker = "🔑"
            col_parts.append(f"{c['col']}{marker}" if marker else c["col"])
        col_str = ", ".join(col_parts[:60]) + ("..." if len(cols) > 60 else "")
        ctx_str = f"  # {ctx}" if ctx else ""
        lines.append(f"  {tbl} [{len(cols)} cols]: {col_str}{ctx_str}")

    lines.append("\n── SAP TABLES (ERP data, MUST double-quote: \"TABLE\".\"col\") ──")

    for tbl in sap_tables:
        cols = schema[tbl]
        ctx = _TABLE_CONTEXT.get(tbl, "")
        col_parts = []
        for c in cols:
            name, dt = c["col"], c["type"]
            if name in _NUMERIC_TEXT_COLS and dt == "text":
                col_parts.append(f"{name}*")  # * = needs CAST
            elif dt in ("numeric", "double precision", "integer", "bigint"):
                col_parts.append(f"{name}ℕ")
            else:
                col_parts.append(name)
        col_str = ", ".join(col_parts[:60]) + ("..." if len(cols) > 60 else "")
        ctx_str = f"  # {ctx}" if ctx else ""
        lines.append(f"  {tbl} [{len(cols)} cols]: {col_str}{ctx_str}")

    lines.append("\n(* = TEXT column that needs CAST(NULLIF(TRIM(CAST(col AS TEXT)),'') AS NUMERIC) in SUM/AVG/MIN/MAX)")
    lines.append("(ℕ = native numeric, 📅 = date/timestamp, 🔘 = boolean, 📋 = JSONB, 🔑 = UUID)")

    return "\n".join(lines)


# ─── Universal system prompt ───────────────────────────────────────────────────

_SYSTEM_PROMPT_CORE = """You are an expert PostgreSQL analyst for a Zodiac invoice processing + SAP ERP system.
You have access to ALL 121 database tables. Generate accurate, executable SQL for any question.

══════════════════════════════════════════════════════
SECTION 1: CRITICAL POSTGRESQL RULES
══════════════════════════════════════════════════════

1. SAP TABLE QUOTING (mandatory):
   FROM "VBRK" AS k   -- uppercase SAP tables MUST be double-quoted
   FROM "vbrp" AS p   -- vbrp is SAP billing items stored lowercase, still needs quotes
   FROM invoice_v2_business_data  -- lowercase app tables: NO quotes

2. SAP NUMERIC COLUMNS (stored as TEXT — ALWAYS CAST in SUM/AVG/MIN/MAX):
   SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC))
   Columns marked * in schema need this cast. NEVER use bare SUM(col) on TEXT columns.

3. SAP DATE COLUMNS (stored as TEXT 'YYYYMMDD' — NEVER cast to DATE):
   Year filter:    SUBSTRING(TRIM(k."fkdat"), 1, 4) = '2001'
   Month filter:   SUBSTRING(TRIM(b."budat"), 1, 6) = '202401'
   Overdue check:  TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
   Last 30 days:   TRIM(b."budat") >= TO_CHAR(CURRENT_DATE - INTERVAL '30 days', 'YYYYMMDD')
   Always: TRIM() before comparing, check TRIM(col) != '' to exclude empty dates

4. HAVING CLAUSE: NEVER use SELECT aliases in HAVING — repeat the full expression:
   WRONG:  HAVING total_amount > 0
   RIGHT:  HAVING SUM(CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)),'') AS NUMERIC)) > 0

5. APP TABLE DATES (real PostgreSQL date/timestamp types — use normally):
   WHERE uploaded_at >= NOW() - INTERVAL '30 days'
   WHERE invoice_date >= CURRENT_DATE - INTERVAL '90 days'

══════════════════════════════════════════════════════
SECTION 2: KEY TABLE RELATIONSHIPS (JOINS)
══════════════════════════════════════════════════════

Sales & Billing:
  "VBRK" → "vbrp":  k.vbeln = p.vbeln  (billing header → billing items)
  "vbrp" → "VBAK":  p.vgbel = a.vbeln  (billing item → sales order header)
  "vbrp" → "VBAP":  p.vgbel = a.vbeln AND p.vgpos = a.posnr  (billing item → SO item)
  "VBAK" → "VBAP":  a.vbeln = p.vbeln  (sales order header → items)
  "VBAK" → "KNA1":  a.kunnr = c.kunnr  (sales order → customer)
  "VBRK" → "KNA1":  k.kunag = c.kunnr  (billing header → customer, kunag=payer)
  "VBFA": vbelv=source doc, vbeln=target doc (document flow)

Delivery:
  "LIKP" → "LIPS":  d.vbeln = i.vbeln  (delivery header → items)
  "LIPS" → "VBAP":  i.vgbel = a.vbeln AND i.vgpos = a.posnr  (delivery → SO item)

Purchasing:
  "EKKO" → "EKPO":  k.ebeln = p.ebeln  (PO header → items)
  "EKKO" → "LFA1":  k.lifnr = v.lifnr  (PO → vendor)
  "RBKP" → "RSEG":  r.belnr = s.belnr AND r.gjahr = s.gjahr  (invoice receipt header → items)
  "RSEG" → "EKPO":  s.ebeln = p.ebeln AND s.ebelp = p.ebelp  (invoice item → PO item)

Finance:
  "BKPF" → "BSEG":  b.belnr = s.belnr AND b.bukrs = s.bukrs AND b.gjahr = s.gjahr
  "BSEG" → "KNA1":  s.kunnr = c.kunnr  (only customer postings)
  "BSEG" → "LFA1":  s.lifnr = v.lifnr  (only vendor postings)
  "FAGLFLEXA" → "CEPC":  f.prctr = c.prctr  (GL → profit center master)
  "FAGLFLEXA" → "CSKS":  f.racct = s.kostl  (GL → cost center via GL account)

Material:
  "MARA" → "MAKT":  m.matnr = t.matnr AND t.spras = 'E'  (material → English description)
  "MARA" → "MARC":  m.matnr = c.matnr  (general → plant data)
  "MARC" → "MARD":  c.matnr = d.matnr AND c.werks = d.werks  (plant data → stock)
  "MARA" → "MBEW":  m.matnr = v.matnr  (material → valuation)
  "MARA" → "MEAN":  m.matnr = e.matnr  (EAN / units of measure variants)
  "MARA" → "MVKE":  m.matnr = v.matnr  (sales data for material — join v.vkorg = billing vbrp.vkorg when needed)

Product drill-down from billing (join order — transaction first, then masters):
  "vbrp" p → "MARA" m ON p.matnr = m.matnr
  → "MAKT" t ON m.matnr = t.matnr AND t.spras = 'E'
  → "MEAN" e ON m.matnr = e.matnr (optional; multiple rows per material possible)
  → "MVKE" vk ON m.matnr = vk.matnr AND vk.vkorg = TRIM(p.vkorg) AND vk.vtweg = TRIM(p.vtweg) when those exist on line
  → "MARC" mc ON m.matnr = mc.matnr AND mc.werks = TRIM(p.werks)  (plant-specific material)

Master vs transaction:
  Transaction / fact tables hold document numbers, dates, quantities, amounts (VBRK, vbrp, VBAK, VBAP, EKKO, EKPO, etc.).
  Master tables hold attributes (KNA1 customer, MARA material, MAKT text, MARC plant params, MVKE sales views).
  Always join facts → masters on business keys (VBELN, MATNR, KUNNR); never invent keys between unrelated masters.

Margin / profitability — purchasing ↔ sales BRIDGE (cross-domain, no document link exists):
  "EKPO" → "vbrp":  ep.matnr = p.matnr   (what we PAID a supplier for a material ↔ what we CHARGED a
                                            customer for the SAME material. MATNR is the ONLY common key —
                                            there is no PO-to-billing-document link. Aggregate each side
                                            separately first, THEN join the aggregates on matnr — joining the
                                            raw line-item tables directly multiplies rows, since one material
                                            can appear on many POs and many billing lines.)
  This bridge answers ANY "margin / profit / what we buy vs sell / supplier cost vs customer price"
  question, for any material, country, region, sales org, plant, product group, or time period named
  in the question — the data exists in EKPO + vbrp/VBRK, it just needs this join. Do not say it's
  uncomputable; see Section 4's margin pattern for the full generalized query.

══════════════════════════════════════════════════════
SECTION 3: BUSINESS RULES & KEYWORD MAPPING
══════════════════════════════════════════════════════

INVOICE COUNT (Andy's issue: count invoices NOT line items):
  ✓ GROUP BY "VBRK".vbeln  (one row per invoice document)
  ✗ GROUP BY "vbrp".vbeln, "vbrp".posnr  (this counts line items, not invoices)
  Multiple line items per invoice is NORMAL — always aggregate at header level for invoice counts

INVOICE AMOUNT / ZERO OR NEGATIVE **BILLING DOCUMENT** (header vs line — critical):
  - For "invoice value", "billing document total", "zero-value invoices", "negative invoices",
    "non-zero invoice", or any question about the **document** total: use **"VBRK"."netwr"** first
    (cast safely). A document is NOT "zero amount" just because some "vbrp" lines have netwr = 0;
    line items are product-level; the header total is authoritative for the invoice.
  - Use **"vbrp"."netwr"** only for line-item / product-level amounts, margins by material, etc.
  - For "negative **sales** at line level" (credit memo lines): filter on **"vbrp"** rows.
  - Do **not** add **T016T** (industry) unless the user explicitly says industry, sector, or brsch.

TRANSACTION vs MASTER DATA:
  - **Transaction / facts** (amounts, quantities, dates of business events): "VBRK", "vbrp", "EKKO", "EKPO",
    "RBKP", "RSEG", "BKPF", "BSEG", "FAGLFLEXA", etc.
  - **Master / attributes** (names, descriptions, plant params, EAN): "KNA1", "MARA", "MAKT", "MARC", "MVKE", "MEAN", etc.
  - Rule: compute money from transaction tables; **LEFT JOIN** master tables for labels. For deep product
    analysis: start from **"vbrp"** (+ "VBRK" for filters), join **MARA** on matnr, **MAKT** on matnr AND spras='E',
    **MARC** on matnr and werks (use **"vbrp"."werks"** when present), **MVKE** on matnr + vkorg/vtweg/spart
    (align with **"VBRK"** sales org fields when available), **MEAN** on matnr (and meinh if needed).

CUSTOMER NUMBERS:
  "VBRK".kunag = payer/customer (use this for customer billing analysis)
  "VBAK".kunnr = sold-to customer
  Join to "KNA1".kunnr for customer name

STATUS / FLAG FIELDS (TEXT, not BOOLEAN in SAP):
  EKPO.elikz = 'X' means delivery complete ('' = still open)
  EKPO.loekz = 'L' means deleted ('' = active)
  EKKO.loekz = 'L' means PO deleted
  BKPF.stblg = '' or '0000000000' means NOT reversed

OVERDUE PURCHASE ORDERS:
  Use EKPO.agdat = expected delivery date (TEXT 'YYYYMMDD')
  WHERE TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
    AND TRIM(COALESCE(p."elikz",'')) = ''   -- not fully delivered
    AND TRIM(COALESCE(p."loekz",'')) = ''   -- not deleted
    AND TRIM(COALESCE(k."loekz",'')) = ''   -- PO not deleted

REVERSED DOCUMENTS:
  WHERE TRIM(COALESCE(b."stblg",'')) NOT IN ('','0000000000')  -- IS reversed
  WHERE TRIM(COALESCE(b."stblg",'')) IN ('','0000000000')      -- NOT reversed

SAT DOCUMENTS NOT YET SENT TO SAP:
  FROM sat_simple_merged WHERE sent_to_sap = false

KEYWORD → TABLES MAPPING:
  Do NOT treat this as a table-selection authority. Keywords are retrieval
  signals only. Select tables from schema intelligence + coverage validation.
  Never answer by mapping "sales" or "customer" to a fixed SAP table list.

══════════════════════════════════════════════════════
SECTION 3b: ADDITIONAL SAP ACCURACY RULES (mandatory)
══════════════════════════════════════════════════════

FISCAL-YEAR COMPOUND KEYS (critical — belnr alone is NEVER unique across years):
  RBKP + RSEG:    JOIN ON r."belnr" = s."belnr" AND r."gjahr" = s."gjahr"
  BKPF + BSEG:    JOIN ON b."belnr" = s."belnr" AND b."bukrs" = s."bukrs" AND b."gjahr" = s."gjahr"
  Missing gjahr or bukrs silently returns cross-year / cross-company matches — ALWAYS include all keys.

TEXT/DESCRIPTION TABLE LANGUAGE FILTER (schema-aware — never invent columns):
  MAKT: if spras exists in schema, join with AND t."spras" = 'E'
  T016T: if spras exists in schema, filter spras='E'; if spras does NOT exist (this DB: brsch/brtxt only), join ONLY on brsch — do NOT add spras
  CSKT: if spras exists, join with AND s."spras" = 'E'
  Requiring a non-existent spras column causes schema validation failure. Schema columns are the source of truth.

ACTIVE / OPEN RECORD FILTERS (deletion/block flags):
  Open POs:       TRIM(COALESCE(k."loekz",'')) = '' (EKKO) AND TRIM(COALESCE(p."loekz",'')) = '' (EKPO)
  Open PO items:  TRIM(COALESCE(p."elikz",'')) = '' (delivery not complete)
  Active vendors: TRIM(COALESCE(v."loevm",'')) = '' (LFA1)
  Active customers: TRIM(COALESCE(c."sperr",'')) = '' (KNA1)
  Active materials: TRIM(COALESCE(m."lvorm",'')) = '' (MARA)
  Always apply these when the question says "active", "open", "outstanding", "current", or "not deleted".

QUANTITY UNIT-OF-MEASURE CONSISTENCY:
  SAP quantities (menge, fkimg, kwmeng, lfimg) are stored in the UOM set in meins/gmein.
  NEVER SUM quantities without ensuring a single UOM scope:
    ✓ GROUP BY p."meins"  (show totals per UOM)
    ✓ WHERE p."meins" = 'EA'  (filter to one UOM)
    ✗ SUM(menge) across mixed UOMs — this is mathematically meaningless

SAP FISCAL PERIOD (FAGLFLEXA.poper):
  poper '001'–'012' = regular posting periods (Jan–Dec for calendar-year companies)
  poper '013'–'016' = period-end adjustment periods (balance sheet adjustments)
  For operational cost/revenue queries, filter WHERE f."poper" BETWEEN '001' AND '012'
  to exclude year-end adjustment postings unless explicitly asked.

PURCHASING PRICE PER UNIT (EINE / EKPO):
  EINE.netpr and EKPO.netpr are price per PEINH units, NOT per 1 unit.
  True unit price = CAST(NULLIF(TRIM(CAST(netpr AS TEXT)),'') AS NUMERIC)
                   / NULLIF(CAST(NULLIF(TRIM(CAST(peinh AS TEXT)),'') AS NUMERIC), 0)
  Always divide by peinh when computing unit prices from purchasing info records.

MARGIN / PROFIT-BY-PRODUCT QUESTIONS (mandatory approach):
  Questions like "margin per product", "profit by material", "what we paid suppliers vs charged
  customers", "buy for X sell for Y, what's the difference" are ALWAYS computable from EKPO (cost)
  + vbrp/VBRK (revenue) joined on matnr — see Section 4's margin pattern. Never respond that this
  needs data that isn't available; the join is the only thing required. To add a dimension the user
  names (country, region, sales org, plant, product group, time period, one specific product):
    - Customer/sales-side filters (country, region, sales org) → join through KNA1 (k.kunag = c.kunnr)
      or use VBRK.vkorg directly; add the column to GROUP BY in the sales CTE.
    - Supplier/purchase-side filters (vendor, vendor country, plant) → join through LFA1 (ek.lifnr =
      v.lifnr) or EKPO.werks; add to GROUP BY in the purchases CTE.
    - Time period → SUBSTRING(TRIM(k."fkdat"),1,4) for sales year, SUBSTRING(TRIM(ek."bedat"),1,4) for
      purchase year; filter/group both CTEs independently since sales and purchase dates differ.
    - One specific product → if the user gives the exact matnr code, filter WHERE matnr = '...' in
      both CTEs. If the user names a product colloquially (a model name/description, not the literal
      matnr key), do NOT assume that text equals matnr — first resolve it via
      MAKT.maktx ILIKE '%name%' (spras='E') to get the real matnr, then filter both CTEs on that
      resolved matnr (e.g. WHERE matnr IN (SELECT matnr FROM "MAKT" WHERE maktx ILIKE '%name%' AND
      spras='E')). Matching the literal name string against matnr directly will silently return 0
      rows on one side and produce a misleading 100% (or 0%) margin.
  Sales and purchase amounts may be in different currencies (VBRK.waerk vs EKKO.waers) — include both
  currency columns in the output so the user can see if they differ; do not silently combine mismatched
  currencies into one number.
  EKPO is the ONLY correct cost basis for "margin"/"profit" — it is what we actually paid suppliers.
  Do NOT use CKIS for margin/profit questions: CKIS holds planned/standard cost estimates (not actual
  purchase price), and CKIS.matnr is blank on ~70% of rows (the real material link runs through
  CKIS.kalnr → KEKO.matnr, which CKIS alone does not give you) — joining vbrp.matnr = CKIS.matnr
  directly silently drops most of the data. Only use CKIS if the user explicitly asks for "standard
  cost" rather than plain "margin"/"profit"/"profit margin".

══════════════════════════════════════════════════════
SECTION 4: PROVEN READY-TO-USE SQL PATTERNS
══════════════════════════════════════════════════════

-- Top customers by billed amount (INVOICE LEVEL, not item level) for a specific year:
SELECT k."vbeln" AS invoice_doc, k."kunag" AS customer_id, c."name1" AS customer_name,
       k."waerk" AS currency, k."fkdat" AS billing_date,
       SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)),'') AS NUMERIC)) AS total_billed,
       COUNT(DISTINCT k."vbeln") AS invoice_count
FROM "VBRK" k
JOIN "vbrp" p ON k."vbeln" = p."vbeln"
LEFT JOIN "KNA1" c ON k."kunag" = c."kunnr"
WHERE SUBSTRING(TRIM(k."fkdat"),1,4) = '2001'
GROUP BY k."vbeln", k."kunag", c."name1", k."waerk", k."fkdat"
ORDER BY total_billed DESC LIMIT 20;

-- Margin/profit by product (what we paid suppliers vs what we charged customers, same material):
-- GENERALIZE THIS: add country/region/sales-org/plant/product-group/year filters or GROUP BY columns
-- inside the two CTEs as needed for the specific question — aggregate each side first, join last.
WITH sales AS (
  SELECT p."matnr" AS matnr, k."waerk" AS sales_currency,
         SUM(CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)),'') AS NUMERIC)) AS total_sales
  FROM "vbrp" p
  JOIN "VBRK" k ON LPAD(TRIM(p."vbeln"),10,'0') = LPAD(TRIM(k."vbeln"),10,'0')
  WHERE TRIM(COALESCE(p."matnr",'')) <> ''
  GROUP BY p."matnr", k."waerk"
),
purchases AS (
  SELECT ep."matnr" AS matnr, ek."waers" AS purchase_currency,
         SUM(CAST(NULLIF(TRIM(CAST(ep."netwr" AS TEXT)),'') AS NUMERIC)) AS total_purchase_cost
  FROM "EKPO" ep
  LEFT JOIN "EKKO" ek ON ep."ebeln" = ek."ebeln"
  WHERE TRIM(COALESCE(ep."matnr",'')) <> '' AND TRIM(COALESCE(ep."netwr",'')) <> ''
  GROUP BY ep."matnr", ek."waers"
)
SELECT m."matnr" AS material_id, t."maktx" AS material_name,
       s.total_sales, s.sales_currency,
       p.total_purchase_cost, p.purchase_currency,
       (s.total_sales - p.total_purchase_cost) AS margin,
       CASE WHEN s.total_sales > 0
            THEN ROUND(100.0 * (s.total_sales - p.total_purchase_cost) / s.total_sales, 2)
       END AS margin_pct
FROM sales s
JOIN purchases p ON s."matnr" = p."matnr"
LEFT JOIN "MARA" m ON s."matnr" = m."matnr"
LEFT JOIN "MAKT" t ON m."matnr" = t."matnr" AND t."spras" = 'E'
ORDER BY margin DESC LIMIT 200;

-- Overdue purchase orders:
SELECT k."ebeln" AS po_number, k."lifnr" AS vendor_id, l."name1" AS vendor_name,
       p."ebelp" AS item, p."matnr" AS material, p."txz01" AS description,
       CAST(NULLIF(TRIM(CAST(p."menge" AS TEXT)),'') AS NUMERIC) AS ordered_qty,
       p."meins" AS uom, p."agdat" AS expected_delivery, p."werks" AS plant
FROM "EKKO" k
JOIN "EKPO" p ON k."ebeln" = p."ebeln"
LEFT JOIN "LFA1" l ON k."lifnr" = l."lifnr"
WHERE TRIM(COALESCE(p."agdat",'')) > '19000101'
  AND TRIM(p."agdat") < TO_CHAR(CURRENT_DATE, 'YYYYMMDD')
  AND TRIM(COALESCE(p."elikz",'')) = ''
  AND TRIM(COALESCE(p."loekz",'')) = ''
  AND TRIM(COALESCE(k."loekz",'')) = ''
ORDER BY p."agdat" ASC LIMIT 100;

-- Potential document reversals:
SELECT b."belnr", b."bukrs", b."gjahr", b."budat", b."blart",
       b."stblg" AS reversal_doc, b."stjah" AS reversal_year, b."waers",
       b."bktxt" AS header_text
FROM "BKPF" b
WHERE TRIM(COALESCE(b."stblg",'')) NOT IN ('','0000000000')
ORDER BY b."budat" DESC LIMIT 100;

-- Compare ordered vs billed quantity at item level:
SELECT p."vbeln" AS billing_doc, p."posnr" AS billing_item,
       p."matnr" AS material,
       CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)),'') AS NUMERIC) AS billed_qty,
       CAST(NULLIF(TRIM(CAST(a."kwmeng" AS TEXT)),'') AS NUMERIC) AS so_ordered_qty,
       p."meins" AS uom
FROM "vbrp" p
LEFT JOIN "VBAP" a ON p."vgbel" = a."vbeln" AND p."vgpos" = a."posnr"
ORDER BY p."vbeln", p."posnr" LIMIT 100;

-- Average invoice amounts by currency (Zodiac app tables):
SELECT currency,
       AVG(total_amount) AS avg_total_amount,
       AVG(tax_amount) AS avg_tax_amount,
       COUNT(*) AS invoice_count
FROM invoice_v2_business_data
WHERE currency IS NOT NULL AND currency <> ''
GROUP BY currency
ORDER BY avg_total_amount DESC;

-- Profit center GL cost (with proper TEXT cast for hsl):
SELECT f."prctr" AS profit_center, c."name1" AS pc_name,
       f."rtcur" AS currency,
       SUM(CAST(NULLIF(TRIM(CAST(f."hsl" AS TEXT)),'') AS NUMERIC)) AS total_amount
FROM "FAGLFLEXA" f
LEFT JOIN "CEPC" c ON f."prctr" = c."prctr"
WHERE TRIM(COALESCE(f."prctr",'')) <> ''
GROUP BY f."prctr", c."name1", f."rtcur"
HAVING SUM(CAST(NULLIF(TRIM(CAST(f."hsl" AS TEXT)),'') AS NUMERIC)) > 0
ORDER BY total_amount DESC LIMIT 20;

-- SAT documents not sent to SAP:
SELECT id, vendor_rfc, vendor_name, fiscal_year, fiscal_period,
       document_count, total_amount, currency, created_at
FROM sat_simple_merged
WHERE sent_to_sap = false
ORDER BY created_at DESC LIMIT 100;

-- Zero-value and negative billing documents (ALWAYS filter on VBRK.netwr — header is authoritative):
-- RULE: An invoice is zero/negative ONLY when VBRK.netwr = 0 or < 0.
-- Do NOT derive from vbrp: a single vbrp line item with netwr=0 does NOT mean the invoice is zero.
SELECT k."vbeln" AS invoice_doc, k."kunag" AS customer_id, c."name1" AS customer_name,
       k."fkdat" AS billing_date, k."waerk" AS currency, k."fkart" AS doc_type,
       CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC) AS invoice_total
FROM "VBRK" k
LEFT JOIN "KNA1" c ON LPAD(TRIM(k."kunag"), 10, '0') = LPAD(TRIM(c."kunnr"), 10, '0')
WHERE TRIM(COALESCE(k."netwr", '')) <> ''
  AND CAST(NULLIF(TRIM(CAST(k."netwr" AS TEXT)), '') AS NUMERIC) <= 0
ORDER BY invoice_total ASC, k."fkdat" DESC LIMIT 100;

-- Product drill-down from billing — COMPLETE join hierarchy (vbrp → MARA → MAKT → MEAN → MVKE → MARC):
-- Use this template whenever the question asks for product attributes, product name, description,
-- material group, plant data, EAN/barcode, or sales unit alongside billing amounts.
-- NOTE: MAKT needs spras='E'. MVKE needs vkorg+vtweg alignment. MEAN may have multiple rows per matnr.
SELECT
    p."vbeln" AS billing_doc,
    p."posnr" AS item,
    p."matnr" AS material_id,
    t."maktx" AS material_description,
    m."matkl" AS material_group,
    m."mtart" AS material_type,
    m."meins" AS base_uom,
    CAST(NULLIF(TRIM(CAST(m."brgew" AS TEXT)), '') AS NUMERIC) AS gross_weight,
    e."ean11" AS ean_barcode,
    vk."dpppp" AS material_pricing_group,
    mc."beskz" AS procurement_type,
    mc."werks" AS plant,
    p."waerk" AS currency,
    CAST(NULLIF(TRIM(CAST(p."netwr" AS TEXT)), '') AS NUMERIC) AS line_net_value,
    CAST(NULLIF(TRIM(CAST(p."fkimg" AS TEXT)), '') AS NUMERIC) AS billed_qty,
    p."meins" AS sales_uom
FROM "vbrp" p
LEFT JOIN "MARA" m ON p."matnr" = m."matnr"
LEFT JOIN "MAKT" t ON m."matnr" = t."matnr" AND t."spras" = 'E'
LEFT JOIN "MEAN" e ON m."matnr" = e."matnr" AND e."meinh" = m."meins"
LEFT JOIN "MVKE" vk ON m."matnr" = vk."matnr"
    AND TRIM(vk."vkorg") = TRIM(p."vkorg")
    AND TRIM(vk."vtweg") = TRIM(p."vtweg")
LEFT JOIN "MARC" mc ON m."matnr" = mc."matnr" AND TRIM(mc."werks") = TRIM(p."werks")
ORDER BY p."vbeln", p."posnr" LIMIT 200;

══════════════════════════════════════════════════════
SECTION 5: VERIFIED SAT / ZODIAC INBOUND TEMPLATES
══════════════════════════════════════════════════════
CRITICAL: sat_documents is a PostgreSQL table (NOT SAP). Use standard PostgreSQL syntax.
NEVER use TEXT-cast tricks (NULLIF/TRIM) on sat_documents — all columns use native types.
Always filter by user_id when querying sat_documents (user_id = current user context).
Use received_at (TIMESTAMP) for "received", "this week", "today", "recent" queries.
Use fecha (TIMESTAMP) only for "invoice date" or "document date" questions.

-- All inbound SAT documents (most recent first):
SELECT doc_type, supplier_rfc, supplier_name, moneda AS currency,
       CAST(total AS NUMERIC) AS total_amount, status, source,
       received_at, fecha AS invoice_date
FROM sat_documents
ORDER BY received_at DESC LIMIT 50;

-- SAT documents received this week:
SELECT doc_type, supplier_rfc, supplier_name, moneda AS currency,
       CAST(total AS NUMERIC) AS total_amount, status, received_at
FROM sat_documents
WHERE received_at >= DATE_TRUNC('week', NOW())
ORDER BY received_at DESC LIMIT 50;

-- SAT documents received today:
SELECT doc_type, supplier_rfc, supplier_name, moneda AS currency,
       CAST(total AS NUMERIC) AS total_amount, status, received_at
FROM sat_documents
WHERE received_at >= CURRENT_DATE
ORDER BY received_at DESC LIMIT 50;

-- SAT documents by type (count and total amount):
SELECT doc_type,
       COUNT(*) AS document_count,
       SUM(CASE WHEN total ~ '^[0-9.]+$' THEN CAST(total AS NUMERIC) ELSE 0 END) AS total_amount,
       moneda AS currency
FROM sat_documents
GROUP BY doc_type, moneda
ORDER BY document_count DESC;

-- Top suppliers by inbound document count:
SELECT supplier_rfc, supplier_name,
       COUNT(*) AS total_docs,
       SUM(CASE WHEN total ~ '^[0-9.]+$' THEN CAST(total AS NUMERIC) ELSE 0 END) AS total_amount,
       COUNT(CASE WHEN doc_type = 'INVOICE' THEN 1 END) AS invoices,
       COUNT(CASE WHEN doc_type = 'CREDIT_NOTE' THEN 1 END) AS credit_notes,
       COUNT(CASE WHEN doc_type = 'PAYMENT' THEN 1 END) AS payments
FROM sat_documents
GROUP BY supplier_rfc, supplier_name
ORDER BY total_docs DESC LIMIT 20;

-- SAT documents with validation status summary:
SELECT status, doc_type, COUNT(*) AS count,
       SUM(CASE WHEN total ~ '^[0-9.]+$' THEN CAST(total AS NUMERIC) ELSE 0 END) AS total_amount
FROM sat_documents
GROUP BY status, doc_type
ORDER BY status, doc_type;

-- SAT documents not yet merged (pending processing):
SELECT d.doc_type, d.supplier_rfc, d.supplier_name,
       d.total, d.moneda, d.status, d.received_at
FROM sat_documents d
LEFT JOIN sat_simple_merged m ON d.supplier_rfc = m.vendor_rfc
    AND d.fiscal_year = m.fiscal_year AND d.fiscal_period = m.fiscal_period
WHERE m.id IS NULL
ORDER BY d.received_at DESC LIMIT 50;

-- SAT documents by fiscal period:
SELECT fiscal_year, fiscal_period,
       COUNT(*) AS doc_count,
       COUNT(CASE WHEN doc_type = 'INVOICE' THEN 1 END) AS invoices,
       COUNT(CASE WHEN doc_type = 'CREDIT_NOTE' THEN 1 END) AS credit_notes,
       COUNT(CASE WHEN doc_type = 'PAYMENT' THEN 1 END) AS payments
FROM sat_documents
WHERE fiscal_year IS NOT NULL
GROUP BY fiscal_year, fiscal_period
ORDER BY fiscal_year DESC, fiscal_period DESC;

-- Supplier token status:
SELECT supplier_rfc, supplier_name, is_active,
       created_at, expires_at, last_used_at,
       CASE WHEN expires_at < NOW() THEN 'EXPIRED'
            WHEN is_active = true THEN 'ACTIVE'
            ELSE 'INACTIVE' END AS token_status
FROM supplier_tokens
ORDER BY last_used_at DESC NULLS LAST;

══════════════════════════════════════════════════════
OUTPUT RULE: Return ONLY the SQL inside a ```sql block. NOTHING ELSE.
══════════════════════════════════════════════════════
"""


def _get_openai_key() -> str:
    k = (os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or OPENAI_API_KEY or "").strip()
    if not k:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Set OPEN_AI_KEY (or OPENAI_API_KEY) on the server")
    return k


def _extract_sql(text: str) -> Optional[str]:
    m = re.search(r"```sql\s*([\s\S]+?)\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"(SELECT[\s\S]+?)(;|$)", text, re.IGNORECASE)
    if m:
        return (m.group(1) + ";").strip()
    return None


def _execute_sql(db: Session, sql: str, question: str = "") -> List[Dict[str, Any]]:
    """Apply all sanitizers then execute. Raises on failure (caller handles retry)."""
    from ..services.sql_generation_sanitizers import (
        sanitize_generated_sap_sql,
        prepare_sql_for_sqlalchemy_text_execution,
    )
    from ..services.sap_sql_agent import _quote_catalog_sql_tables
    from ..services.adaptive_trusted_scope import enforce_trusted_user_scope

    sanitized = sanitize_generated_sap_sql(sql, question or None)
    # PostgreSQL stores uppercase SAP tables as quoted identifiers ("VBRK");
    # bare VBRK folds to vbrk and fails. Catalog/deep SQL must be quoted.
    try:
        sanitized = _quote_catalog_sql_tables(sanitized)
    except Exception:
        pass
    # Trusted identity binding for user-scoped app tables (never LLM-chosen).
    bind_params: Dict[str, Any] = {}
    try:
        sanitized, bind_params = enforce_trusted_user_scope(sanitized)
    except PermissionError as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from denied
    safe = prepare_sql_for_sqlalchemy_text_execution(sanitized)
    try:
        db.rollback()
    except Exception:
        pass
    apply_statement_timeout(db)
    from ..services.investigation_budget import current_budget

    budget = current_budget()
    if budget is not None:
        apply_statement_timeout(db, timeout_ms=budget.statement_timeout_ms())
        budget.checkpoint("db_execute")
    result = db.execute(text(safe), bind_params or {})
    rows = result.fetchall()
    keys = list(result.keys())

    import datetime, decimal
    out: List[Dict[str, Any]] = []
    for row in rows:
        d: Dict[str, Any] = {}
        for k, v in zip(keys, row):
            if isinstance(v, (datetime.date, datetime.datetime)):
                d[k] = v.isoformat()
            elif isinstance(v, decimal.Decimal):
                d[k] = float(v)
            else:
                d[k] = v
        out.append(d)
    return out


# ─── Smart chart generation ────────────────────────────────────────────────

# Column name patterns for axis classification
_DATE_KEYWORDS   = {"date","month","year","period","quarter","week","day","time","at","budat","fkdat","erdat","audat","lfdat","bedat","created","updated","uploaded"}
_LABEL_KEYWORDS  = {"name","customer","vendor","material","product","country","region","currency","code","id","type","group","category","status","plant","org","center","description","text","desc","arktx","ktext","maktx","industry","supplier","format","class","doc","number","phase","stage","rfc","folio","uuid","lifnr","kunnr","matnr","prctr","kostl","hkont"}
_NUMERIC_KEYWORDS= {"amount","value","total","cost","revenue","sales","qty","quantity","count","price","weight","volume","stock","balance","rate","ratio","pct","percent","avg","average","sum","net","gross","tax","billed","paid","spent","profit","margin","labst","netwr","dmbtr","wrbtr","hsl","rmwwr","menge","brgew","ntgew","volum","salk3","stprs"}

CHART_COLORS = [
    "#3b82f6","#10b981","#f59e0b","#ef4444","#8b5cf6",
    "#06b6d4","#f97316","#ec4899","#14b8a6","#a855f7",
    "#eab308","#6366f1","#84cc16","#f43f5e","#0ea5e9",
]


def _col_role(col: str) -> str:
    """
    Classify a column as 'date', 'label', 'numeric', or 'other'.
    Uses word-part matching (split on underscore) to avoid substring false-positives
    (e.g. 'material_id' must NOT match 'at' from DATE_KEYWORDS via substring).
    """
    c = col.lower()
    # Split on underscores and non-alpha to get meaningful word parts
    parts = set(re.split(r'[_\-\s]', c)) | {c}

    # ── Date detection ── (highest priority)
    sap_date_cols = {"budat","fkdat","erdat","audat","lfdat","bedat","cpudt",
                     "aedat","bldat","prdat","agdat","kdatb","kdate","bwbdt"}
    if (c in sap_date_cols
            or c.endswith("_at") or c.endswith("_date") or c.endswith("_time")
            or any(p in {"date","month","year","period","quarter","week","day","time",
                         "budat","fkdat","erdat","audat","lfdat","bedat","cpudt"} for p in parts)):
        return "date"

    label_parts = {"name","customer","vendor","material","product","country","region",
                   "currency","code","id","type","group","category","status","plant","org",
                   "center","description","text","desc","industry","supplier","format",
                   "class","doc","item","line","number","phase","stage","rfc","folio","uuid",
                   "lifnr","kunnr","matnr","prctr","kostl","hkont","waerk","waers",
                   "key","ref","num","no","lang","spras","bukrs","werks","ekorg","ekgrp",
                   "document","header","partner","channel","division","office","area"}

    # Numeric suffixes that win even when a label keyword is also present
    # e.g. vendor_count → "count" suffix → numeric (not label)
    numeric_suffixes = {"count","amount","total","value","qty","quantity","price","cost",
                        "sum","avg","average","net","gross","rate","pct","percent",
                        "balance","revenue","sales","spend","spent","margin","profit",
                        "weight","volume","stock","rows","hits","entries","records"}

    # Split the column name to find the last meaningful word
    word_parts = [p for p in re.split(r'[_\-\s]', c) if p]
    last_part = word_parts[-1] if word_parts else ""
    first_part = word_parts[0] if word_parts else ""

    # ── Numeric: numeric suffix wins over any label prefix ─────────────────
    if last_part in numeric_suffixes or first_part in {"total","avg","average","sum","max","min"}:
        return "numeric"

    # ── Label: any label keyword in parts ──────────────────────────────────
    if any(p in label_parts for p in parts):
        return "label"

    # ── Numeric: any numeric keyword in parts ──────────────────────────────
    numeric_parts = {"amount","value","total","cost","revenue","sales","qty","quantity",
                     "count","price","weight","volume","stock","balance","rate","ratio",
                     "pct","percent","avg","average","sum","net","gross","tax","billed",
                     "paid","spent","profit","margin","netwr","dmbtr","wrbtr","hsl","rmwwr",
                     "menge","brgew","ntgew","volum","salk3","stprs","labst","netpr",
                     "rows","hits","matches","entries","records"}
    if any(p in numeric_parts for p in parts):
        return "numeric"

    return "other"


def _is_numeric_val(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    try:
        from decimal import Decimal
        if isinstance(v, Decimal):
            return True
    except Exception:
        pass
    try:
        float(str(v).replace(",", "").replace(" ", "").strip())
        return True
    except Exception:
        return False


def _column_has_numeric(data: List[Dict[str, Any]], col: str, sample: int = 15) -> bool:
    """True if any of the first `sample` rows has a numeric value for col."""
    for row in data[:sample]:
        if _is_numeric_val(row.get(col)):
            return True
    return False


def _auto_charts(
    question: str,
    sql: str,
    data: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Auto-generate Recharts-compatible chart specs from query results.
    Returns a list of chart dicts (may be empty if no suitable chart).

    Strategy:
      1. Classify every column as date | label | numeric | other
      2. Pick chart type:
         - ≤12 rows + 1 label + 1-3 numeric → pie (if ≤8 rows) OR bar
         - date column + numeric → line/area
         - label column + numeric(s) → horizontal bar / grouped bar
         - 2 numeric series over label → grouped/stacked bar
      3. Return up to 2 charts (primary + secondary if useful)
    """
    if not data or len(data) < 1:
        return []

    cols = list(data[0].keys())
    # Classify columns based on name and actual values across a sample of rows
    # (first-row-only missed product totals when row 0 had NULL NETWR casts).
    date_cols   = [c for c in cols if _col_role(c) == "date"]
    label_cols  = [c for c in cols if _col_role(c) == "label"]
    numeric_cols = [
        c for c in cols
        if _col_role(c) == "numeric" and _column_has_numeric(data, c)
    ]

    # Also detect columns that are actually numeric by value but not by name
    for c in cols:
        if c not in date_cols + label_cols + numeric_cols:
            if _column_has_numeric(data, c) and not isinstance(data[0].get(c), str):
                # Prefer non-string numerics; still allow numeric strings via sample
                numeric_cols.append(c)
            elif c not in date_cols + label_cols + numeric_cols and _column_has_numeric(data, c):
                # Numeric-looking strings (e.g. "1234.56" from some drivers)
                if _col_role(c) != "label":
                    numeric_cols.append(c)

    # Deduplicate while preserving order
    _seen_num: set = set()
    _deduped: List[str] = []
    for c in numeric_cols:
        if c not in _seen_num:
            _seen_num.add(c)
            _deduped.append(c)
    numeric_cols = _deduped

    # Need at least one dimension and one measure
    x_candidates = date_cols or label_cols or [c for c in cols if c not in numeric_cols]
    y_candidates = numeric_cols

    if not x_candidates or not y_candidates:
        return []

    charts: List[Dict[str, Any]] = []
    n_rows = len(data)
    n_numeric = len(y_candidates)
    x_key = x_candidates[0]
    y_keys = y_candidates[:4]  # max 4 series

    # Truncate label for long datasets
    chart_data = data[:50]  # max 50 points on a chart

    # ── Chart type selection ──────────────────────────────────────────────

    has_time = bool(date_cols)

    if n_rows <= 10 and n_numeric == 1 and not has_time:
        # Pie chart — few segments, one value
        q_lower = question.lower()
        use_pie = any(kw in q_lower for kw in ["distribution","share","breakdown","proportion","percent","pie","split","by currency","by country","by region","by type","by status","by category"])
        if use_pie or n_rows <= 6:
            charts.append({
                "chart_type": "pie",
                "title": _chart_title(question, "Distribution"),
                "description": f"Distribution of {y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
                "data": chart_data,
                "name_key": x_key,
                "value_key": y_keys[0],
                "colors": CHART_COLORS,
                "show_legend": True,
            })
            if n_rows > 1:
                # Also add bar as second view
                charts.append({
                    "chart_type": "bar",
                    "title": _chart_title(question, "Bar Chart"),
                    "description": f"{y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
                    "data": chart_data,
                    "x_key": x_key,
                    "y_keys": y_keys,
                    "colors": CHART_COLORS,
                    "show_legend": False,
                    "show_grid": True,
                })
            return charts

    if has_time:
        # Line / area chart for time series
        chart_type = "area" if n_numeric == 1 else "line"
        charts.append({
            "chart_type": chart_type,
            "title": _chart_title(question, "Trend"),
            "description": f"{', '.join(k.replace('_',' ') for k in y_keys)} over time",
            "data": chart_data,
            "x_key": date_cols[0],
            "y_keys": y_keys,
            "colors": CHART_COLORS,
            "show_legend": n_numeric > 1,
            "show_grid": True,
        })
        # Add bar as alternative if not too many points
        if n_rows <= 30 and n_numeric == 1:
            charts.append({
                "chart_type": "bar",
                "title": _chart_title(question, "Bar Chart"),
                "description": f"{y_keys[0].replace('_',' ')} by period",
                "data": chart_data,
                "x_key": date_cols[0],
                "y_keys": y_keys[:1],
                "colors": CHART_COLORS,
                "show_legend": False,
                "show_grid": True,
            })
        return charts

    # Default: bar chart (handles categorical + multi-series)
    is_stacked = any(kw in question.lower() for kw in ["stacked","breakdown","composition","by currency","split by"])
    charts.append({
        "chart_type": "stacked_bar" if (is_stacked and n_numeric > 1) else "bar",
        "title": _chart_title(question, "Chart"),
        "description": f"{', '.join(k.replace('_',' ') for k in y_keys)} by {x_key.replace('_',' ')}",
        "data": chart_data,
        "x_key": x_key,
        "y_keys": y_keys,
        "colors": CHART_COLORS,
        "show_legend": n_numeric > 1,
        "show_grid": True,
        "stacked": is_stacked and n_numeric > 1,
    })

    # Add pie for comparison queries with ≤12 categories
    if n_numeric == 1 and n_rows <= 12 and x_key in label_cols:
        charts.append({
            "chart_type": "pie",
            "title": _chart_title(question, "Distribution"),
            "description": f"Share of {y_keys[0].replace('_',' ')} by {x_key.replace('_',' ')}",
            "data": chart_data,
            "name_key": x_key,
            "value_key": y_keys[0],
            "colors": CHART_COLORS,
            "show_legend": True,
        })

    return charts[:2]  # max 2 charts per query


def _chart_title(question: str, fallback: str) -> str:
    """User-facing chart title — never leak internal continuation prompts."""
    return public_chart_title(question, fallback=fallback or "Results")


def _sql_guardrail_violations(
    question: str,
    sql: str,
    plan: Optional[QueryPlan] = None,
) -> List[str]:
    """
    Hard business guardrails for known accuracy issues.
    If any violation is returned, ask the model to regenerate SQL before executing.

    Intent detection uses the user's real question (and optional QueryPlan), NOT
    instructional boilerplate embedded in follow-up prompts.
    """
    q = _guardrail_intent_text(question, plan).lower()
    s = (sql or "")
    s_lower = s.lower()
    violations: List[str] = []

    # Prefer plan grain / dimensions when available
    if plan is not None and plan.grain == "line":
        asks_line_level = True
    else:
        asks_line_level = any(
            tok in q for tok in ("line item", "line items", "item level", "product level", "by product")
        )
    # Zero/negative invoice rules apply ONLY when the user asks for that exception set.
    # Do NOT treat "billing"+"netwr" alone as zero/negative (false positive on sales ranking).
    asks_zero_negative_invoice = (
        any(tok in q for tok in ("zero", "negative"))
        and any(tok in q for tok in ("invoice", "billing document", "billing", "document"))
        and not asks_line_level
    ) or (
        any(tok in q for tok in ("zero invoice", "negative invoice", "zero-value", "zero value"))
    )
    asks_invoice_doc_value = asks_zero_negative_invoice
    if asks_invoice_doc_value:
        has_vbrk = '"vbrk"' in s_lower
        has_header_netwr = bool(re.search(r'"vbrk"\s*\.\s*"netwr"', s_lower))
        if not (has_vbrk and has_header_netwr):
            violations.append(
                "Invoice/document zero-negative logic must use VBRK.NETWR (header) with cast; "
                "do not rely only on vbrp line netwr. "
                "A billing document is zero/negative ONLY when VBRK.netwr is zero/negative — "
                "some invoices have individual vbrp line items with netwr=0 but the header total is non-zero. "
                "Always filter: WHERE CAST(NULLIF(TRIM(CAST(k.\"netwr\" AS TEXT)), '') AS NUMERIC) <= 0 on VBRK."
            )
        if re.search(r"\bhaving\b[\s\S]{0,220}>\s*0", s_lower):
            violations.append(
                "Query is filtering positive-only with HAVING > 0; for zero/negative invoice checks "
                "you must include zero and/or negative values."
            )
        # Prevent ambiguous netwr usage that commonly shifts logic to line items.
        has_unqualified_netwr = bool(
            re.search(r'(?<![\."a-zA-Z0-9_])netwr(?![\."a-zA-Z0-9_])', s_lower)
        )
        if has_unqualified_netwr and not has_header_netwr:
            violations.append(
                "Invoice-value logic uses ambiguous NETWR reference. Qualify with "
                '"VBRK"."netwr" for document-level checks.'
            )
        # Critical: zero/negative must use WHERE on VBRK.netwr, not GROUP BY / HAVING on vbrp.
        # Grouping vbrp by posnr and summing produces line-item totals, not invoice totals.
        if '"vbrp"' in s_lower and has_header_netwr:
            if re.search(r'\bgroup\s+by\b[\s\S]{0,200}\bposnr\b', s_lower):
                violations.append(
                    "Zero/negative invoice query groups by vbrp.posnr (item level). "
                    "Use VBRK.netwr in the WHERE clause to identify zero/negative invoices at header level; "
                    "do not derive the invoice total by aggregating vbrp rows."
                )
        # Ensure the WHERE clause actually filters zero/negative on VBRK, not just selects it.
        has_vbrk_netwr_filter = bool(
            re.search(
                r'\bwhere\b[\s\S]{0,800}\bcast\s*\([\s\S]{0,120}vbrk[\s\S]{0,40}netwr[\s\S]{0,60}\)\s*(<=|=|<)\s*0',
                s_lower,
            )
        )
        has_vbrk_netwr_having = bool(
            re.search(
                r'\bhaving\b[\s\S]{0,300}\bcast\s*\([\s\S]{0,120}vbrk[\s\S]{0,40}netwr[\s\S]{0,60}\)\s*(<=|=|<)\s*0',
                s_lower,
            )
        )
        if has_vbrk and has_header_netwr and not (has_vbrk_netwr_filter or has_vbrk_netwr_having):
            violations.append(
                "Zero/negative invoice query references VBRK.netwr but does not filter on it in WHERE/HAVING. "
                "Add: WHERE CAST(NULLIF(TRIM(CAST(k.\"netwr\" AS TEXT)), '') AS NUMERIC) <= 0 "
                "to restrict the result set to actual zero/negative billing documents."
            )

    # Generic zero/negative intent safety: do not filter requested exception rows away.
    asks_zero_or_negative = any(tok in q for tok in ("zero", "negative", "credit memo", "exception"))
    if asks_zero_or_negative:
        if re.search(
            r"\b(where|having)\b[\s\S]{0,300}\b(netwr|dmbtr|wrbtr|rmwwr|hsl|ksl|wsl|kwert|kbetr)\b[\s\S]{0,40}>\s*0",
            s_lower,
        ):
            violations.append(
                "Question asks zero/negative/exception values, but SQL filters amounts with > 0 and hides requested rows."
            )
    # Monetary comparisons on SAP text amounts must cast safely before numeric operators.
    if re.search(
        r"\b(where|having)\b[\s\S]{0,400}\b(netwr|dmbtr|wrbtr|rmwwr|hsl|ksl|wsl|kwert|kbetr)\b[\s\S]{0,30}(=|>=|<=|>|<)\s*-?\d",
        s_lower,
    ):
        if "cast(nullif(trim(cast(" not in s_lower:
            violations.append(
                "Monetary comparison appears to use raw text amount; cast to NUMERIC with "
                "CAST(NULLIF(TRIM(CAST(col AS TEXT)), '') AS NUMERIC) before filtering."
            )

    # Accuracy critical: VBRK.GJAHR is unreliable in this dataset (often '0000').
    # Any billing/sales question that mentions a calendar year (or "year") must use fkdat.
    has_calendar_year = bool(re.search(r"\b((?:19|20)\d{2})\b", q))
    asks_year_billing = (
        has_calendar_year
        or any(tok in q for tok in ("year", "fiscal year", "in 20", "in 19"))
    ) and any(tok in q for tok in ("invoice", "billing", "sales", "revenue", "vbrk", "customer", "industry"))
    if (asks_year_billing or has_calendar_year) and (
        re.search(r'"vbrk"\s*\.\s*"gjahr"', s_lower)
        or re.search(r'\b[a-zA-Z_][a-zA-Z0-9_]*\s*\.\s*"gjahr"', s_lower)
        or re.search(r'(?<![a-zA-Z0-9_])gjahr(?![a-zA-Z0-9_])', s_lower)
    ):
        violations.append(
            'Do not use "VBRK"."gjahr" for billing-year filtering (values are unreliable / often 0000). '
            'Use SUBSTRING(TRIM("VBRK"."fkdat"), 1, 4).'
        )

    # R3: default sales/revenue grain is VBRK header — do not silently sum vbrp.netwr.
    asks_header_sales = any(
        tok in q for tok in ("sales", "revenue", "turnover", "highest sales", "lowest sales", "total sales")
    ) or (plan is not None and plan.metric == "sales" and plan.grain != "line")
    asks_line_grain = asks_line_level or any(
        tok in q
        for tok in (
            "line item", "line items", "item level", "product level", "material level",
            "by product", "per product", "by material", "per material", "quantity",
        )
    ) or (plan is not None and plan.grain == "line")
    if asks_header_sales and not asks_line_grain:
        has_vbrp_table = '"vbrp"' in s_lower or re.search(r'\bfrom\s+vbrp\b', s_lower) or re.search(r'\bjoin\s+vbrp\b', s_lower)
        sums_vbrp_netwr = bool(
            re.search(r'\bsum\s*\([\s\S]{0,80}vbrp[\s\S]{0,40}netwr', s_lower)
            or (
                has_vbrp_table
                and re.search(r'\bsum\s*\([\s\S]{0,60}netwr', s_lower)
                and not re.search(r'\bsum\s*\([\s\S]{0,80}vbrk[\s\S]{0,40}netwr', s_lower)
            )
        )
        if sums_vbrp_netwr:
            violations.append(
                "Sales/revenue questions default to VBRK header grain (VBRK.netwr). "
                "Do not aggregate vbrp.netwr unless the user explicitly asks for line/product/material detail."
            )
        if has_vbrp_table and "customer" in q and "product" not in q and "material" not in q:
            # Customer ranking for sales should not require item table
            if re.search(r'\bsum\s*\([\s\S]{0,80}(vbrp|[a-z]\.)[\s\S]{0,40}netwr', s_lower) or sums_vbrp_netwr:
                violations.append(
                    "Customer sales ranking must use VBRK.netwr (header), not vbrp line amounts."
                )

    # R3: customer industry must come from KNA1→T016T, never MARA.mbrsh.
    asks_industry = any(tok in q for tok in ("industry", "sector", "brsch")) or (
        plan is not None and "industry" in (plan.dimensions or [])
    )
    if asks_industry:
        uses_mara_industry = bool(
            re.search(r'\bmara\b[\s\S]{0,80}\bmbrsh\b', s_lower)
            or re.search(r'\bmbrsh\b', s_lower)
        )
        if uses_mara_industry:
            violations.append(
                "Customer/industry questions must use VBRK → KNA1.brsch → T016T.brtxt. "
                "Do not use MARA.mbrsh (material industry sector)."
            )
        if '"t016t"' in s_lower and '"kna1"' not in s_lower:
            violations.append(
                "T016T industry text must be joined through KNA1.brsch (customer master), not alone."
            )

    # Accuracy critical: never SUM(vbrp.netwr) without explicit TEXT->NUMERIC cast.
    if re.search(r"sum\s*\(\s*(?:p\.)?\"?netwr\"?\s*\)", s_lower):
        if "cast(nullif(trim(cast(" not in s_lower:
            violations.append(
                'SUM on NETWR must cast TEXT to NUMERIC using CAST(NULLIF(TRIM(CAST(... AS TEXT)), \'\') AS NUMERIC).'
            )

    asks_industry = any(tok in q for tok in ("industry", "sector", "brsch")) or (
        plan is not None and "industry" in (plan.dimensions or [])
    )
    if ('"t016t"' in s_lower) and not asks_industry:
        violations.append(
            "T016T is industry-only; do not include industry table unless user explicitly asks industry/sector."
        )

    # Structured result quality: avoid wildcard output for business-facing analysis tables.
    if re.search(r"\bselect\s+\*", s_lower):
        violations.append(
            "Avoid SELECT * for analysis queries. Select explicit business columns for stable, structured output."
        )

    # Listing/ranking style questions should be deterministic.
    asks_list_or_rank = any(
        tok in q
        for tok in (
            "top ", "highest", "lowest", "best", "worst", "list", "show", "display",
            "descending", "ascending", "rank", "order",
        )
    )
    if asks_list_or_rank and ("order by" not in s_lower):
        violations.append(
            "Listing/ranking query should include ORDER BY for deterministic output."
        )
    # Row-level listing safety: require LIMIT for non-aggregated list/show queries.
    has_list_word = any(tok in q for tok in ("list", "show", "display"))
    has_agg_func = bool(re.search(r"\b(sum|avg|min|max|count)\s*\(", s_lower))
    if has_list_word and not has_agg_func and "limit" not in s_lower:
        violations.append(
            "Row-level listing query should include LIMIT to keep results stable and interpretable."
        )
    # Invoice listing queries that join line-item tables can duplicate invoice rows.
    asks_invoice_listing = has_list_word and "invoice" in q and "count" not in q
    joins_item_table = '"vbrp"' in s_lower or re.search(r'\bjoin\b[\s\S]{0,40}"?vbrp"?', s_lower)
    has_select_distinct = bool(re.search(r"\bselect\s+distinct\b", s_lower))
    if asks_invoice_listing and joins_item_table and not has_agg_func and not has_select_distinct:
        violations.append(
            "Invoice listing joins item-level data and may duplicate invoices; use SELECT DISTINCT "
            'on invoice keys (e.g., "VBRK"."vbeln").'
        )

    # Amount queries should carry currency context to avoid misleading numbers.
    asks_amount_context = any(
        tok in q for tok in ("amount", "value", "revenue", "sales", "cost", "netwr", "total")
    )
    has_amount_column_ref = bool(
        re.search(r'\b(netwr|rmwwr|dmbtr|wrbtr|hsl|ksl|wsl|stprs|wertn|kwert|kbetr)\b', s_lower)
    )
    has_currency_ref = bool(
        re.search(r'\b(waerk|waers|rtcur|hwaer|currency)\b', s_lower)
    )
    if asks_amount_context and has_amount_column_ref and not has_currency_ref:
        violations.append(
            "Monetary query is missing currency column/context (e.g., WAERK/WAERS/RTCUR/HWAER)."
        )
    # Prevent incorrect totals from mixed currencies in aggregated monetary outputs.
    has_aggregate = bool(re.search(r"\b(sum|avg|min|max)\s*\(", s_lower))
    has_group_by = "group by" in s_lower
    if has_amount_column_ref and has_aggregate:
        mentions_currency_grouping = bool(
            re.search(r"\bgroup\s+by\b[\s\S]{0,400}\b(waerk|waers|rtcur|hwaer|currency)\b", s_lower)
        )
        if not (has_currency_ref and (mentions_currency_grouping or not has_group_by)):
            violations.append(
                "Aggregated monetary query must include currency and group by currency "
                "(or otherwise ensure single-currency scope) to avoid mixed-currency totals."
            )
        # If GROUP BY exists, currency must participate in grouping when monetary aggregates are present.
        if has_group_by and has_currency_ref and not mentions_currency_grouping:
            violations.append(
                "Aggregated monetary query selects currency but does not group by currency, "
                "which can still mix currencies in totals."
            )
        # Ensure aggregate expressions on monetary fields are safely cast from text.
        unsafe_money_agg = re.search(
            r'\b(sum|avg|min|max)\s*\(\s*([a-zA-Z_][a-zA-Z0-9_]*\s*\.\s*)?"?(netwr|rmwwr|dmbtr|wrbtr|hsl|ksl|wsl|kwert|kbetr)"?\s*\)',
            s_lower,
        )
        if unsafe_money_agg and "cast(nullif(trim(cast(" not in s_lower:
            violations.append(
                "Monetary aggregate uses raw text amount. Use CAST(NULLIF(TRIM(CAST(col AS TEXT)), '') AS NUMERIC)."
            )

    # Prevent accidental Cartesian joins. Do not treat CTE bodies without JOIN
    # as missing ON; only flag real JOIN clauses that lack ON before the next clause.
    for jm in re.finditer(
        r'\b(?:(?:left|right|inner|full(?:\s+outer)?|outer)\s+)?join\b',
        s_lower,
    ):
        head = s_lower[max(0, jm.start() - 6) : jm.start()]
        if head.endswith("cross "):
            continue
        rest = s_lower[jm.end() :]
        nxt = re.search(r'\b(join|where|group\s+by|order\s+by|limit|having|union|;)\b', rest)
        chunk = rest[: nxt.start()] if nxt else rest[:500]
        if not re.search(r'\bon\b', chunk):
            violations.append(
                "JOIN is missing ON condition; this can produce incorrect Cartesian results."
            )
            break
    if re.search(r"\bon\s+(?:1\s*=\s*1|true)\b", s_lower):
        violations.append(
            "JOIN uses tautological ON condition (ON 1=1/ON TRUE), which is not allowed for accurate analytics."
        )

    # Join-integrity checks for high-impact SAP relationships.
    has_vbrk = '"vbrk"' in s_lower
    has_vbrp = '"vbrp"' in s_lower
    has_kna1 = '"kna1"' in s_lower
    if has_vbrk and has_vbrp:
        # Expect billing header-item join on VBELN.
        if "vbeln" not in s_lower:
            violations.append(
                'VBRK + vbrp query is missing VBELN join key. Join billing header/items on "vbeln".'
            )
        if " on " in s_lower and "lpad" not in s_lower:
            violations.append(
                'VBRK↔vbrp joins should normalize keys with LPAD(TRIM(...),10,\'0\') to avoid leading-zero mismatches.'
            )
    if has_vbrk and has_kna1:
        # Customer-name usage with KNA1 should join on customer key.
        uses_customer_name = "name1" in s_lower
        if uses_customer_name and ("kunag" not in s_lower and "kunnr" not in s_lower):
            violations.append(
                'VBRK + KNA1 customer query appears to miss customer key join. Use VBRK.KUNAG = KNA1.KUNNR (normalized if needed).'
            )
        if uses_customer_name and " on " in s_lower and "lpad" not in s_lower:
            violations.append(
                'VBRK↔KNA1 customer joins should normalize keys with LPAD(TRIM(...),10,\'0\') for accurate matching.'
            )

    # SAP date safety: these fields are text YYYYMMDD and should not be CAST to DATE.
    sap_date_fields = ("fkdat", "budat", "audat", "erdat", "lfdat", "bedat", "agdat")
    if any(f in s_lower for f in sap_date_fields):
        if re.search(r"cast\s*\([\s\S]{0,80}\b(" + "|".join(sap_date_fields) + r")\b[\s\S]{0,40}\bas\s+date\s*\)", s_lower):
            violations.append(
                "SAP date fields (YYYYMMDD text) must not be CAST to DATE; use TRIM/SUBSTRING string comparisons."
            )
        # Direct comparisons on SAP text dates should be TRIM-normalized.
        sap_date_cmp_pattern = (
            r'(?:(?:"?[a-zA-Z_][a-zA-Z0-9_]*"?\s*\.\s*)?)'
            r'"?(?:' + "|".join(sap_date_fields) + r')"?\s*(=|>=|<=|>|<)\s*\'\d{4,8}\''
        )
        if re.search(sap_date_cmp_pattern, s_lower) and "trim(" not in s_lower:
            violations.append(
                "SAP date comparisons should use TRIM(date_col) and exclude empty values for accurate filtering."
            )
        has_sap_date_literal_compare = re.search(sap_date_cmp_pattern, s_lower) or (
            any(f in s_lower for f in sap_date_fields)
            and bool(re.search(r"(=|>=|<=|>|<)\s*'\d{4,8}'", s_lower))
        )
        intent_q = _guardrail_intent_text(question, plan)
        if has_sap_date_literal_compare and question_asks_date_filter(intent_q):
            has_non_empty_guard = ("trim(" in s_lower) and ("<> ''" in s_lower or "!= ''" in s_lower)
            if not has_non_empty_guard:
                violations.append(
                    "SAP date filter should explicitly exclude empty values (e.g., TRIM(date_col) <> '')."
                )

    asks_product_drilldown = any(
        tok in q
        for tok in (
            "product level", "line item", "line items", "item level", "by product",
            "by material", "matnr", "deeper", "breakdown", "drill down",
        )
    )
    if asks_product_drilldown and '"vbrp"' in s_lower:
        if not any(t in s_lower for t in ('"makt"', '"mara"', '"marc"', '"mvke"', '"mean"')):
            violations.append(
                "Product drill-down should join billing items to material/product masters "
                "(at least MAKT/MARA; optionally MARC/MVKE/MEAN) for meaningful attributes."
            )

    # Invoice count must be header-level (one row per invoice), not item-level.
    asks_invoice_count = "invoice count" in q or ("count" in q and "invoice" in q)
    if asks_invoice_count and (
        ('"vbrp"' in s_lower and re.search(r'"vbrp"\s*\.\s*"posnr"', s_lower))
        or re.search(r'\b[a-zA-Z_][a-zA-Z0-9_]*\s*\.\s*"posnr"', s_lower)
    ):
        violations.append(
            'Invoice count query is item-level (VBRP.POSNR). Use header-level counting/grouping on "VBRK"."vbeln".'
        )
    if asks_invoice_count and "count(" in s_lower:
        uses_distinct_vbeln = bool(re.search(r'count\s*\(\s*distinct[\s\S]{0,60}vbeln', s_lower))
        if not uses_distinct_vbeln:
            violations.append(
                'Invoice count should use COUNT(DISTINCT "VBRK"."vbeln") to avoid line-item inflation.'
            )

    # ── NEW GUARDRAIL 1: RBKP+RSEG join must include GJAHR ───────────────────
    # SAP document numbers (belnr) are reused across fiscal years. A join on
    # belnr alone can silently pull wrong-year items and corrupt invoice totals.
    has_rbkp = '"rbkp"' in s_lower
    has_rseg = '"rseg"' in s_lower
    if has_rbkp and has_rseg and re.search(r'\bjoin\b', s_lower):
        if 'gjahr' not in s_lower:
            violations.append(
                'RBKP+RSEG join is missing GJAHR: use '
                'JOIN ON r."belnr" = s."belnr" AND r."gjahr" = s."gjahr". '
                'SAP document numbers repeat across fiscal years — omitting GJAHR silently returns '
                'wrong cross-year document matches and corrupts invoice receipt totals.'
            )

    # ── NEW GUARDRAIL 2: BKPF+BSEG must join on BELNR + BUKRS + GJAHR ───────
    # All three keys are mandatory for the FI accounting document relationship.
    # Missing any one causes cross-company-code or cross-year row leakage.
    has_bkpf = '"bkpf"' in s_lower
    has_bseg = '"bseg"' in s_lower
    if has_bkpf and has_bseg and re.search(r'\bjoin\b', s_lower):
        missing_keys = []
        if 'belnr' not in s_lower:
            missing_keys.append('belnr')
        if 'bukrs' not in s_lower:
            missing_keys.append('bukrs')
        if 'gjahr' not in s_lower:
            missing_keys.append('gjahr')
        if missing_keys:
            violations.append(
                f'BKPF+BSEG join is missing key(s): {", ".join(missing_keys)}. '
                'The correct join is: b."belnr" = s."belnr" AND b."bukrs" = s."bukrs" AND b."gjahr" = s."gjahr". '
                'Omitting bukrs or gjahr returns wrong cross-company or cross-year accounting line matches.'
            )

    # ── NEW GUARDRAIL 3: Text/description language filter — SCHEMA-AWARE ────
    # Only require spras when the column exists on that table in the loaded schema.
    # Live DB / tables_columns.csv: T016T has brsch+brtxt only (NO spras).
    _text_tables_lang = (
        ("makt", "MAKT"),
        ("t016t", "T016T"),
        ("cskt", "CSKT"),
        ("t005t", "T005T"),
        ("t001t", "T001T"),
    )
    if re.search(r"\bjoin\b", s_lower):
        for tbl_key, tbl_disp in _text_tables_lang:
            if f'"{tbl_key}"' not in s_lower and f'"{tbl_disp.lower()}"' not in s_lower:
                # also match unquoted rare forms
                if not re.search(rf'\b{re.escape(tbl_key)}\b', s_lower):
                    continue
            if not _table_has_column(tbl_disp, "spras") and not _table_has_column(tbl_key, "spras"):
                # Schema has no spras — do not require it; inventing spras fails schema validation
                continue
            # spras exists → require language filter to avoid multi-language row inflation
            if "spras" not in s_lower:
                violations.append(
                    f'Text/description table join ({tbl_disp}) is missing language filter '
                    "(spras = 'E'). Without it each joined row is duplicated once per language "
                    "loaded in SAP, inflating row counts and corrupting SUM/COUNT results."
                )

    # ── NEW GUARDRAIL 4: Active/open PO queries must check deletion flags ─────
    # EKKO.loekz = 'L' means the PO header is cancelled; EKPO.loekz = 'L' means
    # the item is deleted. Queries for "active", "open", or "outstanding" POs
    # must exclude these or results include cancelled documents.
    asks_active_items = any(
        tok in q for tok in ('active', 'open', 'outstanding', 'pending', 'not deleted', 'current')
    )
    asks_po = any(tok in q for tok in ('purchase order', 'po ', ' po', 'procurement', 'purchasing'))
    if asks_active_items and asks_po and ('"ekko"' in s_lower or '"ekpo"' in s_lower):
        if 'loekz' not in s_lower:
            violations.append(
                'Active/open PO query is missing deletion-flag filter (loekz). '
                "Add TRIM(COALESCE(k.\"loekz\",'')) = '' for EKKO and "
                "TRIM(COALESCE(p.\"loekz\",'')) = '' for EKPO "
                'to exclude cancelled/deleted purchase orders from the results.'
            )

    # ── NEW GUARDRAIL 5: Quantity aggregation must reference unit-of-measure ──
    # SAP quantities (menge, fkimg, kwmeng, lfimg) are stored in the UOM given
    # in meins/gmein. Aggregating across different UOMs (EA, KG, M, L, …) is
    # mathematically meaningless and produces silently wrong totals.
    qty_agg_match = re.search(
        r'\b(sum|avg)\s*\(\s*(?:cast\s*\([\s\S]{0,80}?)?\b'
        r'(menge|fkimg|kwmeng|zmeng|abmng|lfimg|lsmng)\b',
        s_lower,
    )
    if qty_agg_match:
        has_uom_ref = bool(re.search(r'\b(meins|gmein|lmein|vrkme|meinh)\b', s_lower))
        if not has_uom_ref:
            col_hit = qty_agg_match.group(2).upper()
            violations.append(
                f'Quantity aggregation on {col_hit} is missing unit-of-measure reference '
                '(meins/gmein). SAP stores quantities in mixed UOMs (EA, KG, M, …). '
                'Add meins to GROUP BY or filter to a single UOM to avoid meaningless cross-UOM totals.'
            )

    return violations


def _schema_reference_violations(sql: str) -> List[str]:
    """
    Validate explicit SQL references against tables_columns.csv-derived schema.
    We only validate explicit/quoted SAP-style references and schema-qualified refs.
    """
    schema = _load_schema()
    schema_tables_ci = {t.lower(): t for t in schema.keys()}
    local_names = local_sql_relation_names(sql)
    violations: List[str] = []

    # FROM/JOIN table refs + aliases: FROM "VBRK" k / JOIN vbrp p
    # Do not treat JOIN/WHERE/ON/… as an alias (newline: FROM "VBRK"\n JOIN …).
    _alias_ok = (
        r'(?:\s+(?:as\s+)?(?!(?:as|on|join|left|right|inner|outer|full|cross|'
        r'where|group|order|limit|union|except|intersect|having|natural)\b)'
        r'([a-zA-Z_][a-zA-Z0-9_]*))?'
    )
    table_with_alias: List[tuple[str, str]] = []
    # Quoted table refs: FROM "VBRK" k
    for t, a in re.findall(
        r'\b(?:from|join)\s+"([^"]+)"' + _alias_ok,
        sql,
        flags=re.IGNORECASE,
    ):
        table_with_alias.append((t, a or ""))
    # Unquoted table refs: FROM vbrp p
    for t, a in re.findall(
        r'\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)' + _alias_ok,
        sql,
        flags=re.IGNORECASE,
    ):
        table_with_alias.append((t, a or ""))
    seen_tables: set[str] = set()
    alias_to_table: Dict[str, str] = {}
    local_aliases = set(local_names)
    for raw_tbl, alias in table_with_alias:
        tbl = raw_tbl.strip('"')
        tbl_ci = tbl.lower()
        if tbl_ci in local_names or tbl_ci in {"select", "lateral"}:
            local_aliases.add(tbl_ci)
            if alias:
                local_aliases.add(alias.lower())
            continue
        if tbl_ci not in schema_tables_ci:
            violations.append(f'Unknown table reference: "{tbl}" is not in schema.')
            continue
        resolved_tbl = schema_tables_ci[tbl_ci]
        seen_tables.add(resolved_tbl)
        if alias:
            alias_to_table[alias.lower()] = resolved_tbl

    # "TABLE"."column" refs
    qrefs = re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*\.\s*"([A-Za-z_][A-Za-z0-9_]*)"', sql)
    for tbl, col in qrefs:
        tbl_ci = tbl.lower()
        resolved_tbl = schema_tables_ci.get(tbl_ci)
        if not resolved_tbl:
            if tbl_ci in local_names:
                continue
            violations.append(f'Unknown table in quoted reference: "{tbl}"."{col}".')
            continue
        cols = {c["col"].lower() for c in schema.get(resolved_tbl, [])}
        if col.lower() not in cols:
            violations.append(
                f'Unknown column "{col}" on table "{resolved_tbl}" (from "{tbl}"."{col}").'
            )

    # alias.column and alias."column" refs
    alias_col_refs = re.findall(
        r'(?<!")\b([a-zA-Z_][a-zA-Z0-9_]*)\b\s*\.\s*"?([A-Za-z_][A-Za-z0-9_]*)"?',
        sql,
    )
    for alias, col in alias_col_refs:
        a = alias.lower()
        if a in {"public", "dbo"} or a in local_aliases:
            continue
        resolved_tbl = alias_to_table.get(a)
        if not resolved_tbl:
            # alias may actually be a table name written unquoted in ref
            resolved_tbl = schema_tables_ci.get(a)
        if not resolved_tbl:
            continue
        cols = {c["col"].lower() for c in schema.get(resolved_tbl, [])}
        if col.lower() not in cols:
            violations.append(
                f'Unknown column "{col}" on table "{resolved_tbl}" (from alias/table "{alias}.{col}").'
            )

    # de-duplicate while preserving order
    out: List[str] = []
    seen: set[str] = set()
    for v in violations:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _universal_query(
    question: str,
    api_key: str,
    db: Session,
    use_sap: bool,
    max_retries: int = 3,
    plan: Optional[QueryPlan] = None,
    display_question: Optional[str] = None,
    timer: Optional[StageTimer] = None,
) -> Optional[Dict[str, Any]]:
    """
    Main engine: send full schema + question to GPT-4o, execute result.
    Local SQL repairs run before guardrails so the common case is one SQL LLM call.
    """
    from openai import OpenAI
    from ..utils.openai_chat_params import openai_chat_temperature_kwargs, openai_completion_limit_kwargs

    client = OpenAI(api_key=api_key)
    timer = timer or StageTimer()
    chart_q = display_question or _guardrail_intent_text(question, plan) or question

    timer.start("schema")
    schema = _build_schema_prompt()
    timer.stop("schema")
    model = (
        os.getenv("ADAPTIVE_SQL_MODEL")
        or os.getenv("OPENAI_FAST_MODEL")
        or "gpt-4o"
    )
    fast_model = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
    use_summary_llm = os.getenv("ADAPTIVE_SUMMARY_LLM", "false").strip().lower() in (
        "1", "true", "yes", "on",
    )

    timer.start("planner")
    active_plan = plan or extract_query_plan(chart_q)
    timer.stop("planner")
    plan_block = plan_prompt_directive(active_plan)
    full_system = _SYSTEM_PROMPT_CORE + "\n\n" + plan_block + "\n\n" + schema
    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": f"Question: {question}\n\nGenerate the SQL:"},
    ]

    sql = ""
    sql_llm_calls = 0
    for attempt in range(max_retries):
        try:
            timer.start("sql_llm")
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                **openai_chat_temperature_kwargs(model, 0.05),
                **openai_completion_limit_kwargs(model, 900),
            )
            timer.stop("sql_llm")
            sql_llm_calls += 1
            raw = resp.choices[0].message.content or ""
            sql = _extract_sql(raw)
            if not sql:
                messages.append({"role": "assistant", "content": raw})
                messages.append({"role": "user", "content": "Provide SQL in a ```sql block."})
                continue

            timer.start("sql_repair")
            sql = repair_generated_sql(sql, chart_q)
            timer.stop("sql_repair")

            logger.info(f"[universal] attempt {attempt+1}: {sql[:200]}")
            timer.start("guardrail")
            guardrail_violations = _sql_guardrail_violations(question, sql, plan=active_plan)
            timer.stop("guardrail")
            if guardrail_violations:
                logger.warning(
                    "[universal] guardrail rejected SQL attempt %d: %s",
                    attempt + 1,
                    " | ".join(guardrail_violations),
                )
                messages.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your SQL violated mandatory business guardrails:\n- "
                        + "\n- ".join(guardrail_violations)
                        + "\nReturn ONLY corrected SQL in a ```sql block."
                    ),
                })
                continue
            timer.start("schema_validate")
            schema_violations = _schema_reference_violations(sql)
            timer.stop("schema_validate")
            if schema_violations:
                logger.warning(
                    "[universal] schema validation rejected SQL attempt %d: %s",
                    attempt + 1,
                    " | ".join(schema_violations[:5]),
                )
                messages.append({"role": "assistant", "content": f"```sql\n{sql}\n```"})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your SQL references schema elements that do not exist:\n- "
                        + "\n- ".join(schema_violations[:12])
                        + "\nUse only real table/column names from the provided schema. "
                        "Return ONLY corrected SQL in a ```sql block."
                    ),
                })
                continue

            sess = None
            try:
                sess = get_sap_session() if use_sap else db
                timer.start("db")
                data = _execute_sql(sess if use_sap else db, sql, chart_q)
                timer.stop("db")
            finally:
                if use_sap and sess is not None:
                    try:
                        sess.close()
                    except Exception:
                        pass

            logger.info(f"[universal] success: {len(data)} rows sql_llm_calls={sql_llm_calls}")

            charts: List[Dict[str, Any]] = []
            summary = f"Query returned {len(data)} result(s)."

            if data:
                try:
                    timer.start("charts")
                    charts = sanitize_chart_payloads(_auto_charts(chart_q, sql, data), chart_q)
                    timer.stop("charts")
                    logger.info(f"[universal] generated {len(charts)} chart(s)")
                except Exception as chart_err:
                    logger.warning(f"[universal] chart generation failed: {chart_err}")

                if use_summary_llm:
                    try:
                        timer.start("summary_llm")
                        chart_note = f" {len(charts)} chart(s) generated." if charts else ""
                        sr = client.chat.completions.create(
                            model=fast_model,
                            messages=[
                                {"role": "system", "content": (
                                    "You are a data analyst. Summarize database results in 2-4 clear, specific sentences. "
                                    "Include key numbers, top values, and actionable insights. Be specific and concise. "
                                    "CRITICAL NUMBER FORMATTING: never confuse scale (thousand/million/billion). "
                                    "When using M/B abbreviations, also include at least one exact value with separators "
                                    "(e.g., 1,245,678.90) and currency code/symbol to avoid decimal ambiguity."
                                )},
                                {"role": "user", "content": (
                                    f"Question: {chart_q}\n"
                                    f"SQL: {sql[:300]}\n"
                                    f"Results ({len(data)} rows, sample of first 10):\n{data[:10]}\n"
                                    f"Write a 2-4 sentence summary:"
                                )},
                            ],
                            **openai_chat_temperature_kwargs(fast_model, 0.15),
                            **openai_completion_limit_kwargs(fast_model, 350),
                        )
                        timer.stop("summary_llm")
                        summary = (sr.choices[0].message.content.strip() or summary) + chart_note
                    except Exception:
                        summary = deterministic_summary(chart_q, data, sql)
                else:
                    timer.start("summary")
                    summary = deterministic_summary(chart_q, data, sql)
                    timer.stop("summary")
            else:
                named = extract_named_customer(chart_q)
                if named:
                    nf = customer_not_found_payload(chart_q, named, sql)
                    logger.info(
                        "adaptive_stage_timings %s",
                        {**timer.as_dict(), "sql_llm_calls": sql_llm_calls},
                    )
                    return {
                        **nf,
                        "query_plan": active_plan.to_dict(),
                        "plan_fingerprint": active_plan.fingerprint(),
                        "stage_timings": {**timer.as_dict(), "sql_llm_calls": sql_llm_calls},
                    }
                try:
                    summary = _diagnose_empty_result(chart_q, sql, active_plan, db)
                except Exception:
                    summary = (
                        f"The query executed successfully but returned **0 rows**. "
                        f"This may mean no data matches your criteria, or the database "
                        f"may not have data for the specified period.\n\n"
                        f"**SQL executed:**\n```sql\n{sql}\n```"
                    )

            logger.info(
                "adaptive_stage_timings %s",
                {**timer.as_dict(), "sql_llm_calls": sql_llm_calls},
            )
            result: Dict[str, Any] = {
                "sql": sql,
                "rowCount": len(data),
                "data": data,
                "summary": summary,
                "query_plan": active_plan.to_dict(),
                "plan_fingerprint": active_plan.fingerprint(),
                "answer_status": "SUCCESS",
                "stage_timings": {**timer.as_dict(), "sql_llm_calls": sql_llm_calls},
            }
            if charts:
                result["charts"] = charts
            return result

        except Exception as err:
            err_msg = str(err)
            logger.warning(f"[universal] attempt {attempt+1} failed: {err_msg[:200]}")
            messages.append({"role": "assistant", "content": f"```sql\n{sql}\n```" if sql else "(no SQL)"})
            messages.append({
                "role": "user",
                "content": (
                    f"PostgreSQL error:\n```\n{err_msg[:500]}\n```\n\n"
                    "Fix the SQL. Common issues:\n"
                    "- SAP TEXT numeric cols need: SUM(CAST(NULLIF(TRIM(CAST(alias.\"col\" AS TEXT)),'') AS NUMERIC))\n"
                    "- Never COALESCE(netwr, '') — netwr may be numeric; use NULLIF(TRIM(CAST(netwr AS TEXT)), '')\n"
                    "- SAP tables MUST be quoted: FROM \"VBRK\" AS k\n"
                    "- vbrp is stored lowercase but still needs quotes: FROM \"vbrp\" AS p\n"
                    "- SAP dates are TEXT YYYYMMDD — compare as strings, never CAST to DATE\n"
                    "- HAVING cannot reference SELECT aliases — repeat the full aggregate\n"
                    "- Check column names against the schema provided\n"
                    "Return ONLY the corrected SQL in a ```sql block."
                ),
            })

    logger.error(f"[universal] all {max_retries} attempts failed for: {question[:100]}")
    return None

def _compose_drilldown_user_message(
    question: str,
    prev_q: str,
    prev_sql: str,
    rows: List[Dict],
    plan: Optional[QueryPlan] = None,
) -> str:
    sample = rows[:12] if rows else []
    prev_sql_clip = (prev_sql or "")[:1800]
    prev_q_clip = (prev_q or "")[:800]
    sample_json = json.dumps(sample, default=str)[:3500]

    # Detect scope changes between previous and new question to avoid table bleed
    prev_has_t016t = 't016t' in (prev_sql_clip or "").lower()
    new_q_lower = question.lower()
    new_asks_industry = any(tok in new_q_lower for tok in ("industry", "sector", "brsch"))
    if plan is not None and "industry" in (plan.dimensions or []):
        new_asks_industry = True
    scope_notes: List[str] = []
    if prev_has_t016t and not new_asks_industry:
        scope_notes.append(
            "SCOPE CHANGE: Previous query used T016T (industry). "
            "New question does NOT ask for industry — do NOT include T016T. "
            "Write SQL only for what is asked now."
        )
    new_asks_product = any(tok in new_q_lower for tok in (
        "product", "material", "matnr", "line item", "product level", "item level",
        "description", "breakdown", "drill", "by product", "by material",
    )) or (plan is not None and plan.grain == "line")
    if new_asks_product:
        scope_notes.append(
            "PRODUCT DRILL-DOWN: Join vbrp → MARA (matnr) → MAKT (matnr + spras='E') → "
            "MEAN (matnr, optional) → MVKE (matnr+vkorg+vtweg, optional) → MARC (matnr+werks, optional). "
            "vbrp.netwr = line item value. VBRK.netwr = invoice header total. Never confuse them."
        )
    scope_block = ("\n".join(f"⚠ {n}" for n in scope_notes) + "\n") if scope_notes else ""
    plan_block = ("\n" + plan_prompt_directive(plan) + "\n") if plan is not None else ""

    return f"""This is a CONTINUATION of an analysis session. The user already ran a query; now they want a NEW SQL query that applies their follow-up delta while preserving prior filters unless they explicitly change them.
{scope_block}{plan_block}
Previous question:
{prev_q_clip}

Previous SQL (reference for filters — REPLACE/extend as required by the SEMANTIC QUERY PLAN):
```sql
{prev_sql_clip}
```

Sample of prior result rows (hints only — NEVER answer solely from this sample; always run fresh SQL for plan changes):
{sample_json}

New request (generate ONE new PostgreSQL SELECT for this):
{question.strip()}

Rules:
- Preserve year/customer/document filters from the previous question ONLY if still relevant to this new question.
- If the SEMANTIC QUERY PLAN adds industry/customer/currency/ranking/filters, the SQL MUST implement those changes.
- NEVER include T016T (industry) unless the plan/dimensions include industry or the user explicitly says industry/sector.
- Customer industry: VBRK → KNA1 → T016T only. Never MARA.mbrsh.
- Sales/revenue default grain: VBRK.netwr (header) unless plan.grain=line.
- Year filters: SUBSTRING(TRIM("VBRK"."fkdat"),1,4) — NEVER gjahr.
- Monetary queries MUST include currency (waerk) and GROUP BY it — never mix EUR+USD into one total.
- Missing masters: COALESCE(name1,'Unknown / unmapped'), COALESCE(brtxt,'Not available').
- For invoice zero/negative questions ONLY: WHERE on "VBRK"."netwr" — not vbrp.
- T016T: join on brsch via KNA1; add spras='E' ONLY if spras exists in schema (this DB often has brsch/brtxt only).
- For invoice counts: COUNT(DISTINCT k."vbeln") on "VBRK" — never GROUP BY vbrp.posnr.
"""


def _diagnose_empty_result(
    question: str,
    sql: str,
    plan: Optional[QueryPlan] = None,
    db: Optional[Session] = None,
) -> str:
    """Explain likely causes of zero rows; optionally probe year availability."""
    q = (question or "").lower()
    s = (sql or "").lower()
    reasons: List[str] = []
    years = re.findall(r"\b((?:19|20)\d{2})\b", question or "")
    if "gjahr" in s:
        reasons.append(
            "The SQL used VBRK.gjahr, which is unreliable in this database (often '0000'). "
            "Billing year must use SUBSTRING(TRIM(VBRK.fkdat),1,4)."
        )
    if years and db is not None:
        try:
            y = years[0]
            probe = db.execute(
                text(
                    'SELECT COUNT(*) FROM "VBRK" '
                    "WHERE SUBSTRING(TRIM(\"fkdat\"),1,4) = :y"
                ),
                {"y": y},
            ).scalar()
            if probe == 0:
                reasons.append(
                    f"No billing documents found with fkdat year {y}. "
                    "Available years may differ — try another year or remove the year filter."
                )
            else:
                reasons.append(
                    f"Year {y} has {probe} billing header row(s) in VBRK; "
                    "zero result is likely due to an over-restrictive join/filter "
                    "(customer, industry, currency, or wrong grain), not a missing year."
                )
        except Exception:
            try:
                db.rollback()
            except Exception:
                pass
    if plan and plan.filters.get("industry"):
        reasons.append(
            f"Industry filter '{plan.filters.get('industry')}' may not match T016T.brtxt text; "
            "try ILIKE '%...%' or verify the industry label exists."
        )
    if plan and plan.grain == "header" and "vbrp" in s and "netwr" in s:
        reasons.append(
            "Query may be mixing header and line grain incorrectly."
        )
    if not reasons:
        reasons.append(
            "No rows matched the generated filters/joins. "
            "Check year (fkdat), customer key join (kunag=kunnr), industry (KNA1→T016T), and currency scope."
        )
    return "The query returned no rows. Likely cause(s): " + " ".join(reasons)


def _followup_analysis(question: str, prev_q: str, prev_sql: str,
                       rows: List[Dict], api_key: str) -> str:
    """Prior-result narration helper.

    Not a routing fallback. Unrecognized deltas and non-business turns must not
    call this; they go to fresh SQL or CLARIFICATION instead.
    """
    from openai import OpenAI
    from ..services.schema_context_builder import build_schema_context
    from ..utils.openai_chat_params import openai_chat_temperature_kwargs, openai_completion_limit_kwargs

    client = OpenAI(api_key=api_key)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    schema_ctx = build_schema_context(
        question=f"{prev_q}\n{question}", focus_tables=None, max_tables=25, max_cols_per_table=40,
    )
    is_empty = len(rows) == 0
    prompt = (
        "You are a helpful SAP/database analyst.\n"
        "Rules: If rows are non-empty, answer from them. If empty or user wants to fix SQL, propose improved SQL.\n"
        "Proposed SQL must use only real table/column names from schema.\n"
        f"Schema:\n{schema_ctx}\n\n"
        f"Previous question:\n{prev_q}\n\n"
        f"Previous SQL:\n{prev_sql[:1500]}\n\n"
        f"Row sample ({len(rows)} rows):\n{rows[:20]}\n\n"
        f"Follow-up question:\n{question}\n\n"
        f"rows_empty={is_empty}"
    )
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        **openai_chat_temperature_kwargs(model, 0.1),
        **openai_completion_limit_kwargs(model, 900),
    )
    return (resp.choices[0].message.content or "").strip() or "Could not generate follow-up answer."


# ─── Router ───────────────────────────────────────────────────────────────────

@router.get("/api/query/health")
async def adaptive_query_health() -> Dict[str, Any]:
    s = _load_schema()
    # Deployment identity: prefer Vercel/git env; fallback to static marker bumped with AI releases.
    build_id = (
        os.getenv("VERCEL_GIT_COMMIT_SHA")
        or os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
        or ""
    ).strip()
    return {
        "status": "ok",
        "tables": len(s),
        "columns": sum(len(v) for v in s.values()),
        "build_id": build_id[:40] if build_id else None,
        "ai_release": "adaptive-llm-first-understand-v1",
        "trusted_scope": True,
        "database_metadata": True,
        "llm_first_understanding": True,
    }


@router.get("/api/query/schema-diagnostics")
async def adaptive_query_schema_diagnostics() -> Dict[str, Any]:
    s = _load_schema()
    return {"status": "ok", "table_count": len(s),
            "column_count": sum(len(v) for v in s.values()),
            "tables": sorted(s.keys())}


@router.get("/api/query/adaptive")
async def get_query_adaptive() -> Dict[str, Any]:
    return {"error": "method_not_allowed", "message": "Use POST /api/query/adaptive"}


@router.get("/api/ai/schema/capabilities")
async def get_ai_schema_capabilities(
    current_user: ZodiacUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Diagnostic: which imported tables the AI Analyst can see and query."""
    from ..services.adaptive_analyst.capabilities import schema_capabilities

    return schema_capabilities()


@router.get("/api/query/adaptive/history")
async def get_adaptive_chat_history(
    thread_id: str = Query(..., min_length=8),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Load persisted Full Chat turns for an adaptive thread (ada_*).
    Reuses chat_thread_store (same tables as schema-chat; separate ada_ prefix).
    """
    from ..services.chat_thread_store import (
        load_thread, thread_owner_user_id, ensure_chat_tables,
    )

    tid = (thread_id or "").strip()
    if not tid.startswith("ada_"):
        raise HTTPException(status_code=400, detail="thread_id must start with ada_")
    ensure_chat_tables(db)
    owner = thread_owner_user_id(db, tid)
    if owner is not None and current_user is not None and int(current_user.id) != int(owner):
        raise HTTPException(status_code=403, detail="thread_not_owned")
    uid = int(current_user.id) if current_user is not None else (int(owner) if owner else 0)
    if not uid:
        return {"thread_id": tid, "messages": []}
    turns = load_thread(db, uid, tid, last_n=80)
    messages: List[Dict[str, Any]] = []
    for t in turns:
        role = t.get("role")
        content = t.get("content") or ""
        msg: Dict[str, Any] = {"role": role, "content": content}
        if role == "assistant":
            rows = t.get("result_rows") or []
            metrics = t.get("key_metrics") if isinstance(t.get("key_metrics"), dict) else {}
            msg["result"] = {
                "sql": t.get("sql_executed") or "",
                "data": rows,
                "charts": t.get("charts") or [],
                "summary": content,
                "rowCount": len(rows) if isinstance(rows, list) else 0,
                "query_plan": metrics.get("query_plan"),
                "answer_status": metrics.get("answer_status") or "SUCCESS",
            }
        messages.append(msg)
    return {"thread_id": tid, "messages": messages}


def _persist_adaptive_turn_async(snapshot: Dict[str, Any]) -> None:
    """Write Full Chat turns off the HTTP critical path (remote app-DB RTT is ~2s)."""
    from ..database import SessionLocal
    from ..services.chat_thread_store import ensure_chat_tables, next_turn_index, save_turn

    t0 = time.perf_counter()
    db2 = SessionLocal()
    try:
        ensure_chat_tables(db2)
        uid = int(snapshot["user_id"])
        tid = str(snapshot["thread_id"])
        idx = next_turn_index(db2, uid, tid)
        rows = snapshot.get("rows") or []
        cols = list(rows[0].keys()) if rows and isinstance(rows[0], dict) else None
        save_turn(
            db2,
            user_id=uid,
            thread_id=tid,
            turn_index=idx,
            role="user",
            content=snapshot.get("question") or "",
            query_mode="new",
            action="adaptive",
            commit=False,
        )
        save_turn(
            db2,
            user_id=uid,
            thread_id=tid,
            turn_index=idx + 1,
            role="assistant",
            content=snapshot.get("summary") or "",
            sql_executed=snapshot.get("sql") or "",
            result_rows=rows if isinstance(rows, list) else None,
            result_columns=cols,
            charts=snapshot.get("charts") or [],
            key_metrics={
                "query_plan": snapshot.get("query_plan"),
                "answer_status": snapshot.get("answer_status"),
            },
            query_mode="new",
            action=snapshot.get("pipeline") or "adaptive",
            commit=False,
        )
        db2.commit()
    except Exception as persist_err:
        logger.debug("adaptive chat persist skipped: %s", persist_err)
        try:
            db2.rollback()
        except Exception:
            pass
    finally:
        try:
            db2.close()
        except Exception:
            pass
        persist_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "[adaptive] persist_ms=%s thread=%s async=1",
            persist_ms,
            snapshot.get("thread_id"),
        )


@router.get("/api/query/adaptive/investigations/{request_id}")
def get_investigation_status(
    request_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
) -> Dict[str, Any]:
    from ..services.investigation_budget import get_investigation

    budget = get_investigation(request_id)
    if budget is None:
        return {"request_id": request_id, "status": "unknown", "pipeline_stage": "UNDERSTANDING"}
    return budget.public_status()


@router.post("/api/query/adaptive/investigations/{request_id}/cancel")
def cancel_investigation_endpoint(
    request_id: str,
    current_user: ZodiacUser = Depends(get_current_user),
) -> Dict[str, Any]:
    from ..services.investigation_budget import cancel_investigation, get_investigation

    ok = cancel_investigation(request_id)
    budget = get_investigation(request_id)
    return {
        "cancelled": ok,
        "request_id": request_id,
        **(budget.public_status() if budget else {"status": "unknown"}),
    }


@router.post("/api/query/adaptive")
def post_query_adaptive(
    question: str = Body(..., embed=True),
    tableHint: Optional[str] = Body(default=None, embed=True),
    contextData: Optional[Dict[str, Any]] = Body(default=None, embed=True),
    overrideSql: Optional[str] = Body(default=None, embed=True),
    threadId: Optional[str] = Body(default=None, embed=True),
    investigationId: Optional[str] = Body(default=None, embed=True),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
) -> Dict[str, Any]:
    """Adaptive analytics entrypoint.

    Intentionally synchronous so FastAPI runs it in a worker thread. That keeps
    the event loop free for cancel/status endpoints while an investigation runs.
    """
    q = (question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail='Send JSON: {"question": "..."}')
    if len(q) > 4000:
        raise HTTPException(status_code=400, detail="question_too_long (max 4000)")

    # Bind trusted execution scope for this request (never LLM-chosen).
    from ..services.adaptive_trusted_scope import (
        TrustedAiExecutionScope,
        classify_cross_user_attempt,
        reset_trusted_scope,
        set_trusted_scope,
    )
    from ..core.workspace.context import list_assigned_customer_ids

    _scope_token = None
    try:
        uid = int(getattr(current_user, "id", 0) or 0)
        allowed: List[str] = []
        try:
            allowed = list_assigned_customer_ids(db, current_user) if current_user is not None else []
        except Exception:
            allowed = []
        _scope_token = set_trusted_scope(
            TrustedAiExecutionScope(user_id=uid, allowed_customer_ids=allowed)
        )
    except Exception as scope_exc:
        logger.warning("[adaptive] trusted scope bind failed: %s", scope_exc)

    # Normalize interrogative sales/revenue ranking phrasings ("which customer had
    # the highest sales?") to the governed canonical form before routing. The
    # user's original wording is preserved for display/history.
    _original_question = q
    try:
        from ..services.ranking_question_normalizer import normalize_ranking_question
        q = normalize_ranking_question(q)
        if q != _original_question:
            logger.info("[adaptive] normalized ranking question: %r -> %r", _original_question, q)
    except Exception as _norm_err:  # never block a query on normalization
        logger.warning("[adaptive] ranking normalizer failed: %s", _norm_err)
        q = _original_question

    try:
        return _post_query_adaptive_body(
            q=q,
            original_question=_original_question,
            tableHint=tableHint,
            contextData=contextData,
            overrideSql=overrideSql,
            threadId=threadId,
            investigationId=investigationId,
            db=db,
            current_user=current_user,
        )
    finally:
        if _scope_token is not None:
            try:
                reset_trusted_scope(_scope_token)
            except Exception:
                pass


def _post_query_adaptive_body(
    *,
    q: str,
    original_question: str,
    tableHint: Optional[str],
    contextData: Optional[Dict[str, Any]],
    overrideSql: Optional[str],
    threadId: Optional[str],
    investigationId: Optional[str],
    db: Session,
    current_user: ZodiacUser,
) -> Dict[str, Any]:
    _original_question = original_question
    openai_key = (
        os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_AI_KEY") or OPENAI_API_KEY or ""
    ).strip()
    google_key = (os.getenv("GOOGLE_API_KEY") or os.getenv("GOOGLE_GEMINI_API_KEY") or "").strip()
    from ..services.ai_native_pipeline import ai_native_enabled
    from ..services.adaptive_analyst import orchestrator_enabled, run_adaptive_orchestrator

    if not openai_key and not google_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Set OPEN_AI_KEY or GOOGLE_API_KEY on the server",
        )
    api_key = openai_key
    thread_id = (threadId or "").strip() or None
    if thread_id and not thread_id.startswith("ada_"):
        thread_id = None  # ignore non-adaptive thread ids
    user_id = int(current_user.id) if current_user is not None and getattr(current_user, "id", None) is not None else 0

    routing_meta: Dict[str, Any] = {}
    from ..services.investigation_budget import (
        InvestigationTimeout,
        begin_investigation,
        end_investigation,
        timeout_response,
        current_budget,
    )

    inv = begin_investigation(q, request_id=(investigationId or "").strip())
    inv.checkpoint("UNDERSTANDING")

    def _persist_and_return(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Attach thread_id, answer_status, and persist via existing chat_thread_store when possible."""
        payload = _annotate_answer_status(dict(payload or {}))
        # Final hard gate: validate against the USER's original wording, not any
        # ranking normalizer rewrite. Wrong results must never become SUCCESS.
        try:
            if str(payload.get("answer_status") or "").upper() == "SUCCESS" and (
                payload.get("sql") or payload.get("data") is not None
            ):
                pipe = str(payload.get("pipeline") or payload.get("sql_generation_method") or "").lower()
                # Result-first follow-ups answer from prior rows; do not re-apply
                # full analytical ranking/grouping gates meant for fresh SQL plans.
                if "result_first" not in pipe:
                    from ..services.plan_satisfaction import (
                        answer_consistent_with_rows,
                        result_matches_analytical_intent,
                    )

                    rows_chk = payload.get("data") or payload.get("rows") or []
                    if not isinstance(rows_chk, list):
                        rows_chk = []
                    sql_chk = str(payload.get("sql") or "")
                    gate_warn = result_matches_analytical_intent(
                        rows_chk, _original_question, sql=sql_chk
                    )
                    gate_warn.extend(
                        answer_consistent_with_rows(
                            str(payload.get("answer") or payload.get("summary") or ""),
                            rows_chk,
                            _original_question,
                        )
                    )
                    if gate_warn:
                        logger.warning(
                            "[adaptive] WRONG_SUCCESS blocked for %r: %s",
                            _original_question[:120],
                            gate_warn[:4],
                        )
                        msg = (
                            "The investigation could not be validated against the analytical "
                            "requirements: " + "; ".join(gate_warn[:4])
                        )
                        payload = {
                            **payload,
                            "answer_status": "CANNOT_ANSWER",
                            "status": "cannot_answer",
                            "type": "semantic_mismatch",
                            "mode": "error",
                            "data": [],
                            "rowCount": 0,
                            "summary": msg,
                            "answer": msg,
                            "keyFindings": [],
                            "meta": {
                                **(payload.get("meta") if isinstance(payload.get("meta"), dict) else {}),
                                "validation_warnings": gate_warn,
                                "wrong_success_blocked": True,
                            },
                        }
        except Exception as gate_err:
            logger.warning("[adaptive] final semantic gate failed open-safe: %s", gate_err)
        budget_now = current_budget()
        if budget_now is not None:
            payload["request_id"] = budget_now.request_id
            payload.setdefault("pipeline_stage", budget_now.pipeline_stage)
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            payload["meta"] = {**meta, **budget_now.public_status()}
            if str(payload.get("answer_status") or "").upper() == "SUCCESS":
                budget_now.final_status = "completed"
                budget_now.pipeline_stage = "COMPLETED"
                payload["pipeline_stage"] = "COMPLETED"
            elif str(payload.get("answer_status") or "").upper() == "TIMEOUT":
                payload["pipeline_stage"] = budget_now.pipeline_stage
            elif str(payload.get("answer_status") or "").upper() == "CANNOT_ANSWER":
                budget_now.final_status = "cannot_answer"
        if routing_meta.get("turn_intent"):
            meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
            payload["meta"] = {**meta, "turn_intent": routing_meta["turn_intent"]}
        sql_l = (payload.get("sql") or "").lower()
        if payload.get("answer_status") == "CANNOT_ANSWER" and (
            "invoice_v2_business_data" in sql_l and "total_rows" in sql_l
        ):
            payload["sql"] = ""
            payload["data"] = []
            payload["rowCount"] = 0
        if thread_id:
            payload = {**payload, "thread_id": thread_id}
        if not (user_id and thread_id):
            end_investigation()
            return payload
        rows = payload.get("data") or payload.get("rows") or []
        if isinstance(rows, list) and len(rows) > 30:
            rows = rows[:30]
        charts = payload.get("charts") or []
        sql_to_store = payload.get("sql") or ""
        if payload.get("answer_status") == "CANNOT_ANSWER":
            sql_to_store = ""
            rows = []
            charts = []
        snapshot = {
            "user_id": user_id,
            "thread_id": thread_id,
            "question": _original_question[:10000],
            "summary": str(
                payload.get("summary")
                or payload.get("answer")
                or payload.get("reply")
                or ""
            )[:10000],
            "sql": sql_to_store,
            "rows": rows if isinstance(rows, list) else [],
            "charts": charts,
            "query_plan": payload.get("query_plan") or payload.get("queryPlan"),
            "answer_status": payload.get("answer_status"),
            "pipeline": payload.get("pipeline") or payload.get("answer_status") or "adaptive",
        }
        threading.Thread(
            target=_persist_adaptive_turn_async,
            args=(snapshot,),
            daemon=True,
            name="adaptive-persist",
        ).start()
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        payload["meta"] = {**meta, "persist_async": True}
        end_investigation()
        return payload

    def _ensure_charts(question_text: str, sql: str, rows: List[Dict[str, Any]], charts: Any) -> List[Dict[str, Any]]:
        """Fill missing charts from result rows using existing _auto_charts (no new generator)."""
        existing = charts if isinstance(charts, list) else []
        if existing:
            return sanitize_chart_payloads(existing, question_text)
        if not rows:
            return []
        try:
            return sanitize_chart_payloads(_auto_charts(question_text, sql or "", rows) or [], question_text)
        except Exception as chart_err:
            logger.warning("[adaptive] auto_charts failed: %s", chart_err)
            return []

    # ── Path 1: Execute user-provided SQL directly ──────────────────────────
    if overrideSql and overrideSql.strip():
        # Public AI Analyst must not accept client SQL. Admin-only escape hatch
        # still runs under TrustedAiExecutionScope (never unscoped).
        if not bool(getattr(current_user, "is_admin", False)):
            raise HTTPException(
                status_code=403,
                detail="overrideSql is not available on the public adaptive endpoint",
            )
        sql_up = overrideSql.upper().strip()
        if not sql_up.startswith("SELECT"):
            raise HTTPException(status_code=400, detail="overrideSql must be SELECT")
        for d in ["DELETE","UPDATE","DROP","ALTER","TRUNCATE","INSERT","CREATE","EXEC","GRANT","REVOKE"]:
            if re.search(r'\b' + d + r'\b', sql_up):
                raise HTTPException(status_code=400, detail=f"Forbidden keyword: {d}")
        from ..services.adaptive_trusted_scope import (
            classify_cross_user_attempt,
            get_trusted_scope,
            touches_user_scoped_table,
        )

        scope = get_trusted_scope()
        if scope is None or int(getattr(scope, "user_id", 0) or 0) <= 0:
            raise HTTPException(
                status_code=403,
                detail="DENIED: overrideSql requires authenticated trusted scope",
            )
        cross_attempt = classify_cross_user_attempt(overrideSql, scope)
        if cross_attempt:
            logger.warning(
                "[adaptive] cross-user override attempt classified=%s user_id=%s",
                cross_attempt,
                getattr(scope, "user_id", None),
            )
        # User-scoped app tables must run on the app DB with trusted scope.
        use_app_db = touches_user_scoped_table(overrideSql) or not USE_SAP_DB_FOR_AI
        sess = None
        try:
            if use_app_db:
                data = _execute_sql(db, overrideSql, q)
            else:
                sess = get_sap_session()
                data = _execute_sql(sess if sess is not None else db, overrideSql, q)
        finally:
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass
        summary = f"Custom SQL executed. {len(data)} row(s) returned."
        try:
            from openai import OpenAI
            from ..utils.openai_chat_params import openai_chat_temperature_kwargs, openai_completion_limit_kwargs

            c = OpenAI(api_key=api_key)
            fast_model = os.getenv("OPENAI_FAST_MODEL", "gpt-4o-mini")
            r = c.chat.completions.create(
                model=fast_model,
                messages=[{"role": "user", "content": f"SQL: {overrideSql[:400]}\nResults ({len(data)} rows): {data[:5]}\nSummarize in 2 sentences:"}],
                **openai_chat_temperature_kwargs(fast_model, 0.1),
                **openai_completion_limit_kwargs(fast_model, 200),
            )
            summary = r.choices[0].message.content.strip() or summary
        except Exception:
            pass
        charts = _ensure_charts(q, overrideSql, data, [])
        return _persist_and_return({
            "sql": overrideSql,
            "rowCount": len(data),
            "data": data,
            "summary": summary,
            "tableHint": tableHint,
            "charts": charts,
            "meta": {
                "trusted_scope": scope.to_public_dict(),
                "cross_user_attempt": cross_attempt,
            },
            "answer_status": "SUCCESS",
        })

    from ..services.operational_query_resolver import _extract_user_question, resolve_operational_query
    clean_q = _extract_user_question(q)
    sap_locked = _is_sap_erp_intent(clean_q)

    # DATABASE_METADATA: schema/catalog introspection (not business analytics).
    try:
        from ..services.adaptive_analyst.database_metadata import (
            answer_database_metadata,
            is_database_metadata_question,
        )

        if is_database_metadata_question(clean_q):
            meta_payload = answer_database_metadata(clean_q, schema=_load_schema())
            if meta_payload is not None:
                return _persist_and_return(meta_payload)
    except Exception as meta_err:
        logger.warning("[adaptive] database_metadata path failed: %s", meta_err)

    if _looks_like_schema_structure_question(clean_q):
        return _persist_and_return(_build_schema_structure_payload(clean_q))

    # SAT / EDI / Zodiac app tables: answer before the SAP business-signal gate and
    # before the orchestrator, which otherwise treats "SAT documents" as chitchat.
    try:
        if resolve_operational_query(clean_q, time_scope="current") is not None:
            from ..services.dashboard_query_router import run_dashboard_query

            op_payload = run_dashboard_query(
                db, api_key, clean_q, [], time_scope="current", days=30,
            )
            reason = str(op_payload.get("sql_path_reason") or op_payload.get("reason") or "")
            if reason.startswith("operational_"):
                rows_out = op_payload.get("rows_preview") or []
                sql_out = op_payload.get("sql") or ""
                charts = _ensure_charts(clean_q, sql_out, rows_out, op_payload.get("charts"))
                logger.info("[adaptive] early operational: %s — %d rows", reason, len(rows_out))
                return _persist_and_return({
                    "sql": sql_out,
                    "rowCount": len(rows_out),
                    "data": rows_out,
                    "summary": op_payload.get("reply") or f"Query returned {len(rows_out)} row(s).",
                    "tableHint": tableHint,
                    "charts": charts,
                    "pipeline": reason,
                    "sql_generation_method": reason,
                    "llm_calls": 0,
                    "query_plan": extract_query_plan(clean_q).to_dict(),
                })
    except Exception as op_early_err:
        logger.warning("[adaptive] early operational path failed: %s", op_early_err)
        try:
            db.rollback()
        except Exception:
            pass

    # Catalog / intent compilers are test fixtures, not runtime answer authorities.
    logger.info("[adaptive] skipping catalog/intent runtime authorities — four-stage is exclusive")

    # Previous context is an input to classification, never proof of continuation.
    prev_q = ""
    prev_sql = ""
    prev_plan_dict = None
    prev_status = ""
    rows_list: List[Dict[str, Any]] = []
    if contextData and isinstance(contextData, dict):
        prev_q = str(contextData.get("previousQuestion") or "").strip()
        prev_sql = str(contextData.get("previousSQL") or "").strip()
        prev_plan_raw = contextData.get("previousPlan") or contextData.get("queryPlan")
        prev_plan_dict = prev_plan_raw if isinstance(prev_plan_raw, dict) else None
        prev_status = str(contextData.get("previousAnswerStatus") or "").strip().upper()
        rows_raw = contextData.get("data")
        rows_list = rows_raw if isinstance(rows_raw, list) else []
        if prev_status == "CANNOT_ANSWER":
            # Preserve deep analytical chain after governed data-gap turns.
            ac = (prev_plan_dict or {}).get("analytical_context") if isinstance(prev_plan_dict, dict) else None
            if not (isinstance(ac, dict) and ac.get("deep_analysis")):
                prev_sql = ""
                prev_plan_dict = None
                rows_list = []
                logger.info("[adaptive] cleared prior context after CANNOT_ANSWER without deep context")
        elif (
            "invoice_v2_business_data" in prev_sql.lower() and "total_rows" in prev_sql.lower()
        ):
            prev_sql = ""
            prev_plan_dict = None
            rows_list = []
            logger.info("[adaptive] cleared contaminated prior SQL/rows before turn classification")

    from ..services.adaptive_analyst.orchestrator import adapt_user_turn

    adapted = adapt_user_turn(
        clean_q,
        prior_question=prev_q,
        prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
        prior_status=prev_status,
    )
    if adapted.action == "query":
        clean_q = adapted.question
        q = adapted.question
        if adapted.drop_prior:
            prev_q = ""
            prev_sql = ""
            prev_plan_dict = None
            rows_list = []
    elif adapted.action == "clarify":
        return _persist_and_return({
            "type": "clarification",
            "answer_status": "CLARIFICATION",
            "sql": "",
            "rowCount": 0,
            "data": [],
            "summary": adapted.clarify_message,
            "answer": adapted.clarify_message,
            "query_plan": {"awaiting_sales_choice": True},
            "suggested_followups": [
                "How many sales orders are there?",
                "Show the top customers by billed sales.",
            ],
        })

    turn = classify_turn(
        clean_q,
        previous_question=prev_q,
        previous_sql=prev_sql,
        previous_plan=prev_plan_dict,
        previous_status=prev_status,
    )
    routing_meta["turn_intent"] = turn.intent
    logger.info(
        "[adaptive] turn_intent=%s reason=%s has_context=%s",
        turn.intent,
        turn.reason,
        bool(prev_sql or prev_plan_dict),
    )
    if turn.intent == TurnIntent.NEW_ANALYTICAL_QUERY:
        prev_q = ""
        prev_sql = ""
        prev_plan_dict = None
        rows_list = []

    if turn.intent != TurnIntent.NEW_ANALYTICAL_QUERY:
        from ..services.result_first_followup import try_answer_from_prior_rows

        reused = try_answer_from_prior_rows(
            clean_q,
            rows_list,
            prior_sql=prev_sql,
            prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
        )
        if reused and not reused.get("needs_plan_expansion"):
            reused["tableHint"] = tableHint
            logger.info("[adaptive] result-first follow-up rows=%s", reused.get("rowCount"))
            return _persist_and_return(reused)

    # Generative AI page: orchestrator for business SQL and for general chat (greetings, world knowledge).
    _orch_enabled = (orchestrator_enabled() or ai_native_enabled()) and not (overrideSql and overrideSql.strip())
    from ..services.ai_followup_routing import is_prior_general_chat

    _prior_general = is_prior_general_chat(
        prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
        prev_status,
        prev_sql,
    )
    _business_turn = turn.intent not in {TurnIntent.NON_BUSINESS, TurnIntent.CLARIFICATION_REQUIRED}
    _general_turn = should_route_to_general_chat(
        clean_q,
        turn,
        previous_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
        previous_status=prev_status,
        previous_sql=prev_sql,
    )
    # LLM-first: prior general chat and underspecified turns go through understanding
    # before any no_business_signal clarification shortcut.
    _needs_understanding = (
        _prior_general
        or _general_turn
        or turn.reason in {"capability_meta", "general_knowledge", "greeting", "no_business_signal", "ambiguous"}
        or is_capability_or_help_question(clean_q)
        or is_greeting_or_chitchat(clean_q)
        or (is_general_knowledge_question(clean_q) and not question_requires_database(clean_q))
        or turn.intent in {TurnIntent.NON_BUSINESS, TurnIntent.CLARIFICATION_REQUIRED}
    )

    # Authoritative GENERAL_CHAT / capability / conversation follow-ups:
    # never fall through to static no_business_signal clarification.
    _authoritative_general = (
        turn.reason in {"capability_meta", "general_knowledge", "greeting"}
        or is_capability_or_help_question(clean_q)
        or is_greeting_or_chitchat(clean_q)
        or (is_general_knowledge_question(clean_q) and not question_requires_database(clean_q))
        or _prior_general
    )
    if (_authoritative_general or _needs_understanding) and not question_requires_database(clean_q):
        if _orch_enabled:
            try:
                orch = run_adaptive_orchestrator(
                    clean_q,
                    db,
                    _execute_sql,
                    use_sap=bool(USE_SAP_DB_FOR_AI),
                    chart_fn=lambda qq, sql, rows: _ensure_charts(qq, sql or "", rows or [], []),
                    prior_question=prev_q,
                    prior_sql=prev_sql,
                    prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
                    prior_rows=rows_list,
                    get_sap_session=get_sap_session,
                    thread_id=thread_id or "",
                    prior_status=prev_status,
                    force_general_chat=_authoritative_general and not _prior_general,
                    schema_for_metadata=_load_schema(),
                )
                if orch:
                    orch["tableHint"] = tableHint
                    orch_mode = str(orch.get("mode") or "")
                    orch_status = str(orch.get("answer_status") or "").upper()
                    orch_fail = str(
                        (orch.get("meta") or {}).get("failure_class")
                        or orch.get("failure_class")
                        or ""
                    ).upper()
                    # Understanding/model failures must not become metric clarification.
                    if orch_fail == "UNDERSTANDING_MODEL_FAILED" or orch_mode == "error":
                        return _persist_and_return(orch)
                    # Understanding selected a capability — return whatever governed
                    # path produced (chat, metadata, clarification, or analytics).
                    return _persist_and_return(orch)
            except Exception as gen_err:
                logger.warning("[adaptive] understanding/general orch failed: %s", gen_err)
                try:
                    db.rollback()
                except Exception:
                    pass
                from ..services.adaptive_analyst.understanding import technical_understanding_failure

                return _persist_and_return(technical_understanding_failure(clean_q, gen_err))
        # Orchestrator disabled: technical limitation, not business-metric clarification.
        return _persist_and_return(
            _cannot_answer_payload(
                clean_q,
                reason="adaptive understanding path unavailable",
            )
        )

    if _orch_enabled and (_business_turn or _general_turn or _needs_understanding):
        try:
            orch = run_adaptive_orchestrator(
                clean_q,
                db,
                _execute_sql,
                use_sap=bool(USE_SAP_DB_FOR_AI),
                chart_fn=lambda qq, sql, rows: _ensure_charts(qq, sql or "", rows or [], []),
                prior_question=prev_q,
                prior_sql=prev_sql,
                prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
                prior_rows=rows_list,
                get_sap_session=get_sap_session,
                thread_id=thread_id or "",
                prior_status=prev_status,
                schema_for_metadata=_load_schema(),
            )
            if orch:
                orch["tableHint"] = tableHint
                orch_status = str(orch.get("answer_status") or "").upper()
                orch_mode = str(orch.get("mode") or "")
                if orch.get("timeout") or orch.get("error") == "timeout" or orch_status == "TIMEOUT" or orch_mode == "timeout":
                    return _persist_and_return(timeout_response(
                        str((orch.get("pipeline_log") or {}).get("timeout_stage") or "orchestrator"),
                        float((orch.get("pipeline_log") or {}).get("elapsed_s") or 0),
                        question=clean_q,
                    ))
                if _general_turn or _prior_general or _needs_understanding:
                    if orch_mode == "general_chat" or (
                        orch_status in {"SUCCESS", "CLARIFICATION"}
                        and not str(orch.get("sql") or "").strip()
                    ):
                        logger.info(
                            "[adaptive] general_chat mode=%s status=%s",
                            orch_mode,
                            orch_status,
                        )
                        return _persist_and_return(orch)
                    orch_fail = str(
                        (orch.get("meta") or {}).get("failure_class")
                        or orch.get("failure_class")
                        or ""
                    ).upper()
                    if orch_fail == "UNDERSTANDING_MODEL_FAILED":
                        return _persist_and_return(orch)
                    # Guard: never surface a DB investigation failure for a
                    # non-database turn. Do NOT convert to metric clarification.
                    if not question_requires_database(clean_q) and orch_status in {
                        "CANNOT_ANSWER",
                        "ERROR",
                        "TIMEOUT",
                    }:
                        logger.warning(
                            "[adaptive] non-database turn orch status=%s — preserving failure",
                            orch_status,
                        )
                        return _persist_and_return(orch)
                    return _persist_and_return(orch)
                logger.info(
                    "[adaptive] orchestrator mode=%s route=%s llm_calls=%s rows=%s status=%s",
                    orch.get("mode"),
                    orch.get("route"),
                    orch.get("llm_calls"),
                    orch.get("rowCount"),
                    orch_status,
                )
                return _persist_and_return(orch)
        except InvestigationTimeout as te:
            return _persist_and_return(timeout_response(te.stage, te.elapsed_s, question=clean_q))
        except Exception as native_err:
            from ..services.investigation_budget import InvestigationTimeout as _InvTimeout

            if isinstance(native_err, _InvTimeout):
                return _persist_and_return(timeout_response(native_err.stage, native_err.elapsed_s, question=clean_q))
            logger.warning("[adaptive] orchestrator failed: %s", native_err)
            try:
                db.rollback()
            except Exception:
                pass
            return _persist_and_return(
                _cannot_answer_payload(
                    clean_q,
                    reason="adaptive analytics engine failed internally",
                )
            )

    if turn.intent in {TurnIntent.NON_BUSINESS, TurnIntent.CLARIFICATION_REQUIRED}:
        # Last resort only if orchestrator path was unavailable above.
        return _persist_and_return(clarification_payload(clean_q, turn.reason))

    # Competing SAP analytics compilers (catalog, sales-order, domain, deep, period-compare,
    # dashboard router, universal LLM) are no longer runtime authorities.
    return _persist_and_return(
        _cannot_answer_payload(
            clean_q,
            reason="investigation did not complete through the adaptive analytics engine",
        )
    )

    # --- LEGACY COMPILER PATHS BELOW ARE UNREACHABLE ---
    # Kept as source for test fixtures / evaluation, not executed.

    # Turn already classified above. Reuse that decision for compiler paths.

    if turn.intent in {TurnIntent.NON_BUSINESS, TurnIntent.CLARIFICATION_REQUIRED}:
        from ..services.analytical_deep_dive import wants_supplier_concentration as _wants_sc

        if not _wants_sc(clean_q):
            return _persist_and_return(clarification_payload(clean_q, turn.reason))

    # ── Path 1.4: catalog source selection (sales-order vs billing vs domain) ──
    # Additive. Frozen R3/R4 billing ranking stays on route="existing".
    try:
        from ..data_catalog.source_selector import select_source
        from ..services.domain_overview_analysis import knowledge_payload, try_domain_overview
        from ..services.sales_order_analysis import try_sales_order_analysis

        spec = select_source(clean_q, prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None)
        routing_meta["r5_source"] = spec.to_log_dict()
        catalog_db = db
        if USE_SAP_DB_FOR_AI:
            try:
                sap_for_cat = get_sap_session()
                if sap_for_cat is not None:
                    catalog_db = sap_for_cat
            except Exception:
                pass
        if spec.route == "knowledge" or spec.reason == "table_absent":
            return _persist_and_return(knowledge_payload(clean_q, spec))
        if spec.needs_clarification:
            payload = clarification_payload(clean_q, spec.reason)
            if spec.clarification_message:
                payload["summary"] = spec.clarification_message
                payload["answer"] = spec.clarification_message
            return _persist_and_return(payload)
        if spec.route == "sales_order":
            so = try_sales_order_analysis(clean_q, spec, catalog_db, _execute_sql)
            if so:
                from ..services.plan_satisfaction import sql_satisfies_analytical_intent

                if sql_satisfies_analytical_intent(str(so.get("sql") or ""), clean_q):
                    meta = so.get("meta") if isinstance(so.get("meta"), dict) else {}
                    so["meta"] = {**routing_meta, **meta}
                    return _persist_and_return(so)
                logger.info("[adaptive] sales_order_catalog rejected — does not satisfy analytical plan")
        if spec.route == "domain_overview":
            ov = try_domain_overview(clean_q, spec, catalog_db, _execute_sql)
            if ov:
                from ..services.plan_satisfaction import sql_satisfies_analytical_intent

                if sql_satisfies_analytical_intent(str(ov.get("sql") or ""), clean_q):
                    meta = ov.get("meta") if isinstance(ov.get("meta"), dict) else {}
                    ov["meta"] = {**routing_meta, **meta}
                    return _persist_and_return(ov)
                logger.info("[adaptive] domain_overview rejected — does not satisfy analytical plan")
    except Exception as cat_err:
        logger.info("[adaptive] catalog source selection skipped: %s", cat_err)

    # ── Path 1.5: governed multi-dimensional deep analysis (schema-backed) ──
    # After classify_turn only. Falls through when not a deep candidate / unsafe.
    try:
        from ..services.analytical_deep_dive import try_deep_multidim_analysis

        deep_db = db
        if USE_SAP_DB_FOR_AI:
            try:
                sap_for_deep = get_sap_session()
                if sap_for_deep is not None:
                    deep_db = sap_for_deep
            except Exception:
                pass
        deep = try_deep_multidim_analysis(
            clean_q,
            deep_db,
            _execute_sql,
            prior_plan=prev_plan_dict if isinstance(prev_plan_dict, dict) else None,
            prior_rows=rows_list,
        )
        if deep:
            meta = deep.get("meta") if isinstance(deep.get("meta"), dict) else {}
            deep["meta"] = {**routing_meta, **meta, "turn_intent": turn.intent}
            logger.info(
                "[adaptive] deep_multidim hit intent=%s queries=%s",
                (meta.get("analytical_plan") or {}).get("intent"),
                meta.get("query_count"),
            )
            return _persist_and_return(deep)
    except Exception as deep_err:
        logger.info("[adaptive] deep_multidim skipped: %s", deep_err)

    # ── Path 2: recognized follow-up delta only (never "contextData exists") ──
    if turn.intent == TurnIntent.FOLLOWUP_DELTA:
        merged_plan = turn.plan
        if merged_plan is None:
            _needs, merged_plan = resolve_follow_up_sql_need(
                q, previous_question=prev_q, previous_sql=prev_sql, previous_plan=prev_plan_dict
            )
        augmented = _compose_drilldown_user_message(
            q, prev_q, prev_sql, rows_list, plan=merged_plan
        )
        logger.info(
            "[universal] follow-up → fresh SQL deltas=%s fingerprint=%s",
            merged_plan.delta_ops,
            merged_plan.fingerprint(),
        )
        try:
            use_sap = bool(USE_SAP_DB_FOR_AI)
            result = None
            sql_method = "universal_llm"
            sap_sess = get_sap_session() if use_sap else None
            exec_sess = sap_sess if sap_sess is not None else db
            try:
                delta_sql = apply_plan_sql_deltas(prev_sql, merged_plan) if prev_sql else ""
                if delta_sql:
                    try:
                        rows_d = _execute_sql(exec_sess, delta_sql, q)
                        sql_method = "deterministic_sql_delta"
                        result = {
                            "sql": delta_sql,
                            "rowCount": len(rows_d),
                            "data": rows_d,
                            "summary": deterministic_summary(q, rows_d, delta_sql),
                            "sql_generation_method": sql_method,
                            "llm_calls": 0,
                            "pipeline": sql_method,
                        }
                    except Exception as delta_err:
                        logger.info("[adaptive] follow-up SQL delta failed: %s", delta_err)
                        try:
                            exec_sess.rollback()
                        except Exception:
                            pass
                if result is None:
                    composed = compose_nl_from_plan(merged_plan)
                    from ..services.intent_dashboard_fast_path import (
                        try_intent_dashboard_fast_path,
                    )
                    fast = try_intent_dashboard_fast_path(exec_sess, composed)
                    if fast and (fast.get("sql") or ""):
                        sql_f = apply_plan_sql_deltas(str(fast.get("sql") or ""), merged_plan)
                        if sql_f != str(fast.get("sql") or ""):
                            rows_f = _execute_sql(exec_sess, sql_f, q)
                        else:
                            rows_f = list(fast.get("rows_preview") or [])
                        sql_method = "intent_sql_fast"
                        result = {
                            "sql": sql_f,
                            "rowCount": len(rows_f),
                            "data": rows_f,
                            "summary": deterministic_summary(q, rows_f, sql_f),
                            "sql_generation_method": sql_method,
                            "llm_calls": 0,
                            "pipeline": sql_method,
                        }
                if result is None:
                    result = _universal_query(
                        augmented, api_key, db, use_sap, max_retries=3, plan=merged_plan,
                        display_question=q,
                    )
                    if result:
                        result["sql_generation_method"] = "universal_llm"
                        result["llm_calls"] = (result.get("stage_timings") or {}).get("sql_llm_calls")
            finally:
                if sap_sess is not None:
                    try:
                        sap_sess.close()
                    except Exception:
                        pass
            if result:
                result["follow_up_mode"] = "drill_down_sql"
                result["query_plan"] = merged_plan.to_dict()
                result["plan_fingerprint"] = merged_plan.fingerprint()
                result["tableHint"] = tableHint
                result["charts"] = _ensure_charts(
                    q, result.get("sql") or "", result.get("data") or [], result.get("charts"),
                )
                if not (result.get("data") or []):
                    result["summary"] = _diagnose_empty_result(
                        q, result.get("sql") or "", merged_plan, db
                    )
                return _persist_and_return(result)
        except Exception as drill_err:
            logger.warning("[universal] drill-down SQL path failed: %s", drill_err)
        return _persist_and_return(
            _cannot_answer_payload(
                q,
                reason="follow-up required fresh SQL but generation failed after retries",
                plan=merged_plan,
                follow_up_mode="sql_failed",
            )
        )

    named_customer = extract_named_customer(clean_q)

    # ── Path 2.5: Year/period compare — BEFORE router/analyst intercept ─────
    # Reuses compare_query_router + orchestrator compare action (no duplicated logic).
    try:
        from ..services.compare_query_router import (
            should_route_period_compare,
            extract_distinct_calendar_years,
            deterministic_year_compare_sql,
        )
        if should_route_period_compare(clean_q):
            logger.info("[adaptive] period-compare fast path: %s", clean_q[:120])
            years = extract_distinct_calendar_years(clean_q)
            cmp_sql = deterministic_year_compare_sql(years)
            sap_sess = get_sap_session() if USE_SAP_DB_FOR_AI else None
            try:
                rows_out = _execute_sql(sap_sess if sap_sess is not None else db, cmp_sql, clean_q)
            except Exception as det_err:
                logger.warning("[adaptive] deterministic year-compare failed: %s", det_err)
                rows_out = None
            finally:
                if sap_sess is not None:
                    try:
                        sap_sess.close()
                    except Exception:
                        pass
            if rows_out is not None:
                charts = _ensure_charts(clean_q, cmp_sql, rows_out, [])
                return _persist_and_return({
                    "sql": cmp_sql,
                    "rowCount": len(rows_out),
                    "data": rows_out,
                    "tableHint": tableHint,
                    "summary": deterministic_summary(clean_q, rows_out, cmp_sql),
                    "charts": charts,
                    "pipeline": "period_compare",
                    "action": "compare",
                })
            from ..services.ai_analysis_orchestrator import (
                run_ai_analysis_orchestrator, orchestrator_payload,
            )
            sap_sess = get_sap_session() if USE_SAP_DB_FOR_AI else None
            try:
                orch = run_ai_analysis_orchestrator(
                    api_key=api_key,
                    user_id=user_id or 0,
                    user_query=clean_q,
                    db=db,
                    conversation_history=[],
                    context_str="",
                    sap_db=sap_sess,
                    time_scope="both",
                    days=30,
                    thread_id=thread_id,
                    query_mode="new",
                )
                payload = orchestrator_payload(orch)
            finally:
                if sap_sess is not None:
                    try: sap_sess.close()
                    except Exception: pass
            rows_out = payload.get("rows") or payload.get("rows_preview") or []
            charts = payload.get("charts") or []
            if not charts and rows_out:
                charts = _ensure_charts(clean_q, payload.get("sql") or "", rows_out, [])
            return _persist_and_return({
                "sql": payload.get("sql") or "",
                "rowCount": len(rows_out),
                "data": rows_out,
                "tableHint": tableHint,
                "summary": payload.get("reply") or "Comparison complete.",
                "charts": charts,
                "pipeline": "period_compare",
                "action": payload.get("action") or "compare",
            })
    except Exception as cmp_err:
        logger.warning("[adaptive] period-compare path failed, falling through: %s", cmp_err)
        try:
            db.rollback()
        except Exception:
            pass

    # ── Path 3: Scalable dashboard router (operational → intent → catalog → universal) ──
    from ..services.dashboard_query_router import run_dashboard_query

    try:
        router_payload = run_dashboard_query(
            db, api_key, clean_q, [], time_scope="current", days=30,
        )
        reason = router_payload.get("sql_path_reason") or router_payload.get("reason") or ""
        if reason and reason != "no_match":
            rows_out = router_payload.get("rows_preview") or []
            sql_out = router_payload.get("sql") or ""
            sql_l = (sql_out or "").lower()
            if sap_locked and "invoice_v2_business_data" in sql_l:
                logger.warning("[adaptive] blocked SAP→EDI router contamination for: %s", clean_q[:80])
            else:
                skip_unfiltered_named = False
                if named_customer:
                    if not sql_has_customer_name_filter(sql_out, named_customer):
                        sql_out = inject_customer_name_predicate(sql_out, named_customer)
                        try:
                            sess = get_sap_session() if USE_SAP_DB_FOR_AI else db
                            try:
                                rows_out = _execute_sql(sess if USE_SAP_DB_FOR_AI else db, sql_out, clean_q)
                            finally:
                                if USE_SAP_DB_FOR_AI and sess is not db:
                                    try:
                                        sess.close()
                                    except Exception:
                                        pass
                        except Exception as re_err:
                            logger.warning("[adaptive] named-customer re-exec failed: %s", re_err)
                    if not sql_has_customer_name_filter(sql_out, named_customer):
                        logger.warning(
                            "[adaptive] skip unfiltered engine result for named customer %s",
                            named_customer,
                        )
                        skip_unfiltered_named = True
                    elif not rows_out:
                        return _persist_and_return(
                            customer_not_found_payload(clean_q, named_customer, sql_out)
                        )
                if not skip_unfiltered_named:
                    charts = _ensure_charts(clean_q, sql_out, rows_out, router_payload.get("charts"))
                    logger.info("[adaptive] scalable router: %s — %d rows, %d charts", reason, len(rows_out), len(charts))
                    timings = router_payload.get("stage_timings") or {}
                    sql_method = (
                        router_payload.get("sql_generation_method")
                        or ("universal_llm" if reason == "universal_adaptive" else reason)
                    )
                    return _persist_and_return({
                        "sql": sql_out,
                        "rowCount": len(rows_out),
                        "data": rows_out,
                        "summary": router_payload.get("reply") or f"Query returned {len(rows_out)} row(s).",
                        "tableHint": tableHint,
                        "charts": charts,
                        "pipeline": reason,
                        "sql_generation_method": sql_method,
                        "llm_calls": router_payload.get("llm_calls") if router_payload.get("llm_calls") is not None else (
                            0 if reason != "universal_adaptive" else 1
                        ),
                        "stage_timings": timings,
                        "query_plan": extract_query_plan(clean_q).to_dict(),
                    })
                result = _universal_query(
                    clean_q, api_key, db, bool(USE_SAP_DB_FOR_AI), max_retries=3,
                    display_question=clean_q,
                )
                if result:
                    result["tableHint"] = tableHint
                    result["charts"] = _ensure_charts(
                        clean_q, result.get("sql") or "", result.get("data") or [], result.get("charts"),
                    )
                    if named_customer and not (result.get("data") or []):
                        return _persist_and_return(
                            customer_not_found_payload(clean_q, named_customer, result.get("sql") or "")
                        )
                    return _persist_and_return(result)
        elif sap_locked and reason == "no_match":
            logger.warning("[adaptive] SAP domain locked; refusing EDI analyst after router no_match")
            return _persist_and_return(
                _cannot_answer_payload(
                    clean_q,
                    reason="SAP SQL generation exhausted (catalog/intent/universal) without a valid ERP query",
                    plan=extract_query_plan(clean_q),
                )
            )
    except Exception as router_err:
        logger.warning("[adaptive] scalable router failed: %s", router_err)
        try:
            db.rollback()
        except Exception:
            pass
        if sap_locked:
            try:
                result = _universal_query(clean_q, api_key, db, USE_SAP_DB_FOR_AI, max_retries=3)
                if result:
                    result["tableHint"] = tableHint
                    result["charts"] = _ensure_charts(
                        clean_q, result.get("sql") or "", result.get("data") or [], result.get("charts"),
                    )
                    return _persist_and_return(result)
            except Exception:
                pass
            return _persist_and_return(
                _cannot_answer_payload(
                    clean_q,
                    reason=f"SAP router/universal failed: {router_err}",
                    plan=extract_query_plan(clean_q),
                )
            )

    # ── Path 4: Analyst pipeline — blocked for SAP/ERP domain continuity ─────
    if sap_locked:
        return _persist_and_return(
            _cannot_answer_payload(
                clean_q,
                reason="SAP/ERP domain question could not be answered; EDI analyst fallback blocked",
                plan=extract_query_plan(clean_q),
            )
        )

    # ── Path 4b: Multi-Stage AI Analyst Pipeline (non-SAP / EDI-capable) ─────
    logger.info(f"[analyst-pipeline] question: {q[:120]}")
    try:
        from ..services.analyst_pipeline import run_analyst_pipeline
        analyst_db = get_sap_session() if USE_SAP_DB_FOR_AI else db
        try:
            result = run_analyst_pipeline(question=q, db_session=analyst_db)
            if result:
                sql_l = (result.get("sql") or "").lower()
                if result.get("degraded_fallback") or (
                    "invoice_v2_business_data" in sql_l and "total_rows" in sql_l
                ):
                    result["answer_status"] = "CANNOT_ANSWER"
                    result["type"] = "cannot_answer"
                result["tableHint"] = tableHint
                result["charts"] = _ensure_charts(
                    q, result.get("sql") or "", result.get("data") or [], result.get("charts"),
                )
                return _persist_and_return(result)
        finally:
            if USE_SAP_DB_FOR_AI and analyst_db is not db:
                try: analyst_db.close()
                except Exception: pass
        raise RuntimeError("Analyst pipeline returned empty result")
    except Exception as pipeline_err:
        logger.warning(f"[analyst-pipeline] falling back to universal engine: {pipeline_err}")
        try:
            result = _universal_query(q, api_key, db, USE_SAP_DB_FOR_AI, max_retries=3)
            if result:
                result["tableHint"] = tableHint
                result["charts"] = _ensure_charts(
                    q, result.get("sql") or "", result.get("data") or [], result.get("charts"),
                )
                return _persist_and_return(result)
            raise RuntimeError("Universal engine: all retries failed")
        except Exception as univ_err:
            logger.warning(f"[universal] falling back to orchestrator: {univ_err}")
        try:
            from ..services.ai_analysis_orchestrator import run_ai_analysis_orchestrator, orchestrator_payload
            sap_sess = get_sap_session() if USE_SAP_DB_FOR_AI else None
            try:
                orch = run_ai_analysis_orchestrator(
                    api_key=api_key, user_id=user_id or 0, user_query=q, db=db,
                    conversation_history=[], context_str="", sap_db=sap_sess,
                    time_scope="current", days=30, thread_id=thread_id, query_mode="new",
                )
                payload = orchestrator_payload(orch)
            finally:
                if sap_sess is not None:
                    try: sap_sess.close()
                    except Exception: pass
            rows_out = payload.get("rows") or payload.get("rows_preview") or []
            charts = _ensure_charts(q, payload.get("sql") or "", rows_out, payload.get("charts"))
            out = {
                "sql": payload.get("sql") or "",
                "rowCount": len(rows_out),
                "data": rows_out,
                "tableHint": tableHint,
                "summary": payload.get("reply") or "Query completed.",
                "charts": charts,
            }
            return _persist_and_return(out)
        except Exception as orch_err:
            raise HTTPException(status_code=500, detail={
                "error_code": "query_failed",
                "message": str(orch_err),
                "hint": "Try specifying table names explicitly.",
            })
