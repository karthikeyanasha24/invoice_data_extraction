"""
Dynamic NL-to-SQL agent for SAP-style tables stored in the main Postgres DB.

This mirrors the INVOICE_BOT behaviour at a high level:
- LLM picks relevant tables based on the question and table descriptions.
- LLM produces a JSON SQL specification (tables, columns, joins, filters, order_by, limit).
- We convert that JSON spec into real SQL for Postgres and execute it via SQLAlchemy.
- Results are summarized back to the user via another LLM call.

It is intentionally generic and works over the following tables (if present in the DB):
VBRP, VBRK, VBAK, VBAP, VBEP, BSAD, BSEG, FAGLFLEXA, KNA1, KNVP, KNVV, MAKT, MARC, MARM, MEAN, MVKE, T016T.

The goal is to power questions like:
- "show me highest sales by product"
- "compare sales data with invoice data and identify major differences"
- "show me lowest sales by customer and country"
- "show me sales by country and industry"
- "which industry has highest revenues"
- "show me highest sales by customer and product and country"
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from ..config.config import OPENAI_API_KEY

logger = logging.getLogger("zodiac-api.sap_sql_agent")

try:
    from openai import OpenAI

    _openai_available = True
except ImportError:  # pragma: no cover - runtime dependency
    OpenAI = None  # type: ignore
    _openai_available = False


# --- Schema config (extensible: edit schema_ai_config.json when adding tables) ---

def _load_schema_config() -> Dict[str, Any]:
    """Load schema_ai_config.json for extensible rules. Returns {} on failure."""
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "schema_ai_config.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                cfg = json.load(f)
            return cfg if isinstance(cfg, dict) else {}
    except Exception as e:
        logger.warning("Could not load schema_ai_config.json: %s", e)
    return {}


_SCHEMA_CONFIG: Dict[str, Any] = {}
def _get_schema_config() -> Dict[str, Any]:
    global _SCHEMA_CONFIG
    if not _SCHEMA_CONFIG:
        _SCHEMA_CONFIG = _load_schema_config()
    return _SCHEMA_CONFIG


# --- Static metadata (fallback when mapping/config lack entries) ---------------------------------------------------------------------------

SAP_TABLE_DESCRIPTIONS: Dict[str, str] = {
    # Sales / Billing
    "VBRP": "Billing document item (sales by product, quantities, net values, currencies, customers). Use for: highest sales by product, revenue analysis.",
    "vbrp": "Same as VBRP – billing document item. Use for sales, revenue, product analysis.",
    "VBRK": "Billing document header (invoice-level amounts, dates, currencies, customers).",
    "VBAK": "Sales document header (orders, customers, dates, overall values).",
    "VBAP": "Sales document item (ordered products, quantities, values).",
    "VBEP": "Schedule lines for sales document items (delivery quantities and dates).",
    # Customer / Material Master
    "KNA1": "Customer master (names, addresses, countries, brsch=industry code). IMPORTANT: brsch is a code, use T016T for industry descriptions.",
    "T016T": "Industry text/descriptions (converts brsch codes to readable industry names). Use this for industry labels in charts.",
    "KNVV": "Customer sales data (sales area, pricing, related attributes).",
    "KNVP": "Customer partners (payer, ship-to, bill-to relationships).",
    "MAKT": "Material descriptions (product names).",
    "MARC": "Plant data for material (plant-level material attributes).",
    "MARM": "Units of measure for material (UOM conversion).",
    "MEAN": "International Article Numbers (EAN/UPC) for materials.",
    "MVKE": "Sales data for materials (sales org, distribution channel, pricing group).",
    # Finance / Accounting
    "BSAD": "Customer open and cleared items (AR line items, payments).",
    "BSEG": "Accounting document segment (line items for GL, customers, vendors).",
    "FAGLFLEXA": "General ledger: totals/line items for new G/L accounting.",
    # Logistics – Outbound
    "LIKP": "Outbound delivery header (delivery documents, shipping dates, quantities, ship-to). Use for: deliveries, logistics.",
    "LIPS": "Outbound delivery item (products, quantities, reference to sales order). Use for: delivery line details.",
    # Vendor / Purchasing
    "LFA1": "Vendor master (vendor names, addresses, countries). Use for: supplier analysis, purchasing.",
    "LFB1": "Vendor company code (vendor accounting, payment terms).",
    "LFM1": "Vendor purchasing org (vendor–purchasing org data).",
    "EKKO": "Purchasing document header (PO header, vendor, dates, currency). Use for: purchase orders.",
    "EKPO": "Purchasing document item (PO line items, materials, quantities, values).",
    "EBAN": "Purchase requisition (requisition items, materials, quantities).",
    # Invoice Verification (Vendor Invoices)
    "RBKP": "Vendor invoice header (invoice document, vendor, amount, currency). Use for: vendor invoice analysis.",
    "RSEG": "Vendor invoice item (invoice line items, materials, quantities, amounts).",
    # Material Document / Reservations
    "MKPF": "Material document header (goods movement header, posting date).",
    "RESB": "Reservation/dependent requirements (material reservations, requirements).",
    "LSEG": "Document segment (document item data).",
}


# High-level join hints between common SAP tables. This is injected into the LLM
# prompt so that the SQL JSON spec uses realistic join paths instead of guessing.
SAP_JOIN_HINTS = """
Typical business key joins you MUST prefer (do NOT invent other join columns):

SALES / BILLING:
- VBRP (billing items) <-> VBRK (billing header)
  * VBRP.VBELN = VBRK.VBELN
- vbrp: same as VBRP, use vbrp.VBELN = VBRK.VBELN

- VBRK (billing header) <-> KNA1 (customer master)
  * VBRK.KUNAG = KNA1.KUNNR
  * VBRK.KUNRG = KNA1.KUNNR   (payer, if present)

- VBAK (sales order header) <-> VBAP (sales order items)
  * VBAK.VBELN = VBAP.VBELN

- VBAP (order items) / VBRP (billing items) <-> VBEP (schedule lines)
  * VBEP.VBELN = VBAP.VBELN AND VBEP.POSNR = VBAP.POSNR

- VBRP / VBAP / LIPS (items with product) <-> MAKT / MVKE / MARC (material master & descriptions)
  * VBRP.MATNR = MAKT.MATNR = MVKE.MATNR = MARC.MATNR
  * VBAP.MATNR = MAKT.MATNR
  * LIPS.MATNR = MAKT.MATNR

