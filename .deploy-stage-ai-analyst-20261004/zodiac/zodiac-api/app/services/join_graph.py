"""
Single source of truth for table relationships (join graph).

Static relationship physics:
- approved table edges
- approved ON predicate templates
- approved join key pairs
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from itertools import combinations

from .schema_index import build_canonical_schema_index

logger = logging.getLogger("zodiac-api.join-graph")
_join_graph_mode_logged = False


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


_COMPOSITE_KEY_PRIORITY: List[Tuple[str, ...]] = [
    ("BELNR", "GJAHR", "BUKRS"),
    ("VBELN", "POSNR"),
    ("EBELN", "EBELP"),
    ("MATNR", "WERKS"),
    ("VKORG", "VTWEG"),
]

_SINGLE_KEY_PRIORITY: List[str] = [
    "VBELN",
    "MATNR",
    "KUNNR",
    "LIFNR",
    "EBELN",
    "KALNR",
    "AUFNR",
    "OBJNR",
    "PRCTR",
    "KOSTL",
]

_ID_LIKE_COLUMN_PATTERNS: List[str] = [
    r".*ID$",
    r".*NR$",
    r".*NUM$",
    r".*NO$",
    r".*KEY$",
    r".*CODE$",
]

_SOFT_COMMON_COLUMNS: Set[str] = {
    "MANDT",
    "BUKRS",
    "WERKS",
    "VKORG",
    "VTWEG",
    "SPART",
    "LAND1",
    "WAERK",
}

_MAX_ADAPTIVE_TEMPLATES_PER_PAIR = 48

_EQUIVALENT_KEY_GROUPS: List[Tuple[str, ...]] = [
    ("KUNNR", "CUSTOMER_ID", "CUST_ID", "CLIENT_ID"),
    ("LIFNR", "VENDOR_ID", "SUPPLIER_ID"),
    ("VBELN", "INVOICE_ID", "BILLING_DOC_ID", "DOCUMENT_ID"),
    ("MATNR", "MATERIAL_ID", "PRODUCT_ID", "ITEM_ID"),
    ("EBELN", "PO_ID", "PURCHASE_ORDER_ID"),
    ("BELNR", "ACCOUNTING_DOC_ID", "FI_DOCUMENT_ID"),
    ("BUKRS", "COMPANY_CODE", "COMPANY_ID"),
    ("WERKS", "PLANT_ID"),
    ("PRCTR", "PROFIT_CENTER", "PROFIT_CENTER_ID"),
    ("KOSTL", "COST_CENTER", "COST_CENTER_ID"),
]


def _quoted_table_identifier(table_name: str) -> str:
    t = (table_name or "").strip()
    if not t:
        return t
    if t == t.lower():
        return t
    return f'"{t}"'


def _is_id_like_column(col: str) -> bool:
    c = (col or "").upper()
    if not c:
        return False
    if c in _SINGLE_KEY_PRIORITY:
        return True
    return any(re.match(p, c) for p in _ID_LIKE_COLUMN_PATTERNS)


def _adaptive_mode() -> str:
    mode = (os.getenv("JOIN_GRAPH_ADAPTIVE_MODE", "max") or "max").strip().lower()
    if mode in {"strict", "balanced", "max", "exhaustive"}:
        return mode
    return "max"


def _mode_template_limit() -> int:
    mode = _adaptive_mode()
    if mode == "strict":
        return min(16, _MAX_ADAPTIVE_TEMPLATES_PER_PAIR)
    if mode == "balanced":
        return min(32, _MAX_ADAPTIVE_TEMPLATES_PER_PAIR)
    if mode == "exhaustive":
        # Effectively uncapped for practical workloads.
        return 1_000_000
    return _MAX_ADAPTIVE_TEMPLATES_PER_PAIR


def _mode_max_combo_size() -> int:
    mode = _adaptive_mode()
    if mode == "strict":
        return 3
    if mode == "balanced":
        return 4
    if mode == "exhaustive":
        # Use full id-like pool length.
        return 99
    return 5


def _infer_composite_from_common(common: Set[str]) -> Optional[Tuple[str, ...]]:
    """
    Infer a composite join key from shared columns when known priority groups
    don't match. This enables broader adaptive joins for app tables too.
    """
    candidates = [c for c in common if _is_id_like_column(c) or c in _SOFT_COMMON_COLUMNS]
    if len(candidates) < 2:
        return None
    scored = sorted(
        candidates,
        key=lambda c: (
            0 if c in _SINGLE_KEY_PRIORITY else 1,
            0 if _is_id_like_column(c) else 1,
            len(c),
            c,
        ),
    )
    # Keep composites compact to reduce noisy joins.
    return tuple(scored[: min(3, len(scored))])


def _equivalent_cross_matches(left_cols: Set[str], right_cols: Set[str]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for grp in _EQUIVALENT_KEY_GROUPS:
        left_hits = [c for c in grp if c in left_cols]
        right_hits = [c for c in grp if c in right_cols]
        for l in left_hits:
            for r in right_hits:
                if l == r:
                    continue
                out.append((l, r))
    # deterministic ordering
    return sorted(set(out), key=lambda x: (len(x[0]) + len(x[1]), x[0], x[1]))


def _infer_on_templates_for_tables(left: str, right: str, left_cols: Set[str], right_cols: Set[str]) -> List[str]:
    common = left_cols & right_cols
    if not common:
        return []
    max_templates = _mode_template_limit()
    max_combo = _mode_max_combo_size()
    templates: List[str] = []
    seen: Set[str] = set()
    for grp in _COMPOSITE_KEY_PRIORITY:
        if all(k in common for k in grp):
            t = " AND ".join([f"{left}.{k} = {right}.{k}" for k in grp])
            if t not in seen:
                seen.add(t)
                templates.append(t)
    for k in _SINGLE_KEY_PRIORITY:
        if k in common:
            t = f"{left}.{k} = {right}.{k}"
            if t not in seen:
                seen.add(t)
                templates.append(t)
    inferred = _infer_composite_from_common(common)
    if inferred:
        t = " AND ".join([f"{left}.{k} = {right}.{k}" for k in inferred])
        if t not in seen:
            seen.add(t)
            templates.append(t)
    id_like_common = sorted([c for c in common if _is_id_like_column(c)], key=lambda c: (len(c), c))
    if id_like_common:
        k = id_like_common[0]
        t = f"{left}.{k} = {right}.{k}"
        if t not in seen:
            seen.add(t)
            templates.append(t)
    # Last-resort adaptive mode for app tables: join on one stable shared dimension.
    # Avoid ultra-generic columns that cause noisy joins.
    soft_common = sorted([c for c in common if c in _SOFT_COMMON_COLUMNS], key=lambda c: (len(c), c))
    if soft_common:
        k = soft_common[0]
        t = f"{left}.{k} = {right}.{k}"
        if t not in seen:
            seen.add(t)
            templates.append(t)
    for lcol, rcol in _equivalent_cross_matches(left_cols, right_cols):
        t = f"{left}.{lcol} = {right}.{rcol}"
        if t not in seen:
            seen.add(t)
            templates.append(t)
        if len(templates) >= max_templates:
            break
    # Extra adaptive coverage: add additional id-like composite options.
    id_like_pool = sorted(
        [c for c in common if _is_id_like_column(c) and c not in {"MANDT"}],
        key=lambda c: (0 if c in _SINGLE_KEY_PRIORITY else 1, len(c), c),
    )
    if _adaptive_mode() != "exhaustive":
        # Keep bounded in non-exhaustive modes.
        id_like_pool = id_like_pool[:8]
    for k in id_like_pool:
        t = f"{left}.{k} = {right}.{k}"
        if t not in seen:
            seen.add(t)
            templates.append(t)
        if len(templates) >= max_templates:
            break
    max_k = min(max_combo, len(id_like_pool))
    # In exhaustive mode, generate all combinations across the full id-like pool.
    # In non-exhaustive modes, cap pool for larger k to control size.
    for k in range(2, max_k + 1):
        pool = id_like_pool if _adaptive_mode() == "exhaustive" else id_like_pool[: min(len(id_like_pool), 5 + k)]
        for grp in combinations(pool, k):
            t = " AND ".join([f"{left}.{col} = {right}.{col}" for col in grp])
            if t not in seen:
                seen.add(t)
                templates.append(t)
            if len(templates) >= max_templates:
                break
        if len(templates) >= max_templates:
            break
    return templates[:max_templates]


def _confidence_for_template(on_template: str) -> float:
    pairs = _parse_join_rule_pairs(on_template)
    if not pairs:
        return 0.5
    cols = sorted({c for p in pairs for c in p})
    score = 0.0
    for grp in _COMPOSITE_KEY_PRIORITY:
        if all(k in cols for k in grp):
            score += 4.2
    # High-value SAP business keys should carry stronger confidence.
    primary_business_keys = {"VBELN", "MATNR", "KUNNR", "LIFNR", "EBELN", "BELNR", "BUKRS", "GJAHR"}
    if any(k in cols for k in primary_business_keys):
        score += 0.9
    for c in cols:
        if c in _SINGLE_KEY_PRIORITY:
            score += 1.35
        elif _is_id_like_column(c):
            score += 0.95
        elif c in _SOFT_COMMON_COLUMNS:
            score += 0.3
    # Multiple pair predicates in ON typically indicate stronger relationship quality.
    score += min(2.4, len(pairs) * 0.45)
    return round(score, 2)


def _confidence_from_edge(edge: JoinEdge) -> float:
    card = (edge.cardinality or "").strip().lower()
    m = re.search(r"conf:([0-9]+(?:\.[0-9]+)?)", card)
    if m:
        try:
            return float(m.group(1))
        except Exception:
            return 0.0
    return 0.0


def is_low_confidence_adaptive_edge(edge: JoinEdge) -> bool:
    role = (edge.role or "").lower()
    return "adaptive_inferred_low" in role


def preferred_join_graph(include_low_confidence: bool = False) -> List[JoinEdge]:
    """
    Preferred planning graph for deterministic join routing.
    By default excludes low-confidence adaptive edges and keeps explicit/high/medium first.
    """
    edges = list(load_join_graph())
    if not include_low_confidence:
        edges = [e for e in edges if not is_low_confidence_adaptive_edge(e)]
    def _sort_key(e: JoinEdge) -> Tuple[int, float, str, str, str]:
        r = (e.role or "").lower()
        if "adaptive" not in r:
            pri = 0
        elif "high" in r:
            pri = 1
        elif "medium" in r:
            pri = 2
        else:
            pri = 3
        return (pri, -_confidence_from_edge(e), e.left_table, e.right_table, e.on_template)
    return sorted(edges, key=_sort_key)


@lru_cache(maxsize=1)
def _build_adaptive_join_edges() -> List[JoinEdge]:
    """
    Infer safe join candidates from table metadata so the graph can adapt as tables grow.
    We only infer joins on strong SAP keys (VBELN/MATNR/KUNNR/... or trusted composites),
    and never replace explicit rules from schema_ai_config.json.
    """
    idx = build_canonical_schema_index(include_non_sap=True)
    table_cols: Dict[str, Set[str]] = {}
    for t in idx.tables.values():
        table_cols[t.name] = {str(c.name or "").upper() for c in (t.columns or []) if c and c.name}

    table_names = sorted(table_cols.keys(), key=lambda x: x.upper())
    out: List[JoinEdge] = []
    for i in range(len(table_names)):
        left_actual = table_names[i]
        left_upper = left_actual.upper()
        left_cols = table_cols.get(left_actual) or set()
        if not left_cols:
            continue
        for j in range(i + 1, len(table_names)):
            right_actual = table_names[j]
            right_upper = right_actual.upper()
            right_cols = table_cols.get(right_actual) or set()
            if not right_cols:
                continue
            on_templates = _infer_on_templates_for_tables(
                _quoted_table_identifier(left_actual),
                _quoted_table_identifier(right_actual),
                left_cols,
                right_cols,
            )
            if not on_templates:
                continue
            for on_t in on_templates:
                conf = _confidence_for_template(on_t)
                if conf >= 3.0:
                    role = "adaptive_inferred_high"
                elif conf >= 1.5:
                    role = "adaptive_inferred_medium"
                else:
                    role = "adaptive_inferred_low"
                out.append(
                    JoinEdge(
                        left_table=left_upper,
                        right_table=right_upper,
                        on_template=on_t,
                        role=role,
                        cardinality=f"conf:{conf}",
                    )
                )
    return out


@lru_cache(maxsize=1)
def load_join_graph() -> List[JoinEdge]:
    global _join_graph_mode_logged
    path = _service_root() / "schema_ai_config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    out: List[JoinEdge] = []
    explicit_pairs: Set[frozenset[str]] = set()
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
        explicit_pairs.add(frozenset({left, right}))

    # Add adaptive inferred edges for broader SAP + app coverage.
    # Keep explicit rules first in list (priority), but also keep inferred alternatives
    # for the same pair so the graph can adapt to more query variants.
    for e in _build_adaptive_join_edges():
        pair = frozenset({e.left_table, e.right_table})
        if pair in explicit_pairs:
            e = JoinEdge(
                left_table=e.left_table,
                right_table=e.right_table,
                on_template=e.on_template,
                role=f"{e.role}_secondary",
                cardinality=e.cardinality,
            )
        out.append(e)
    if not _join_graph_mode_logged:
        mode = _adaptive_mode()
        adaptive_count = sum(1 for e in out if (e.role or "").startswith("adaptive_inferred"))
        logger.info(
            "Join graph mode active: %s (total_edges=%d, adaptive_edges=%d)",
            mode,
            len(out),
            adaptive_count,
        )
        _join_graph_mode_logged = True
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
    table_roles: Dict[str, str] = {
        "VBRP": "transaction_line",
        "VBRK": "transaction_header",
        "EKPO": "transaction_line",
        "EKKO": "transaction_header",
        "RBKP": "transaction_header",
        "RSEG": "transaction_line",
        "BSEG": "transaction_line",
        "FAGLFLEXA": "transaction_line",
        "MARA": "master_data",
        "MAKT": "text_master",
        "MARC": "master_data_plant",
        "MVKE": "master_data_sales_area",
        "MEAN": "master_data_barcode",
        "KNA1": "master_data",
        "LFA1": "master_data",
        "CEPC": "master_data",
    }
    role_lines: List[str] = []
    for t in sorted(table_set):
        role = table_roles.get(t)
        if role:
            role_lines.append(f"- {t}: {role}")
    matching_edges: List[JoinEdge] = []
    for e in load_join_graph():
        if e.left_table in table_set and e.right_table in table_set:
            matching_edges.append(e)
    def _edge_priority(e: JoinEdge) -> Tuple[int, float]:
        r = (e.role or "").lower()
        if "adaptive" not in r:
            return (0, _confidence_from_edge(e))  # explicit/config edges first
        if "high" in r:
            return (1, _confidence_from_edge(e))
        if "medium" in r:
            return (2, _confidence_from_edge(e))
        return (3, _confidence_from_edge(e))
    matching_edges.sort(key=lambda e: (_edge_priority(e)[0], -_edge_priority(e)[1], e.left_table, e.right_table, e.on_template))
    for e in matching_edges:
        conf = _confidence_from_edge(e)
        conf_txt = f" [conf={conf:.2f}]" if conf > 0 else ""
        lines.append(f"- {e.left_table} ↔ {e.right_table}: ON {e.on_template}{conf_txt}")
    if not lines and not role_lines:
        return ""
    out: List[str] = []
    if role_lines:
        out.append("Selected table roles (transaction vs master):")
        out.extend(role_lines)
    if lines:
        out.append("Approved join paths (use only these edges/predicates):")
        out.extend(lines)
    return "\n".join(out)


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

