"""Read current schema metadata without reading business rows."""
from __future__ import annotations

import logging
from typing import Any, Dict
from sqlalchemy import text

logger = logging.getLogger("zodiac-api.live_schema")


def _rows_to_schema(rows) -> Dict[str, Any]:
    schema: Dict[str, Any] = {}
    for row in rows or []:
        schema.setdefault(str(row["table_name"]), []).append(
            {"col": str(row["column_name"]), "type": str(row["data_type"])}
        )
    return schema


def load_live_schema(db: Any, fallback: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    """Prefer live information_schema; keep a usable fallback when remote catalog is empty or times out."""
    try:
        rows = db.execute(text(
            "SELECT table_name, column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position"
        )).mappings().all()
        schema = _rows_to_schema(rows)
        # SAP extracts sometimes land in public while search_path/current_schema is empty.
        if not schema:
            rows = db.execute(text(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public' ORDER BY table_name, ordinal_position"
            )).mappings().all()
            schema = _rows_to_schema(rows)
        if schema:
            return schema, "live_database_metadata"
        if fallback:
            logger.warning(
                "Live schema empty for current_schema()/public; using schema snapshot fallback (%s tables)",
                len(fallback),
            )
            return fallback, "schema_snapshot"
        return {}, "live_database_metadata"
    except Exception as exc:
        logger.warning("Live schema introspection failed (%s); using schema snapshot fallback", type(exc).__name__)
        try:
            db.rollback()
        except Exception:
            pass
        return fallback or {}, "schema_snapshot"