- BSAD / BSEG (AR items) <-> KNA1 (customer master)
  * BSAD.KUNNR = KNA1.KUNNR
  * BSEG.KUNNR = KNA1.KUNNR

TEXT / DESCRIPTION TABLES (IMPORTANT for readable labels):
- KNA1 (customer with brsch code) <-> T016T (industry descriptions)
  * KNA1.brsch = T016T.brsch
  * ALWAYS use T016T.brtxt for industry name (not KNA1.brsch which is just "HITE", "TRAD", "FOOD")

- Materials (MATNR code) <-> MAKT (material text)
  * VBRP.MATNR = MAKT.MATNR or VBAP.MATNR = MAKT.MATNR
  * Use MAKT.MAKTX for product names (not just MATNR codes)

LOGISTICS – OUTBOUND DELIVERY:
- LIKP (delivery header) <-> LIPS (delivery items)
  * LIKP.VBELN = LIPS.VBELN

- LIPS (delivery items) <-> VBAP (sales order items) – reference
  * LIPS.VGBEL = VBAP.VBELN AND LIPS.VGPOS = VBAP.POSNR

- LIKP (delivery) <-> KNA1 (ship-to customer)
  * LIKP.KUNNR = KNA1.KUNNR  (if present)

PURCHASING / VENDOR:
- EKKO (PO header) <-> EKPO (PO items)
  * EKKO.EBELN = EKPO.EBELN

- EKKO / EKPO <-> LFA1 (vendor master)
  * EKKO.LIFNR = LFA1.LIFNR
  * EKPO.LIFNR = LFA1.LIFNR  (if present)

- RBKP (vendor invoice header) <-> RSEG (vendor invoice items)
  * RBKP.BELNR = RSEG.BELNR AND RBKP.GJAHR = RSEG.GJAHR  (if GJAHR present)
  * or RBKP.BELNR = RSEG.BELNR

- RBKP <-> LFA1 (vendor)
  * RBKP.LIFNR = LFA1.LIFNR

- EBAN (purchase req) <-> EKPO (PO items) – optional, via EBAN–EKPO reference fields if present

MATERIAL DOCUMENT:
- MKPF <-> MSEG (if MSEG exists): MKPF.MBLNR = MSEG.MBLNR, MKPF.MJAHR = MSEG.MJAHR

VERY IMPORTANT:
- VBRP / vbrp usually does NOT have KUNNR directly. To reach the customer, go:
  VBRP.VBELN -> VBRK.VBELN, then VBRK.KUNAG -> KNA1.KUNNR.

- When you need INDUSTRY of a customer:
  * NEVER use KNA1.brsch alone (it's just a code like "HITE", "TRAD", "FOOD")
  * ALWAYS join T016T to get the description: T016T.brtxt (readable industry name)
  * Join: KNA1.brsch = T016T.brsch
  * SELECT T016T.brtxt as industry_name (not KNA1.brsch)

- When you need COUNTRY of a customer:
  * KNA1.LAND1 (country code)

- For cost-related or COGS queries, use EKPO (purchase values), RBKP/RSEG (vendor invoice amounts), BSEG (accounting).
"""


@dataclass
class SqlAgentResult:
    sql: str
    rows: List[Dict[str, Any]]


_QUERY_TO_SQL_CACHE: Dict[str, str] = {}
_SQL_TO_ROWS_CACHE: Dict[str, List[Dict[str, Any]]] = {}


# --- Utility helpers --------------------------------------------------------------------------


def _get_openai_client() -> OpenAI | None:
    if not _openai_available:
        logger.warning("OpenAI package not available for sap_sql_agent")
        return None
    api_key = OPENAI_API_KEY
    if not api_key:
        logger.warning("OPEN_AI_KEY/OPENAI_API_KEY not set for sap_sql_agent")
        return None
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:  # pragma: no cover - network/config
        logger.warning("Failed to create OpenAI client for sap_sql_agent: %s", e)
        return None


def _serialize_value(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    if hasattr(v, "isoformat"):
        try:
            return v.isoformat()
        except Exception:
            return str(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="ignore")
    return v


def _introspect_columns(db: Session, table_names: List[str]) -> Dict[str, Dict[str, str]]:
    """
    Introspect the DB to get columns for each table and build semantic descriptions.

    Priority:
    1) If db_table_mapping.json (generated by test_db_connection.py) exists, use its
       per-column descriptions for any matching tables/columns.
    2) Otherwise, fall back to simple heuristic descriptions.
    """
    insp = inspect(db.bind)
    mapping: Dict[str, Dict[str, str]] = {}

    # Try to load pre-generated mapping file (optional)
    mapping_file: Dict[str, Any] = {}
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "db_table_mapping.json"
        if path.exists():
            import json as _json  # local import to avoid polluting module namespace

            with path.open("r", encoding="utf-8") as f:
                raw = _json.load(f)
            if isinstance(raw, dict):
                mapping_file = raw
    except Exception:
        # Non-fatal; we just fall back to heuristics
        mapping_file = {}

    for tbl in table_names:
        # Find matching table in DB, case-insensitive
        db_tables = {t.lower(): t for t in insp.get_table_names()}
        actual_name = db_tables.get(tbl.lower())
        if not actual_name:
            continue

        cols: Dict[str, str] = {}
        file_entry = mapping_file.get(actual_name) or mapping_file.get(tbl) or {}
        file_cols = (file_entry.get("columns") or {}) if isinstance(file_entry, dict) else {}

        for col in insp.get_columns(actual_name):
            col_name = col["name"]
            if isinstance(file_cols, dict) and col_name in file_cols:
                # Use human-friendly description from mapping file when available
                cols[col_name] = str(file_cols[col_name])
            else:
                # Simple heuristic description; LLM will still see raw names
                cols[col_name] = f"{tbl}.{col_name} column"

        if cols:
            mapping[actual_name] = cols

    return mapping


def _get_table_descriptions(db: Session) -> Dict[str, str]:
    """
    Build table descriptions. Priority (mapping-first, adaptive for new tables):
    1) db_table_mapping.json meta.description
    2) schema_ai_config.json table_semantic_hints
    3) SAP_TABLE_DESCRIPTIONS (fallback)
    4) Generic fallback

    Skip tables from schema_ai_config skip_tables.
    """
    insp = inspect(db.bind)
    db_table_names = insp.get_table_names()
    cfg = _get_schema_config()
    skip_set = {s.lower() for s in (cfg.get("skip_tables") or [])}
    db_table_names = [t for t in db_table_names if t.lower() not in skip_set]

    mapping_file: Dict[str, Any] = {}
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "db_table_mapping.json"
        if path.exists():
            import json as _json
            with path.open("r", encoding="utf-8") as f:
                raw = _json.load(f)
            if isinstance(raw, dict):
                mapping_file = raw
    except Exception:
        pass

    table_hints = (cfg.get("table_semantic_hints") or {})
    out: Dict[str, str] = {}
    for actual_name in db_table_names:
        # 1) Mapping meta (from db_table_mapping.json - updated by refresh_schema_for_ai.py)
        entry = mapping_file.get(actual_name) or mapping_file.get(actual_name.upper())
        if isinstance(entry, dict) and entry.get("meta", {}).get("description"):
            desc = str(entry["meta"]["description"])
            if desc and desc != f"{actual_name} table":
                out[actual_name] = desc
                continue
        # 2) Config table_semantic_hints (extensible - add new tables here)
        desc = table_hints.get(actual_name) or table_hints.get(actual_name.upper())
        if desc:
            out[actual_name] = desc
            continue
        # 3) Hardcoded fallback
        desc = SAP_TABLE_DESCRIPTIONS.get(actual_name) or SAP_TABLE_DESCRIPTIONS.get(actual_name.upper())
        if desc:
            out[actual_name] = desc
            continue
        # 4) Generic
        out[actual_name] = f"{actual_name} table – check columns for available fields."
    return out


def _pick_tables(
    question: str,
    client: OpenAI,
    db: Session,
    knowledge_context: Optional[str] = None,
) -> List[str]:
    """
    Pick tables needed to answer the question. Uses dynamic table list from DB +
    mapping so new tables are auto-detected. User knowledge (e.g. "use these for costs")
    is injected when provided.
    """
    table_descriptions = _get_table_descriptions(db)
    if not table_descriptions:
        table_descriptions = SAP_TABLE_DESCRIPTIONS  # fallback

    knowledge_block = ""
    if knowledge_context and knowledge_context.strip():
        knowledge_block = f"""
