"""
Schema loader for schema-driven SAP SQL agent.
Reads database schema and produces a compact text representation for the LLM.
Only includes SAP business tables (excludes app tables like ai_*, zodiac_*, etc.).
Uses sap_table_knowledge.json for table-by-table business context (AUFK, BSAD, BSEG, etc.).
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import inspect
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_TABLE_KNOWLEDGE: Optional[Dict[str, Any]] = None
_SEMANTIC_MAP: Optional[Dict[str, Any]] = None


@lru_cache(maxsize=1)
def _load_schema_ai_config() -> Dict[str, Any]:
    """Load schema_ai_config.json for skip-table rules and other AI hints."""
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "schema_ai_config.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                return raw
    except Exception as e:
        logger.debug("schema_loader: could not load schema_ai_config.json: %s", e)
    return {}


def load_semantic_map() -> Dict[str, Any]:
    """Load sap_semantic_map.json (query intent → table chains) for reliable SQL routing."""
    global _SEMANTIC_MAP
    if _SEMANTIC_MAP is not None:
        return _SEMANTIC_MAP
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_semantic_map.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _SEMANTIC_MAP = json.load(f)
            return _SEMANTIC_MAP or {}
    except Exception as e:
        logger.debug("schema_loader: could not load sap_semantic_map.json: %s", e)
    _SEMANTIC_MAP = {}
    return {}


def _table_available(table: str, available: Set[str]) -> bool:
    """Check if table is in available set (case-insensitive)."""
    if not available:
        return True
    return (table or "").upper() in available


def get_semantic_map_text(available_tables: Optional[List[str]] = None) -> str:
    """
    Return a compact semantic map summary for the LLM (query intent → tables and join chains).
    When available_tables is provided, only references tables that exist in the schema.
    This prevents suggesting MARA, MBEW, etc. when they are not in db_table_mapping.json.
    """
    avail = {t.upper() for t in (available_tables or [])}
    lines = ["SAP semantic map (use ONLY these tables — do not reference tables not listed below):"]

    # Vendor: only if we have the tables
    if not avail or all(_table_available(t, avail) for t in ["LFA1", "LFB1", "LFM1"]):
        lines.append("- Vendor: LFA1 → LFB1 → LFM1 (lifnr)")
    elif _table_available("LFA1", avail):
        lines.append("- Vendor: LFA1 (lifnr)")

    # Customer
    if not avail or any(_table_available(t, avail) for t in ["KNA1", "KNVV", "KNVP"]):
        cust = [t for t in ["KNA1", "KNVV", "KNVP"] if _table_available(t, avail)] if avail else ["KNA1", "KNVV", "KNVP"]
        if cust:
            lines.append(f"- Customer: {' → '.join(cust)} (kunnr)")

    # Material: dynamic — if MARA missing, use sales/purchasing tables instead
    if not avail:
        lines.append("- Material: MARA → MARC → MAKT → MARM (matnr)")
    elif _table_available("MARA", avail):
        mat = [t for t in ["MARA", "MARC", "MAKT", "MARM"] if _table_available(t, avail)]
        if mat:
            lines.append(f"- Material: {' → '.join(mat)} (matnr, mtart)")
    else:
        # No MARA: use VBRP/VBAP + MAKT for product info; LIPS/EKPO for mtart
        alt = []
        if _table_available("VBRP", avail) or _table_available("VBAP", avail):
            alt.append("VBRP/VBAP (matnr)")
        if _table_available("MAKT", avail):
            alt.append("MAKT (matnr, maktx for descriptions)")
        if _table_available("LIPS", avail):
            alt.append("LIPS (mtart for material type)")
        if _table_available("EKPO", avail):
            alt.append("EKPO (mtart)")
        if alt:
            lines.append(f"- Material: {'; '.join(alt)} — use these when MARA is not available")

    # Delivery
    if not avail or all(_table_available(t, avail) for t in ["LIKP", "LIPS"]):
        lines.append("- Delivery: LIKP → LIPS (vbeln)")
    elif _table_available("LIPS", avail):
        lines.append("- Delivery: LIPS (vbeln)")

    # Warehouse
    if not avail or _table_available("LSEG", avail):
        lines.append("- Warehouse: LSEG (matnr, werks, lgort)")

    # Finance/GL
    if not avail or _table_available("FAGLFLEXA", avail):
        lines.append("- Finance/GL: FAGLFLEXA (prctr, rcntr, racct)")

    # Costing
    if not avail or all(_table_available(t, avail) for t in ["KEKO", "KEPH"]):
        lines.append("- Costing: KEKO → KEPH (kalnr)")

    # Purchasing
    if not avail or all(_table_available(t, avail) for t in ["EKKO", "EKPO"]):
        lines.append("- Purchasing: EKKO → EKPO (ebeln); join LFA1 on lifnr")

    # Sales
    if not avail or any(_table_available(t, avail) for t in ["VBAK", "VBAP", "VBRK", "VBRP"]):
        lines.append("- Sales: VBAK → VBAP; VBRK → VBRP (vbeln, matnr, netwr, fkimg)")

    # Controlling
    if not avail or any(_table_available(t, avail) for t in ["COEP", "COSP", "CSKS", "AUFK"]):
        lines.append("- Controlling: COEP, COSP → CSKS (cost center) or AUFK (internal order)")

    return "\n".join(lines)


def load_table_knowledge() -> Dict[str, Any]:
    """Load sap_table_knowledge.json (table -> description, joins, sql_hints, example_questions)."""
    global _TABLE_KNOWLEDGE
    if _TABLE_KNOWLEDGE is not None:
        return _TABLE_KNOWLEDGE
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "sap_table_knowledge.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                _TABLE_KNOWLEDGE = json.load(f)
            return _TABLE_KNOWLEDGE or {}
    except Exception as e:
        logger.debug("schema_loader: could not load sap_table_knowledge.json: %s", e)
    _TABLE_KNOWLEDGE = {}
    return {}

LOWERCASE_SAP_TABLE_ALIASES = {"vbrp"}


def _is_sap_business_table(table_name: str) -> bool:
    """
    Return True for SAP-style business tables and False for app/internal tables.

    Previous logic used a fixed allowlist, which meant newly added SAP tables never
    reached the AI until code was manually updated. We now accept any SAP-style
    uppercase table name from the live schema or mapping file, while still excluding
    explicitly skipped internal tables.
    """
    if not table_name:
        return False

    cfg = _load_schema_ai_config()
    skip_tables = {str(t).lower() for t in (cfg.get("skip_tables") or [])}
    if table_name.lower() in skip_tables:
        return False

    if table_name in LOWERCASE_SAP_TABLE_ALIASES:
        return True

    # SAP tables in this DB are consistently uppercase-style names, including names
    # with digits/underscores such as CE1S_AL, TCKH1, or CKMLPR.
    has_alpha = any(ch.isalpha() for ch in table_name)
    if has_alpha and table_name.upper() == table_name:
        return True

    return False


def load_schema(db: Session, max_columns_per_table: Optional[int] = None) -> Dict[str, List[str]]:
    """
    Load schema from the database: table_name -> list of column names.
    Only includes SAP business tables. Uses SQLAlchemy inspect.
    """
    insp = inspect(db.bind)
    all_tables = insp.get_table_names()
    schema: Dict[str, List[str]] = {}
    for tbl in all_tables:
        if not _is_sap_business_table(tbl):
            continue
        try:
            columns = [c["name"] for c in insp.get_columns(tbl)]
            if columns:
                schema[tbl] = columns[:max_columns_per_table] if max_columns_per_table else columns
        except Exception as e:
            logger.warning("schema_loader: could not get columns for %s: %s", tbl, e)
    return schema


def load_schema_from_mapping_file(max_columns_per_table: Optional[int] = None) -> Dict[str, List[str]]:
    """
    Fallback: load table -> columns from db_table_mapping.json (no DB needed).
    Only SAP business tables.
    """
    schema: Dict[str, List[str]] = {}
    try:
        root = Path(__file__).resolve().parent.parent
        path = root / "db_table_mapping.json"
        if not path.exists():
            return schema
        import json
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return schema
        for table_name, entry in raw.items():
            if not _is_sap_business_table(table_name):
                continue
            if isinstance(entry, dict) and isinstance(entry.get("columns"), dict):
                columns = list(entry["columns"].keys())
                schema[table_name] = columns[:max_columns_per_table] if max_columns_per_table else columns
    except Exception as e:
        logger.warning("schema_loader: could not load db_table_mapping.json: %s", e)
    return schema


def schema_to_text(
    schema: Dict[str, List[str]],
    table_subset: Optional[List[str]] = None,
    include_knowledge: bool = True,
) -> str:
    """
    Convert schema dict to a compact text block for the LLM.
    If include_knowledge is True, appends purpose and sql_hints from sap_table_knowledge.json
    so the agent knows how to use each table (AUFK=internal orders, BSAD=cleared AR, BSEG=FI line items, etc.).
    """
    if table_subset:
        tables = [t for t in table_subset if t in schema]
        if not tables:
            tables = list(schema.keys())
    else:
        tables = list(schema.keys())
    knowledge = load_table_knowledge() if include_knowledge else {}
    parts = []
    for table in sorted(tables, key=lambda x: x.upper()):
        cols = schema.get(table, [])
        col_list = ", ".join(cols[:15])
        line = f"Table: {table}\n  columns: {col_list}"
        # Append table knowledge for this table (match case-insensitively)
        key = (table or "").upper() if isinstance(table, str) else ""
        tk = knowledge.get(table) or knowledge.get(key) or knowledge.get((table or "").lower() if isinstance(table, str) else "")
        if isinstance(tk, dict):
            desc = tk.get("description") or tk.get("business_meaning")
            if desc:
                line += f"\n  purpose: {desc[:300]}"
            hints = tk.get("sql_hints")
            if hints:
                line += f"\n  use: {hints[:280]}"
            joins = tk.get("joins")
            if isinstance(joins, dict) and joins:
                join_str = ", ".join(f"{t2} on {j}" for t2, j in list(joins.items())[:5])
                line += f"\n  joins: {join_str}"
        parts.append(line)
    return "\n".join(parts)


def get_schema_text(
    db: Session,
    table_subset: Optional[List[str]] = None,
    include_semantic_map: bool = True,
) -> str:
    """
    Load schema from DB (or mapping file fallback) and return text for the LLM.
    If include_semantic_map is True, prepends the SAP semantic map (query intent → table chains)
    so the agent can route vendor, delivery, material, finance, etc. questions correctly.
    The semantic map is dynamic: it only references tables that exist in the schema,
    preventing MARA/MBEW etc. from being suggested when they are not in the DB.
    """
    schema = load_schema(db)
    if not schema:
        schema = load_schema_from_mapping_file()
    available_tables = list(schema.keys())
    text = schema_to_text(schema, table_subset)
    if include_semantic_map:
        map_text = get_semantic_map_text(available_tables=available_tables) or ""
        try:
            from .semantic_sql_resolver import get_join_graph_text, get_metrics_text
            jg = get_join_graph_text()
            mt = get_metrics_text()
            if jg:
                map_text += "\n\n" + jg if map_text else jg
            if mt:
                map_text += "\n\n" + mt if map_text else mt
        except ImportError:
            pass
        if map_text:
            text = map_text + "\n\n" + text
    return text


def get_schema_dict(db: Session) -> Dict[str, List[str]]:
    """Return raw schema dict (table -> columns). Used for validation.

    Always merges the live DB schema with db_table_mapping.json so that tables
    present in the mapping file (e.g. ``vbrp`` stored lowercase) are included
    in validation even when the live DB session cannot see them directly.
    The live DB takes precedence for any table that appears in both sources.
    """
    schema = load_schema(db)
    mapping_schema = load_schema_from_mapping_file()
    # Fill in tables that are in the mapping file but missing from the live schema
    for table, cols in mapping_schema.items():
        if table not in schema:
            schema[table] = cols
    return schema
