"""
Schema loader for schema-driven SAP SQL agent.
Reads database schema and produces a compact text representation for the LLM.
Only includes SAP business tables (excludes app tables like ai_*, zodiac_*, etc.).
Uses sap_table_knowledge.json for table-by-table business context (AUFK, BSAD, BSEG, etc.).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import inspect
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_TABLE_KNOWLEDGE: Optional[Dict[str, Any]] = None
_SEMANTIC_MAP: Optional[Dict[str, Any]] = None


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


def get_semantic_map_text() -> str:
    """Return a compact semantic map summary for the LLM (query intent → tables and join chains)."""
    data = load_semantic_map()
    if not data:
        return ""
    concepts = data.get("concepts") or {}
    lines = [
        "SAP semantic map (use for routing questions to the right tables and joins):",
        "- Vendor: LFA1 → LFB1 → LFM1 (lifnr)",
        "- Customer: KNA1 → KNVV → KNVP (kunnr)",
        "- Material: MARA → MARC → MAKT → MARM (matnr)",
        "- Delivery: LIKP → LIPS (vbeln)",
        "- Warehouse: LSEG (matnr, werks, lgort)",
        "- Finance/GL: FAGLFLEXA (prctr, rcntr, racct)",
        "- Costing: KEKO → KEPH (kalnr)",
        "- Purchasing: EKKO → EKPO (ebeln); join LFA1 on lifnr",
        "- Sales: VBAK → VBAP; VBRK → VBRP",
        "- Controlling: COEP, COSP → CSKS (cost center) or AUFK (internal order)",
    ]
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

# SAP business tables we care about (from list_tables). Exclude app/system tables.
# Tables not in this set are excluded when building schema for the LLM.
SAP_BUSINESS_TABLE_PREFIXES = (
    "AUFK", "BSAD", "BSEG", "CEPC", "CKHS", "CKIS", "CKIT", "CKMLCR", "CKMLHD", "CKMLPP",
    "COEP", "COSP", "CRHD", "CSKS", "EBAN", "EKKO", "EKPO", "FAGLFLEXA", "KEKO", "KEPH",
    "KNA1", "KNVP", "KNVV", "KONV", "LFA1", "LFB1", "LFM1", "LIKP", "LIPS", "LSEG",
    "MARA", "MAKT", "MARC", "MARM", "MEAN", "MKPF", "MVKE", "RBKP", "RESB", "RSEG",
    "STKO", "STPO", "T016T", "VBAK", "VBAP", "VBEP", "VBFA", "VBRK", "VBRP",
)
# Allow lowercase vbrp as seen in DB
SAP_BUSINESS_TABLES_SET: Set[str] = {t.upper() for t in SAP_BUSINESS_TABLE_PREFIXES}
# Add lowercase variants for tables that may exist as lowercase (e.g. vbrp)
SAP_BUSINESS_TABLES_SET.add("VBRP")


def _is_sap_business_table(table_name: str) -> bool:
    """Return True if table is an SAP business table we want to expose to the LLM."""
    if not table_name:
        return False
    upper = table_name.upper()
    if upper in SAP_BUSINESS_TABLES_SET:
        return True
    # Allow any table whose uppercase form is in the set
    for known in SAP_BUSINESS_TABLE_PREFIXES:
        if upper == known.upper():
            return True
    return False


def load_schema(db: Session, max_columns_per_table: int = 15) -> Dict[str, List[str]]:
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
                schema[tbl] = columns[:max_columns_per_table]
        except Exception as e:
            logger.warning("schema_loader: could not get columns for %s: %s", tbl, e)
    return schema


def load_schema_from_mapping_file() -> Dict[str, List[str]]:
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
                schema[table_name] = list(entry["columns"].keys())[:15]
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
    """
    schema = load_schema(db)
    if not schema:
        schema = load_schema_from_mapping_file()
    text = schema_to_text(schema, table_subset)
    if include_semantic_map:
        map_text = get_semantic_map_text() or ""
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
    """Return raw schema dict (table -> columns). Used for validation."""
    schema = load_schema(db)
    if not schema:
        schema = load_schema_from_mapping_file()
    return schema
