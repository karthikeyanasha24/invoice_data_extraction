"""
Join planner v2: schema-aware join path planning using the approved join graph.

This is deterministic and does not guess joins outside schema_ai_config.json join_rules.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from .join_graph import JoinEdge, preferred_join_graph


@dataclass(frozen=True)
class JoinStep:
    left_table: str
    right_table: str
    on_sql: str
    join_type: str = "INNER"


def _neighbors(edges: List[JoinEdge]) -> Dict[str, Set[str]]:
    n: Dict[str, Set[str]] = {}
    for e in edges:
        n.setdefault(e.left_table, set()).add(e.right_table)
        n.setdefault(e.right_table, set()).add(e.left_table)
    return n


def find_join_path(start_table: str, target_table: str) -> Optional[List[JoinEdge]]:
    """
    BFS multi-hop join path across approved edges.
    Returns list of JoinEdge in traversal order.
    """
    s = (start_table or "").upper()
    t = (target_table or "").upper()
    if not s or not t:
        return None
    if s == t:
        return []
    for include_low in (False, True):
        edges = preferred_join_graph(include_low_confidence=include_low)
        neigh = _neighbors(edges)
        q = deque([(s, [])])
        seen: Set[str] = set()
        while q:
            cur, path = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in neigh.get(cur, set()):
                if nxt in seen:
                    continue
                edge = _edge_between(edges, cur, nxt)
                if edge is None:
                    continue
                new_path = path + [edge]
                if nxt == t:
                    return new_path
                q.append((nxt, new_path))
    return None


def _edge_between(edges: List[JoinEdge], a: str, b: str) -> Optional[JoinEdge]:
    au, bu = a.upper(), b.upper()
    for e in edges:
        if e.left_table == au and e.right_table == bu:
            return e
        if e.left_table == bu and e.right_table == au:
            return e
    return None


def render_join_sql(path: List[JoinEdge], base_alias: Dict[str, str]) -> str:
    """
    Render JOIN clauses for a path with stable aliases.
    `base_alias` maps table -> alias (e.g. {"VBRP":"t0","VBRK":"t1"}).

    JoinEdge.on_template is of form "VBRP.VBELN = VBRK.VBELN" (no aliases).
    We rewrite table qualifiers to aliases.
    """
    if not path:
        return ""
    joins: List[str] = []
    for e in path:
        lt, rt = e.left_table.upper(), e.right_table.upper()
        la = base_alias.get(lt, lt.lower())
        ra = base_alias.get(rt, rt.lower())
        on_sql = e.on_template
        # Replace strict qualifiers
        on_sql = on_sql.replace(f"{lt}.", f"{la}.").replace(f"{rt}.", f"{ra}.")
        joins.append(f"INNER JOIN {rt} {ra} ON {on_sql}")
    return "\n".join(joins)

