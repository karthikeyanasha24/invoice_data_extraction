"""
Single source of truth for table relationships (join graph).

Static relationship physics:
- approved table edges
- approved ON predicate templates
- approved join key pairs
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


@dataclass(frozen=True)
class JoinEdge:
    left_table: str
    right_table: str
    on_template: str
    role: str = ""
    cardinality: str = ""


def _service_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _clean_identifier(value: str) -> str:
    return (value or "").strip().strip('"')


def _parse_join_rule_pairs(rule_sql: str) -> Set[frozenset[str]]:
    pairs: Set[frozenset[str]] = set()
    eq_pattern = re.compile(
        r'([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)',
        re.IGNORECASE,
    )
    for m in eq_pattern.finditer(rule_sql or ""):
        left_col = _clean_identifier(m.group(2)).upper()
        right_col = _clean_identifier(m.group(4)).upper()
        if left_col and right_col:
            pairs.add(frozenset({left_col, right_col}))
    return pairs


@lru_cache(maxsize=1)
def load_join_graph() -> List[JoinEdge]:
    path = _service_root() / "schema_ai_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    out: List[JoinEdge] = []
    for rule in (data.get("join_rules") or []):
        left = _clean_identifier(str(rule.get("left") or "")).upper()
        right = _clean_identifier(str(rule.get("right") or "")).upper()
        on_t = str(rule.get("on") or "").strip()
        if not left or not right or not on_t:
            continue
        note = str(rule.get("note") or "")
        role = ""
        if "header" in note.lower() and "item" in note.lower():
            role = "header_line"
        elif "master" in note.lower():
            role = "lookup"
        out.append(JoinEdge(left_table=left, right_table=right, on_template=on_t, role=role))
    return out


@lru_cache(maxsize=1)
def allowed_table_edges() -> Set[frozenset[str]]:
    return {frozenset({e.left_table, e.right_table}) for e in load_join_graph()}


@lru_cache(maxsize=1)
def allowed_join_column_pairs() -> Dict[frozenset[str], Set[frozenset[str]]]:
    allowed: Dict[frozenset[str], Set[frozenset[str]]] = {}
    for e in load_join_graph():
        key = frozenset({e.left_table, e.right_table})
        allowed.setdefault(key, set()).update(_parse_join_rule_pairs(e.on_template))
    return allowed


def join_hints_for_tables(tables: List[str]) -> str:
    if not tables:
        return ""
    table_set = {str(t).upper() for t in tables}
    lines: List[str] = []
    for e in load_join_graph():
        if e.left_table in table_set and e.right_table in table_set:
            lines.append(f"- {e.left_table} ↔ {e.right_table}: ON {e.on_template}")
    if not lines:
        return ""
    return "Approved join paths (use only these edges/predicates):\n" + "\n".join(lines)


def tables_linked_to_graph(tables: List[str]) -> bool:
    """
    True when all tables are connected through approved graph edges (or 0/1 table).
    """
    uniq = sorted({str(t).upper() for t in (tables or []) if t})
    if len(uniq) <= 1:
        return True
    edges = allowed_table_edges()
    neighbor: Dict[str, Set[str]] = {t: set() for t in uniq}
    for e in edges:
        nodes = sorted(e)
        if len(nodes) != 2:
            continue
        a, b = nodes[0], nodes[1]
        if a in neighbor and b in neighbor:
            neighbor[a].add(b)
            neighbor[b].add(a)
    seen: Set[str] = set()
    stack: List[str] = [uniq[0]]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(list(neighbor.get(n, set()) - seen))
    return len(seen) == len(uniq)