User preferences / stored knowledge (apply when relevant):
{knowledge_context.strip()}
"""

    prompt = f"""
User question: "{question}"
{knowledge_block}
You are selecting SAP-style tables that live in a Postgres database.
Here are the available tables (use exact names as shown):
{json.dumps(table_descriptions, indent=2)}

Task:
- Choose ONLY the tables that are truly needed to answer the question.
- Use EXACT table names as they appear above (e.g. vbrp if listed, VBRK, LIKP, etc.).
- For sales/revenue: prefer VBRP or vbrp + VBRK + KNA1 + MAKT.
- For purchasing/vendor invoices: prefer EKKO + EKPO + LFA1, or RBKP + RSEG + LFA1.
- For logistics/deliveries: prefer LIKP + LIPS.
- Return STRICT JSON only:
{{
  "selected_tables": [
    {{ "name": "<exact_table_name>", "description": "..." }}
  ]
}}
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
    tables = [t.get("name") for t in data.get("selected_tables", []) if isinstance(t, dict) and t.get("name")]
    # Normalize: ensure we only pick tables that exist in DB
    db_tables_lower = {t.lower(): t for t in table_descriptions}
    normalized = []
    for t in tables:
        key = (t or "").strip()
        if not key:
            continue
        actual = db_tables_lower.get(key.lower())
        if actual:
            normalized.append(actual)
    tables = normalized
    
    # Auto-include description/text tables for better labels
    q_lower = question.lower()
    if "industry" in q_lower or "industries" in q_lower:
        # Ensure T016T is included ONLY when question asks about industry (T016T has brsch/brtxt, not VBELN)
        t016t_match = db_tables_lower.get("t016t")
        if t016t_match and t016t_match not in tables and any(t.upper() == "KNA1" for t in tables):
            tables.append(t016t_match)
            logger.info(f"✨ Auto-added T016T for industry descriptions")
    else:
        # Remove T016T if question does not ask about industry (prevents wrong joins like t.VBELN)
        tables = [t for t in tables if t.upper() != "T016T"]

    if "product" in q_lower or "material" in q_lower:
        # Ensure MAKT is included for product descriptions
        makt_match = db_tables_lower.get("makt")
        if makt_match and makt_match not in tables:
            tables.append(makt_match)
            logger.info(f"✨ Auto-added MAKT for product descriptions")
    
    if not tables:
        # Fallback: try vbrp/VBRP, VBRK, or first available
        for cand in ["vbrp", "VBRP", "VBRK"]:
            if cand in table_descriptions or cand.upper() in {k.upper() for k in table_descriptions}:
                tables = [cand if cand in table_descriptions else next(k for k in table_descriptions if k.upper() == cand.upper())]
                break
        if not tables and table_descriptions:
            tables = [list(table_descriptions.keys())[0]]
    return tables


