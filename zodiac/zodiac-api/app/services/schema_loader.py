"""
Schema loader for schema-driven SAP SQL agent.
Reads database schema and produces a compact text representation for the LLM.
Only includes SAP business tables (excludes app tables like ai_*, zodiac_*, etc.).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from sqlalchemy import inspect
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# SAP business tables we care about (from list_tables). Exclude app/system tables.
# Tables not in this set are excluded when building schema for the LLM.
SAP_BUSINESS_TABLE_PREFIXES = (
    "AUFK", "BSAD", "BSEG", "CEPC", "CKHS", "CKIS", "CKIT", "CKMLCR", "CKMLHD", "CKMLPP",
    "COEP", "COSP", "CRHD", "CSKS", "EBAN", "EKKO", "EKPO", "FAGLFLEXA", "KEKO", "KEPH",
    "KNA1", "KNVP", "KNVV", "KONV", "LFA1", "LFB1", "LFM1", "LIKP", "LIPS", "LSEG",
    "MAKT", "MARC", "MARM", "MEAN", "MKPF", "MVKE", "RBKP", "RESB", "RSEG",
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


def schema_to_text(schema: Dict[str, List[str]], table_subset: Optional[List[str]] = None) -> str:
    """
    Convert schema dict to a compact text block for the LLM.
    Format:
      Table: TABLE_NAME
      columns: col1, col2, col3, ...
    """
    if table_subset:
        tables = [t for t in table_subset if t in schema]
        if not tables:
            tables = list(schema.keys())
    else:
        tables = list(schema.keys())
    parts = []
    for table in sorted(tables, key=lambda x: x.upper()):
        cols = schema.get(table, [])
        col_list = ", ".join(cols[:15])
        parts.append(f"Table: {table}\n  columns: {col_list}")
    return "\n".join(parts)


def get_schema_text(db: Session, table_subset: Optional[List[str]] = None) -> str:
    """
    Load schema from DB (or mapping file fallback) and return text for the LLM.
    """
    schema = load_schema(db)
    if not schema:
        schema = load_schema_from_mapping_file()
    return schema_to_text(schema, table_subset)


def get_schema_dict(db: Session) -> Dict[str, List[str]]:
    """Return raw schema dict (table -> columns). Used for validation."""
    schema = load_schema(db)
    if not schema:
        schema = load_schema_from_mapping_file()
    return schema
