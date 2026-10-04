"""Generic join-path discovery and cardinality safety for analytical SQL.

Supports multi-hop relationship resolution across the approved join graph.
Rejects paths that would silently multiply fact rows under aggregation.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ..data_catalog.physical import has_column, has_table, resolve_table_name
from .join_planner_v2 import find_join_path

# Dimension-side tables that are typically N:1 from transactional facts.
_SAFE_DIMENSION_TABLES = frozenset({
    "KNA1", "LFA1", "MAKT", "MARA", "T001W", "T001", "T016T", "CEPC",
})
# Tables known to be historical / multi-row per entity (fan-out risk).
_FANOUT_RISK_TABLES = frozenset({
    "ADRC", "ADR6", "ADR2", "BUT020", "BUT021", "CDHDR", "CDPOS",
    "VBPA",  # multiple partners per document
})


def normalize_table(name: str) -> str:
    return (resolve_table_name(name) or name or "").upper()


def discover_join_path(start: str, target: str) -> Optional[List[Any]]:
    """BFS multi-hop path across approved edges (unlimited hop count)."""
    s, t = normalize_table(start), normalize_table(target)
    if not s or not t or not has_table(s) or not has_table(t):
        return None
    return find_join_path(s, t)


def path_tables(path: Sequence[Any]) -> List[str]:
    tables: List[str] = []
    seen: Set[str] = set()
    for edge in path or []:
        for t in (getattr(edge, "left_table", ""), getattr(edge, "right_table", "")):
            u = normalize_table(str(t))
            if u and u not in seen:
                seen.add(u)
                tables.append(u)
    return tables


def assess_join_cardinality(
    fact_table: str,
    path: Sequence[Any],
    *,
    aggregation: bool = True,
) -> Dict[str, Any]:
    """Evaluate whether joining along `path` from a fact table is safe.

    Returns:
      {
        "safe": bool,
        "reason": str,
        "risk": "none"|"1:N"|"N:N"|"ambiguous"|"fanout_history",
        "intermediate_tables": [...],
      }
    """
    fact = normalize_table(fact_table)
    intermediates = path_tables(path)
    if not path:
        return {
            "safe": True,
            "reason": "same table / no join",
            "risk": "none",
            "intermediate_tables": [],
        }

    for t in intermediates:
        if t in _FANOUT_RISK_TABLES and aggregation:
            return {
                "safe": False,
                "reason": (
                    f"Join path includes {t}, which can multiply fact rows "
                    "(historical/multi-valued). Aggregation would be inflated."
                ),
                "risk": "fanout_history",
                "intermediate_tables": intermediates,
            }

    # Prefer fact → dimension (N:1). If every non-fact hop is a known dimension, accept.
    dims = [t for t in intermediates if t != fact]
    if dims and all(t in _SAFE_DIMENSION_TABLES for t in dims):
        return {
            "safe": True,
            "reason": "fact to dimension path (N:1 expected)",
            "risk": "none",
            "intermediate_tables": intermediates,
        }

    # Unknown intermediates with aggregation → reject rather than guess.
    if aggregation and dims and any(t not in _SAFE_DIMENSION_TABLES for t in dims):
        unknown = [t for t in dims if t not in _SAFE_DIMENSION_TABLES]
        return {
            "safe": False,
            "reason": (
                f"Ambiguous join cardinality via {', '.join(unknown)}; "
                "refusing to risk duplicate fact multiplication."
            ),
            "risk": "ambiguous",
            "intermediate_tables": intermediates,
        }

    return {
        "safe": True,
        "reason": "approved path",
        "risk": "none",
        "intermediate_tables": intermediates,
    }


def ensure_connected_tables(selected: Sequence[str]) -> Tuple[List[str], List[str]]:
    """Insert intermediate tables so the selected set is join-connected.

    Returns (expanded_tables, relationship_on_clauses).
    """
    tables = [normalize_table(t) for t in selected if t and has_table(t)]
    if len(tables) <= 1:
        return tables, []

    expanded: List[str] = list(tables)
    seen = {t.upper() for t in expanded}
    relationships: List[str] = []

    # Connect each subsequent table to the first via BFS path.
    base = expanded[0]
    for tgt in list(expanded[1:]):
        path = discover_join_path(base, tgt)
        if not path:
            # Try connecting to any already-expanded table.
            path = None
            for src in expanded:
                path = discover_join_path(src, tgt)
                if path is not None:
                    break
        if not path:
            continue
        assessment = assess_join_cardinality(base, path, aggregation=True)
        if not assessment["safe"]:
            continue
        for edge in path:
            lt = normalize_table(getattr(edge, "left_table", ""))
            rt = normalize_table(getattr(edge, "right_table", ""))
            on = str(getattr(edge, "on_template", "") or "")
            for t in (lt, rt):
                if t and t not in seen and has_table(t):
                    seen.add(t)
                    expanded.append(t)
            if on and on not in relationships:
                relationships.append(on)

    return expanded, relationships


def resolve_transactional_geo_column(
    fact_candidates: Sequence[str] = ("VBRK", "VBAK", "EKKO", "RBKP"),
    geo_cols: Sequence[str] = ("land1", "landx", "country"),
) -> Optional[Dict[str, str]]:
    """Find a country/geo column on a transactional fact table (not master-only)."""
    for fact in fact_candidates:
        if not has_table(fact):
            continue
        for col in geo_cols:
            if has_column(fact, col):
                resolved = resolve_table_name(fact) or fact
                return {"table": resolved, "column": col, "grain": "transaction"}
    return None


def resolve_master_geo_column(
    master_candidates: Sequence[str] = ("KNA1", "LFA1", "T001W"),
    geo_cols: Sequence[str] = ("land1", "landx", "country"),
) -> Optional[Dict[str, str]]:
    for master in master_candidates:
        if not has_table(master):
            continue
        for col in geo_cols:
            if has_column(master, col):
                resolved = resolve_table_name(master) or master
                return {"table": resolved, "column": col, "grain": "master"}
    return None
