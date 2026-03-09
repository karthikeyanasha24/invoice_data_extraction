import json
from pathlib import Path
from typing import Any, Dict


# Path to the merged table mapping used by the AI
TABLE_MAP_PATH = Path(__file__).resolve().parent.parent / "db_table_mapping.json"


def load_schema() -> Dict[str, Any]:
    """Load the full table mapping JSON."""
    with TABLE_MAP_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_schema_context() -> str:
    """
    Build a prompt-friendly schema description from db_table_mapping.json.

    Format (per line):
      TABLE_NAME: col1, col2, col3, ...
    """
    schema = load_schema()

    parts = []
    for table, info in schema.items():
        if not isinstance(info, dict):
            continue
        cols_dict = info.get("columns") or {}
        if not isinstance(cols_dict, dict) or not cols_dict:
            continue

        col_names = list(cols_dict.keys())
        col_list = ", ".join(col_names)
        parts.append(f"{table}: {col_list}")

    return "\n".join(parts)