def _generate_sql_json(
    question: str,
    selected_tables: List[str],
    column_mappings: Dict[str, Dict[str, str]],
    client: OpenAI,
    time_scope: str = "current",
    few_shot_examples: Optional[List[Dict[str, str]]] = None,
    table_descriptions: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Equivalent of INVOICE_BOT.generate_sql_json, but simplified and Postgres-focused.

    Supports:
    - simple SELECTs
    - aggregates (SUM/AVG/COUNT/MIN/MAX) via the optional "agg" field on columns
    - GROUP BY via a dedicated "group_by" list
    """
    # Determine date filter based on time_scope
    date_filter_instruction = ""
    if time_scope == "historical":
        date_filter_instruction = """
⏳ **TIME SCOPE: HISTORICAL DATA (1994-2010)**
- MUST add date filters to ONLY include data from 1994-01-01 to 2010-12-31
- Example: {{"lhs": "VBRK.FKDAT", "operator": ">=", "rhs": "'1994-01-01'"}}, {{"lhs": "VBRK.FKDAT", "operator": "<=", "rhs": "'2010-12-31'"}}
"""
    elif time_scope == "current":
        date_filter_instruction = """
⏳ **TIME SCOPE: CURRENT PERIOD**
- Include recent data only (no strict date filter unless user specifies)
"""
    elif time_scope == "both":
        date_filter_instruction = """
⏳ **TIME SCOPE: ALL PERIODS**
- Include ALL data from 1994 to present for comparison
"""

    few_shot_block = ""
    if few_shot_examples:
        # Keep prompt lean: only a few short examples
        cleaned_examples = []
        for ex in few_shot_examples[:5]:
            uq = str(ex.get("user_query") or "")[:500]
            sql_ex = str(ex.get("sql_query") or "")[:1500]
            if uq and sql_ex:
                cleaned_examples.append({"user_query": uq, "sql_query": sql_ex})
        if cleaned_examples:
            few_shot_block = (
                "\nRecent successful question→SQL examples (use as patterns, do NOT copy literally):\n"
                f"{json.dumps(cleaned_examples, indent=2)}\n"
            )

    # Table descriptions: config/mapping-first, fallback to SAP_TABLE_DESCRIPTIONS
    tbl_desc = table_descriptions or {}
    tables_block = {tbl: tbl_desc.get(tbl) or tbl_desc.get(tbl.upper()) or SAP_TABLE_DESCRIPTIONS.get(tbl, "") for tbl in selected_tables}

    # Config-driven: column_semantic_hints + join_rules (extensible when adding new tables)
    cfg = _get_schema_config()
    col_hints = cfg.get("column_semantic_hints") or {}
    join_rules = cfg.get("join_rules") or []
    col_hints_block = ""
    if col_hints:
        col_hints_block = (
            "\nColumn semantics (use when choosing columns – from schema_ai_config.json):\n"
            + "\n".join(f"- {k}: {v}" for k, v in list(col_hints.items())[:25])
            + "\n"
        )
    join_rules_block = ""
    if join_rules:
        join_rules_block = "\nConfigured join rules (schema_ai_config.json – use these when joining):\n" + "\n".join(
            f"- {r.get('left')} + {r.get('right')}: {r.get('on', '')}" for r in join_rules[:20]
        ) + "\n"
    
    prompt = f"""
User question: "{question}"

{date_filter_instruction}

{few_shot_block}

Tables available (subset already selected as relevant):
{json.dumps(tables_block, indent=2)}

Column mappings (table -> column -> short description):
{json.dumps(column_mappings, indent=2)}
{col_hints_block}
Known join patterns between these tables:
{SAP_JOIN_HINTS}
{join_rules_block}

Task:
- Choose relevant columns from these tables.
- Propose joins between tables using ONLY the business keys listed above (do NOT invent other join columns).
- Remember that VBRP typically does NOT have KUNNR; to reach the customer, you MUST join via VBRK then KNA1.
- **T016T (industry)**: ONLY include T016T when the question explicitly asks for "industry" or "by industry".
  * T016T has ONLY columns brsch and brtxt (no VBELN, no KUNNR).
  * Join: KNA1.brsch = T016T.brsch (NOT on VBELN).
  * SELECT T016T.brtxt for industry name (not KNA1.brsch which is just a code).
  * Do NOT add T016T for questions about products, customers, or sales alone.
- **SIMILAR RULE**: For materials, use MAKT.MAKTX (description) not MATNR (code)
- **Margin/profitability**: margin = (revenue - cost) / revenue. Revenue from VBRP.NETWR. Cost from EKPO.NETWR or CKIS.wertn joined on material. For "average margin on low products" use AVG of margin per product, filter to low-margin products, group by product. If EKPO/CKIS not available, use revenue-only analysis and note that true margin needs cost data.
- **Cost of a specific product (e.g. a jacket)**: when the question is "cost of X" or "price of X", and tables MAKT + EKPO/RSEG exist, include:
  * MAKT to filter by description, e.g. MAKT.MAKTX ILIKE '%harley%jacket%'.
  * EKPO (or RSEG) for the monetary amounts and quantities (NETWR / WRBTR and MENGE).
  * Compute total cost as SUM(amount) and, where possible, unit cost as SUM(amount) / SUM(quantity).
  * Group by material and MAKT.MAKTX so we only show rows actually matching the requested product text.
- Add filters only if clearly needed from the question (for dates, customers, countries, industries, products, etc.).
- Return STRICT JSON with this structure:
{{
  "tables": [{{ "name": "VBRP", "description": "..." }}],
  "columns": [
    {{ "table": "T016T", "name": "brtxt", "description": "industry_name", "agg": null }},
    {{ "table": "VBRP", "name": "NETWR", "description": "total_sales", "agg": "SUM" }}
  ],
  "joins": [
    {{ "left": "VBRP", "right": "VBRK", "on": "VBRP.VBELN = VBRK.VBELN" }},
    {{ "left": "VBRK", "right": "KNA1", "on": "VBRK.KUNAG = KNA1.KUNNR" }},
    {{ "left": "KNA1", "right": "T016T", "on": "KNA1.brsch = T016T.brsch" }}
  ],
  "filters": [{{ "lhs": "VBRK.FKDAT", "operator": ">=", "rhs": "'2024-01-01'" }}],
  "group_by": [
    {{ "table": "T016T", "column": "brtxt" }}
  ],
  "having": [
    {{ "lhs": "total_sales", "operator": ">", "rhs": "0" }}
  ],
  "order_by": [
    "total_sales DESC"
  ],
  "limit": 200
}}

Rules:
- Use table and column names that actually exist in the column mappings.
- If a column entry has "agg": "SUM" | "AVG" | "COUNT" | "MIN" | "MAX",
  you are defining an aggregated metric over that column.
- CRITICAL: For "order_by", you MUST reference a column by its "description" field from the "columns" array.
  Example: If you have {{"table": "VBRP", "name": "NETWR", "description": "total_sales", "agg": "SUM"}},
  then order_by should be ["total_sales DESC"], NOT ["NETWR DESC"] or ["billing_item_net_value DESC"].
- For questions like:
    * "which industry has highest revenues"
    * "top customers by sales"
    * "highest sales by customer and product"
  you MUST:
    * pick an appropriate numeric metric column (e.g., VBRP.NETWR, BSAD.DMBTR, INVOICE_V2_BUSINESS_DATA.TOTAL_AMOUNT)
    * set "agg": "SUM" (or another relevant aggregate) on that metric column
    * give it a clear "description" like "total_sales" or "total_revenue"
    * add the dimension columns (industry, customer, product, country, etc.) to "group_by"
    * filter out NULL dimension values where it makes sense (e.g., industry IS NOT NULL)
    * order by the metric's description (e.g., "total_sales DESC") and use a small limit (e.g. 50 or 100).
- If the question is about "lowest", sort ASC instead of DESC.
- **CRITICAL for lowest/highest/top/bottom by dimension**: Exclude zero/empty aggregates.
  When grouping by customer, country, product, industry, etc. and showing SUM of sales/amounts,
  add "having": [{{ "lhs": "<metric_description>", "operator": ">", "rhs": "0" }}]
  so we only show entities that have actual activity. E.g. for "lowest sales by customer and country",
  add having on total_sales > 0 — otherwise we get customers with $0 (no sales), which is wrong.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    content = resp.choices[0].message.content or ""
    try:
        spec = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        spec = json.loads(m.group(0)) if m else {}
    return spec or {}


def _ensure_having_for_aggregates(spec: Dict[str, Any], question: str) -> None:
    """
    When question asks for lowest/highest/top/bottom by dimension with aggregates,
    auto-inject HAVING metric > 0 so we exclude entities with $0 (wrong for rankings).
    Modifies spec in place.
    """
    q_lower = (question or "").lower()
    if not any(kw in q_lower for kw in ("lowest", "highest", "top", "bottom", "minimum", "maximum", "best", "worst")):
        return
    if spec.get("having"):
        return
    group_bys = spec.get("group_by") or []
    if not group_bys:
        return
    columns = spec.get("columns") or []
    sum_col = None
    for col in columns:
        if str(col.get("agg") or "").upper() in ("SUM", "AVG"):
            sum_col = col
            break
    if not sum_col:
        return
    human = sum_col.get("description") or f"{sum_col.get('table', '')}_{sum_col.get('name', '')}"
    human_safe = re.sub(r"[^\w]", "_", str(human))[:60] or "total"
    spec["having"] = [{"lhs": human_safe, "operator": ">", "rhs": "0"}]
    logger.info("Auto-injected HAVING %s > 0 for ranking query", human_safe)


def _json_to_sql_postgres(json_spec: Dict[str, Any], column_mappings: Dict[str, Dict[str, str]]) -> str:
    """
    Convert JSON spec into a Postgres SQL query.

    We mirror the INVOICE_BOT approach:
    - Build SELECT list for chosen columns.
    - Start from a base table, then add JOINs from the spec.
    - If some tables are missing join conditions, join them via common keys if possible (e.g., VBELN, KUNNR, MATNR).
    """
    columns = json_spec.get("columns", []) or []
    joins = json_spec.get("joins", []) or []
    tables_info = json_spec.get("tables", []) or []
    limit = int(json_spec.get("limit", 100) or 100)

    all_tables: List[str] = []
    for j in joins:
        all_tables.append(j.get("left"))
        all_tables.append(j.get("right"))
    for c in columns:
        all_tables.append(c.get("table"))
    for t in tables_info:
        all_tables.append(t.get("name"))
    all_tables = [t for t in {t for t in all_tables if t}]  # unique, remove None

    if not all_tables:
        raise ValueError("sap_sql_agent: JSON spec contains no tables")

    # Map spec table names to actual DB table names (case differences already handled by column_mappings keys)
    table_aliases: Dict[str, str] = {}
    used_aliases: set[str] = set()

    def _fmt_alias(tbl: str) -> str:
        base = tbl[0].lower()
        alias = base
        i = 1
        while alias in used_aliases:
            alias = f"{base}{i}"
            i += 1
        used_aliases.add(alias)
        return alias

    # The mapping keys in column_mappings are the actual DB table names.
    # Build a map from logical name (any case) -> actual DB table name.
    logical_to_actual: Dict[str, str] = {}
    for logical in SAP_TABLE_DESCRIPTIONS.keys():
        for actual in column_mappings.keys():
            if actual.lower() == logical.lower():
                logical_to_actual[logical] = actual
                logical_to_actual[logical.lower()] = actual
                logical_to_actual[logical.upper()] = actual

    def _actual_table_name(logical: str) -> str:
        key = logical
        if key not in logical_to_actual:
            key = logical.lower()
        if key not in logical_to_actual:
            key = logical.upper()
        return logical_to_actual.get(key, logical)

    # Build a case-insensitive column name map per table so we can always
    # use the real DB column identifiers even if the JSON spec uses upper-case.
    column_name_map: Dict[str, Dict[str, str]] = {}
    for actual_tbl, cols in column_mappings.items():
        column_name_map[actual_tbl] = {c_name.lower(): c_name for c_name in cols.keys()}

    def _actual_column_name(actual_tbl: str, logical_col: str) -> str:
        if not logical_col:
            return logical_col
        table_cols = column_name_map.get(actual_tbl, {})
        return table_cols.get(str(logical_col).lower(), logical_col)

    for tbl in all_tables:
        actual = _actual_table_name(tbl)
        table_aliases[actual] = _fmt_alias(actual)

    # SELECT (also build alias -> aggregate expression for HAVING; PostgreSQL does not allow SELECT aliases in HAVING)
    select_parts: List[str] = []
    used_col_aliases: set[str] = set()
    alias_to_agg_expr: Dict[str, str] = {}

    for col in columns:
        logical_tbl = col.get("table")
        col_name_raw = col.get("name")
        if not logical_tbl or not col_name_raw:
            continue
        actual_tbl = _actual_table_name(logical_tbl)
        if actual_tbl not in table_aliases:
            continue
        alias = table_aliases[actual_tbl]
        col_name = _actual_column_name(actual_tbl, col_name_raw)
        agg = str(col.get("agg") or "").upper()

        # Config-driven casting: schema_ai_config.json defines numeric_columns and trim_numeric_tables.
        # Add new tables/columns there when schema changes; no code changes needed.
        cfg = _get_schema_config()
        numeric_cols = {c.upper() for c in (cfg.get("numeric_columns") or [])}
        trim_tables = {t.upper() for t in (cfg.get("trim_numeric_tables") or [])}
        actual_upper = actual_tbl.upper()
        col_upper = str(col_name).upper()
        needs_numeric_cast = col_upper in numeric_cols
        use_trim_pattern = actual_upper in trim_tables and needs_numeric_cast

        if agg in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            if needs_numeric_cast and agg != "COUNT":
                if use_trim_pattern:
                    expr = f"{agg}(NULLIF(TRIM({alias}.\"{col_name}\"::text), '')::numeric)"
                else:
                    expr = f"{agg}(NULLIF({alias}.\"{col_name}\",'')::numeric)"
            else:
                expr = f"{agg}({alias}.\"{col_name}\")"
        else:
            expr = f'{alias}."{col_name}"'
        human = col.get("description") or f"{actual_tbl}_{col_name}"
        human_safe = re.sub(r"[^\w]", "_", human)[:60] or f"{alias}_{col_name}"
        if human_safe in used_col_aliases:
            suffix = 1
            while f"{human_safe}_{suffix}" in used_col_aliases:
                suffix += 1
            human_safe = f"{human_safe}_{suffix}"
        used_col_aliases.add(human_safe)
        if agg in {"SUM", "AVG", "COUNT", "MIN", "MAX"}:
            alias_to_agg_expr[human_safe] = expr
        select_parts.append(f'    {expr} AS "{human_safe}"')

    if not select_parts:
        # Fallback: SELECT * from first table
        base_logical = all_tables[0]
        base_actual = _actual_table_name(base_logical)
        alias = table_aliases[base_actual]
        select_parts.append(f"    {alias}.*")

    sql_lines: List[str] = [f"SELECT {', '.join(select_parts)}",]

    # Base table: first in joins, else first in tables_info, else first in list
    base_logical = (
        (joins[0].get("left") if joins else None)
        or (tables_info[0].get("name") if tables_info else None)
        or all_tables[0]
    )
    base_actual = _actual_table_name(base_logical)
    base_alias = table_aliases[base_actual]
    sql_lines.append(f'FROM "{base_actual}" AS {base_alias}')

    added_actuals = {base_actual}

    # Helper to rewrite "VBRP.VBELN" → "v.\"vbeln\"" using aliases and actual DB column names.
    # Postgres identifiers are case-sensitive when quoted; DB usually has lowercase columns.
    def _rewrite_expr(expr: str) -> str:
        out = expr
        # Replace Table.Column with alias."actual_column" (uses real DB column casing)
        def _repl(m: re.Match) -> str:
            tbl_part = m.group(1)
            col_part = m.group(2)
            actual_tbl = _actual_table_name(tbl_part)
            alias = table_aliases.get(actual_tbl)
            if not alias:
                return m.group(0)
            actual_col = _actual_column_name(actual_tbl, col_part)
            return f'{alias}."{actual_col}"'
        out = re.sub(r'\b(\w+)\.(\w+)\b', _repl, out)
        return out

    # Add joins from spec
    for j in joins:
        left_logical = j.get("left")
        right_logical = j.get("right")
        on_expr = j.get("on") or ""
        if not right_logical:
            continue
        right_actual = _actual_table_name(right_logical)
        if right_actual in added_actuals:
            continue
        right_alias = table_aliases[right_actual]
        sql_lines.append(f'\nLEFT JOIN "{right_actual}" AS {right_alias}')
        if on_expr:
            sql_lines.append(f"    ON {_rewrite_expr(on_expr)}")
        added_actuals.add(right_actual)

    # Add any missing tables with heuristic joins on common keys (skip if no common key; else invalid SQL)
    COMMON_KEYS = ["VBELN", "KUNNR", "KUNAG", "MATNR", "EBELN", "LIFNR", "BELNR", "BRSCH"]
    for logical_tbl in all_tables:
        actual_tbl = _actual_table_name(logical_tbl)
        if actual_tbl in added_actuals:
            continue
        alias = table_aliases[actual_tbl]
        # Try to join on a shared key with an already-added table
        join_cond = None
        for key in COMMON_KEYS:
            other_col = _actual_column_name(actual_tbl, key)
            if not other_col:
                continue
            for added in added_actuals:
                base_col = _actual_column_name(added, key)
                if base_col:
                    add_alias = table_aliases.get(added)
                    if add_alias:
                        join_cond = f'{add_alias}."{base_col}" = {alias}."{other_col}"'
                        break
            if join_cond:
                break
        if join_cond:
            sql_lines.append(f'\nLEFT JOIN "{actual_tbl}" AS {alias}')
            sql_lines.append(f"    ON {join_cond}")
            added_actuals.add(actual_tbl)

    # WHERE (must come BEFORE GROUP BY)
    conds: List[str] = []
    for f in json_spec.get("filters", []) or []:
        lhs = _rewrite_expr(str(f.get("lhs", "")))
        op = str(f.get("operator", "")).strip().upper()
        rhs_raw = f.get("rhs")
        
        if not lhs or not op:
            continue
        
        # Handle NULL operators (don't need RHS)
        if op in {"IS NULL", "IS NOT NULL"}:
            conds.append(f"{lhs} {op}")
        else:
            # Need RHS for all other operators
            rhs = str(rhs_raw).strip() if rhs_raw is not None else ""
            if rhs and rhs.lower() != "none":
                conds.append(f"{lhs} {op} {rhs}")

    # When using VBRP+VBRK+KNA1 for customer (per verified scripts), exclude NULL joins
    vbrk_actual = next((a for a in added_actuals if a.upper() == "VBRK"), None)
    kna1_actual = next((a for a in added_actuals if a.upper() == "KNA1"), None)
    if vbrk_actual and kna1_actual:
        va = table_aliases.get(vbrk_actual)
        ka = table_aliases.get(kna1_actual)
        vbeln_col = _actual_column_name(vbrk_actual, "VBELN")
        kunnr_col = _actual_column_name(kna1_actual, "KUNNR")
        if va and ka and vbeln_col and kunnr_col:
            conds.append(f'{va}."{vbeln_col}" IS NOT NULL')
            conds.append(f'{ka}."{kunnr_col}" IS NOT NULL')

    if conds:
        sql_lines.append("\nWHERE " + " AND ".join(conds))

    # GROUP BY (must come AFTER WHERE)
    group_bys = json_spec.get("group_by", []) or []
    gb_parts: List[str] = []
    for gb in group_bys:
        if not isinstance(gb, dict):
            continue
        t_logical = gb.get("table")
        col_raw = gb.get("column")
        if not t_logical or not col_raw:
            continue
        t_actual = _actual_table_name(t_logical)
        alias = table_aliases.get(t_actual)
        if not alias:
            continue
        col = _actual_column_name(t_actual, col_raw)
        gb_parts.append(f'{alias}."{col}"')
    if gb_parts:
        sql_lines.append("\nGROUP BY " + ", ".join(gb_parts))

    # HAVING (after GROUP BY, before ORDER BY)
    # PostgreSQL does NOT allow SELECT aliases in HAVING; use the full aggregate expression instead.
    having_parts: List[str] = []
    for h in json_spec.get("having", []) or []:
        if not isinstance(h, dict):
            continue
        lhs = str(h.get("lhs", "")).strip()
        op = str(h.get("operator", "")).strip().upper()
        rhs_raw = h.get("rhs")
        if not lhs or not op:
            continue
        # Match alias by name (case-insensitive)
        lhs_lower = lhs.lower()
        matched = lhs if lhs in used_col_aliases else None
        if not matched:
            for a in used_col_aliases:
                if a.lower() == lhs_lower or lhs_lower in a.lower():
                    matched = a
                    break
        # Use aggregate expression if available; otherwise fall back to alias (may fail in PG)
        lhs_expr = alias_to_agg_expr.get(matched) if matched else None
        if not lhs_expr and matched:
            lhs_expr = f'"{matched}"'
        elif not lhs_expr:
            lhs_expr = lhs
        # Ensure any raw table.column inside HAVING is rewritten to the correct alias/column
        lhs_expr = _rewrite_expr(lhs_expr)
        if op in {"IS NULL", "IS NOT NULL"}:
            having_parts.append(f"{lhs_expr} {op}")
        else:
            rhs = str(rhs_raw).strip() if rhs_raw is not None else ""
            if rhs and rhs.lower() != "none":
                having_parts.append(f"{lhs_expr} {op} {rhs}")
    if having_parts:
        sql_lines.append("\nHAVING " + " AND ".join(having_parts))

    # ORDER BY
    order_by_parts: List[str] = []
    for ob in json_spec.get("order_by", []) or []:
        if isinstance(ob, str):
            # Check if it's a SELECT alias first
            ob_clean = ob.strip().split()[0]  # Remove DESC/ASC
            if ob_clean in used_col_aliases:
                order_by_parts.append(ob)
            else:
                order_by_parts.append(_rewrite_expr(ob))
        else:
            t_logical = ob.get("table")
            col_raw = ob.get("column")
            direction = ob.get("direction", "DESC").upper()
            
            # Try to match against SELECT aliases first (case-insensitive)
            col_lower = str(col_raw).lower().strip() if col_raw else ""
            matched_alias = None
            for used_alias in used_col_aliases:
                if col_lower in used_alias.lower() or used_alias.lower() in col_lower:
                    matched_alias = used_alias
                    break
            
            if matched_alias:
                # Use the SELECT alias directly
                order_by_parts.append(f'"{matched_alias}" {direction}')
            elif t_logical and col_raw:
                # Fall back to table.column format
                t_actual = _actual_table_name(t_logical)
                alias = table_aliases.get(t_actual)
                if alias and t_actual:
                    col = _actual_column_name(t_actual, col_raw)
                    order_by_parts.append(f'{alias}."{col}" {direction}')
    
    if order_by_parts:
        sql_lines.append("\nORDER BY " + ", ".join(order_by_parts))

    sql_lines.append(f"\nLIMIT {limit}")
    return "\n".join(sql_lines) + ";"


def _run_sql(db: Session, sql: str) -> List[Dict[str, Any]]:
    if not sql or not sql.strip():
        return []
    try:
        result = db.execute(text(sql))
        rows = result.fetchall()
        keys = result.keys()
        out: List[Dict[str, Any]] = []
        for row in rows:
            row_dict = {k: _serialize_value(v) for k, v in zip(keys, row)}
            out.append(row_dict)
        return out
    except Exception as e:
        logger.warning("sap_sql_agent SQL execution failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return []


def _summarize_results(question: str, sql: str, rows: List[Dict[str, Any]], client: OpenAI) -> str:
    """
    Ask the LLM to summarize the tabular result in natural language.
    """
    if not rows:
        return ""

    # Truncate to keep prompt reasonable
    sample_rows = rows[:100]
    data_json = json.dumps(sample_rows, default=_serialize_value)

    prompt = f"""
You are an expert SAP sales and finance analyst.

The user asked:
\"\"\"{question}\"\"\"

You executed the following SQL on a Postgres database that contains SAP-style tables:
```sql
{sql}
```

Here is a sample of the result rows as JSON:
{data_json}

Task:
- Explain the answer using ONLY the exact numbers and values from the JSON above.
- Do NOT invent, approximate, or reuse numbers from memory or prior context.
- Include specific numbers (totals, top items, customers, countries, industries) from the data.
- Be concise (3–8 sentences).
- If the JSON is empty, say clearly that no data was returned for this query.
"""
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=600,
    )
    return (resp.choices[0].message.content or "").strip()


def validate_sql_spec(spec: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """
    Validate SQL specification before execution.
    
    Args:
        spec: JSON SQL specification
    
    Returns:
        Tuple of (is_valid, list_of_errors)
    """
    errors = []
    
    # Check basic structure
    if not spec:
        errors.append("Empty specification")
        return False, errors
    
    tables = spec.get("tables", [])
    columns = spec.get("columns", [])
    
    if not tables:
        errors.append("No tables specified")
    
    if not columns:
        errors.append("No columns specified")
    
    # Validate columns reference existing tables
    table_names = {t.get("name") for t in tables if isinstance(t, dict) and t.get("name")}
    for col in columns:
        if isinstance(col, dict):
            col_table = col.get("table")
            if col_table and col_table not in table_names:
                errors.append(f"Column references unknown table: {col_table}")
    
    # Validate joins reference existing tables
    joins = spec.get("joins", [])
    for j in joins:
        if isinstance(j, dict):
            left = j.get("left")
            right = j.get("right")
            if left and left not in table_names:
                errors.append(f"Join references unknown left table: {left}")
            if right and right not in table_names:
                errors.append(f"Join references unknown right table: {right}")
    
    is_valid = len(errors) == 0
    return is_valid, errors


def refine_query_on_error(
    client: OpenAI,
    original_question: str,
    sql_error: str,
    previous_spec: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Use LLM to refine the query specification after an SQL error.
    
    Args:
        client: OpenAI client
        original_question: User's original question
        sql_error: Error message from SQL execution
        previous_spec: Previous JSON SQL specification that failed
    
    Returns:
        Refined JSON SQL specification
    """
    try:
        prompt = f"""
An SQL query failed with an error. Please fix the JSON SQL specification.

Original question: "{original_question}"

Previous specification that failed:
{json.dumps(previous_spec, indent=2)}

Error message:
{sql_error}

Common issues:
- Missing join conditions
- Invalid column names (use exact DB column names; Postgres columns are usually lowercase)
- Incorrect table references
- Missing GROUP BY for aggregated columns
- T016T has only brsch/brtxt columns — NEVER join T016T on VBELN; only join KNA1.brsch = T016T.brsch when question asks about industry
- Do NOT include T016T unless the question asks about industry
- Query returned no rows: remove date filters, use all periods, simplify to fewer joins
- Results include $0 / zero aggregates: add "having": [{{ "lhs": "<metric_alias>", "operator": ">", "rhs": "0" }}]

Return a CORRECTED JSON specification with the same structure.
"""
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        
        content = (response.choices[0].message.content or "").strip()
        try:
            refined_spec = json.loads(content)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", content, re.DOTALL)
            refined_spec = json.loads(m.group(0)) if m else previous_spec
        
        return refined_spec or previous_spec
    
    except Exception as e:
        logger.error(f"Query refinement failed: {e}")
        return previous_spec


def run_sap_sql_agent(
    question: str,
    db: Session,
    knowledge_context: Optional[str] = None,
    max_retries: int = 2,
    time_scope: str = "current",
    few_shot_examples: Optional[List[Dict[str, str]]] = None,
) -> SqlAgentResult | None:
    """
    Main entry point used by the dashboard AI endpoint.

    It:
    - Uses LLM to pick tables (dynamically from DB + mapping; supports new tables)
    - Introspects columns from Postgres
    - Uses LLM to build a JSON SQL spec
    - Translates to Postgres SQL and executes
    - Caches SQL per question

    Args:
        knowledge_context: Optional user preferences (e.g. "For cost queries use EKPO, RBKP, RSEG").
        time_scope: 'current' (recent data), 'historical' (1994-2010), or 'both' (all periods)
    """
    client = _get_openai_client()
    if not client:
        return None

    attempt = 0
    last_error = None
    spec = None
    
    try:
        selected_tables = _pick_tables(question, client, db, knowledge_context)
        column_mappings = _introspect_columns(db, selected_tables)
        if not column_mappings:
            logger.warning("sap_sql_agent: no column mappings found for selected tables %s", selected_tables)
            return None

        table_descriptions = _get_table_descriptions(db)
        spec = _generate_sql_json(
            question,
            selected_tables,
            column_mappings,
            client,
            time_scope=time_scope,
            few_shot_examples=few_shot_examples,
            table_descriptions=table_descriptions,
        )
        if not spec:
            logger.warning("sap_sql_agent: empty JSON spec for question %s", question)
            return None

        _ensure_having_for_aggregates(spec, question)

        # Validate specification
        is_valid, validation_errors = validate_sql_spec(spec)
        if not is_valid:
            logger.warning(f"Invalid SQL spec: {validation_errors}")
            # Try to auto-fix common issues
            if validation_errors and len(validation_errors) < 5:
                logger.info("Attempting to refine specification...")
                spec = refine_query_on_error(client, question, ", ".join(validation_errors), spec)
                is_valid, validation_errors = validate_sql_spec(spec)
        
        # Retry loop for SQL execution
        rows: List[Dict[str, Any]] = []
        sql = ""
        while attempt <= max_retries:
            try:
                sql = _json_to_sql_postgres(spec, column_mappings)
                logger.info(f"📝 Generated SQL:\n{sql}")
                rows = _run_sql(db, sql)

                if rows:
                    logger.info(f"✅ SQL returned {len(rows)} rows")
                    return SqlAgentResult(sql=sql, rows=rows)

                # Query returned no rows — retry with simpler query
                logger.warning(f"⚠️ SQL returned no rows for question: {question}")
                logger.warning(f"📊 SQL query:\n{sql}")
                if attempt < max_retries:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.warning("Query returned 0 rows — refining SQL...")
                    spec = refine_query_on_error(
                        client,
                        question,
                        "Query returned no rows. The database may have historical data (1994-2010) but little recent data. "
                        "Remove date filters, use ALL periods, simplify joins to only essential tables.",
                        spec,
                    )
                    attempt += 1
                    continue
                break

            except Exception as sql_err:
                last_error = str(sql_err)
                logger.warning(f"SQL execution failed (attempt {attempt + 1}/{max_retries + 1}): {last_error}")
                
                if attempt < max_retries:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    logger.info("Refining query specification...")
                    spec = refine_query_on_error(client, question, last_error, spec)
                    attempt += 1
                else:
                    # Max retries reached
                    logger.error(f"Max retries reached for question: {question}")
                    return None

        # ADAPTIVE: If 0 rows and we used "current" (recent) scope, retry once with ALL periods.
        # Works for any question — sales, costs, compare — no hardcoding.
        if not rows and time_scope == "current":
            try:
                db.rollback()
            except Exception:
                pass
            logger.info("Retrying with time_scope='both' (all periods) — adaptive fallback")
            retry_result = run_sap_sql_agent(
                question,
                db,
                knowledge_context=knowledge_context,
                max_retries=1,
                time_scope="both",
                few_shot_examples=few_shot_examples,
            )
            if retry_result and retry_result.rows:
                return retry_result

        return None

    except Exception as e:
        logger.warning("sap_sql_agent failed for question '%s': %s", question, e)
        return None


def answer_with_sap_sql_agent(question: str, db: Session) -> str:
    """
    Convenience wrapper: run the SAP SQL agent and turn its result into a natural language answer.
    """
    client = _get_openai_client()
    if not client:
        return ""

    result = run_sap_sql_agent(question, db)
    if not result or not result.rows:
        return ""

    try:
        summary = _summarize_results(question, result.sql, result.rows, client)
    except Exception as e:
        logger.warning("sap_sql_agent summarization failed: %s", e)
        return ""

    return summary
