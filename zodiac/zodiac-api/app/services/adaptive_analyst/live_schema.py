"""Read current schema metadata without reading business rows."""
from __future__ import annotations

from typing import Any, Dict
from sqlalchemy import text


def load_live_schema(db: Any, fallback: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    try:
        rows = db.execute(text(
            'SELECT table_name, column_name, data_type FROM information_schema.columns '
            'WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position'
        )).mappings().all()
        if not isinstance(rows, list) or not rows:
            return fallback, 'schema_snapshot'
        schema: Dict[str, Any] = {}
        for row in rows:
            schema.setdefault(str(row['table_name']), []).append(
                {'col': str(row['column_name']), 'type': str(row['data_type'])})
        return schema, 'live_database_metadata'
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return fallback, 'schema_snapshot'
