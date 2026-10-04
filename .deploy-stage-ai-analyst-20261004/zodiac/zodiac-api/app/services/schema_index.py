from __future__ import annotations

import csv
import difflib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .schema_nl_lexicon import (
    EXTRA_NL_PHRASE_TABLE_WEIGHTS,
    SAP_COLUMN_NL_HINTS,
    TABLE_NAME_NL_HINTS,
)

# Natural-language phrases → SAP / app tables (soft boosts for retrieval ranking).
_BASE_NL_PHRASE_TABLE_WEIGHTS: Dict[str, List[Tuple[str, float]]] = {
    "profit center": [("FAGLFLEXA", 6.0), ("CEPC", 4.0), ("COEP", 2.5), ("CSKS", 1.5)],
    "profit centre": [("FAGLFLEXA", 6.0), ("CEPC", 4.0), ("COEP", 2.5)],
    "purchase order": [("EKPO", 6.0), ("EKKO", 4.0), ("LFA1", 2.0)],
    "vendor invoice": [("RBKP", 6.0), ("RSEG", 5.0), ("LFA1", 2.5)],
    "invoice amount": [("VBRK", 4.0), ("VBRP", 5.0), ("RBKP", 4.0), ("RSEG", 3.5)],
    "billing": [("VBRK", 5.0), ("VBRP", 6.0), ("KNA1", 2.0)],
    "revenue": [("VBRK", 5.0), ("VBRP", 6.0), ("MAKT", 2.0)],
    "delivery": [("LIKP", 5.0), ("LIPS", 6.0), ("VBRP", 2.0)],
    "customer": [("KNA1", 5.0), ("VBRK", 3.0), ("KNVV", 2.0)],
    "material": [("MAKT", 5.0), ("MARA", 4.0), ("VBRP", 3.0), ("EKPO", 3.0)],
    "country": [("VBRK", 3.0), ("KNA1", 3.0)],
    "industry": [("KNA1", 4.0), ("T016T", 5.0), ("VBRK", 2.0)],
    "plant": [("LIPS", 4.0), ("MARC", 4.0), ("EKPO", 3.0), ("VBRP", 2.5)],
    "currency": [("VBRK", 3.0), ("RBKP", 3.5), ("EKKO", 2.5)],
    "year": [("VBRK", 3.0), ("FAGLFLEXA", 2.5), ("EKKO", 2.0)],
    "trend": [("VBRK", 3.0), ("VBRP", 3.0), ("FAGLFLEXA", 2.0)],
    "cost": [("FAGLFLEXA", 4.0), ("COEP", 3.5), ("CKIS", 2.5), ("BSEG", 2.0)],
    "spend": [("EKPO", 4.0), ("BSEG", 3.0), ("RSEG", 3.0)],
    "payment": [("BSAD", 4.0), ("BSEG", 3.0), ("DFKKOP", 2.0)],
    "tax": [("VBRK", 2.0), ("BSEG", 3.0), ("RBKP", 2.0)],
    "quantity": [("LIPS", 4.0), ("VBRP", 4.0), ("EKPO", 3.0), ("RESB", 2.5)],
}


def _merge_nl_phrase_table_weights(
    base: Dict[str, List[Tuple[str, float]]],
    extra: Dict[str, List[Tuple[str, float]]],
) -> Dict[str, List[Tuple[str, float]]]:
    out: Dict[str, List[Tuple[str, float]]] = {k: list(v) for k, v in base.items()}
    for phrase, weights in extra.items():
        by_table: Dict[str, float] = {t: w for t, w in out.get(phrase, [])}
        for t, w in weights:
            by_table[t] = max(by_table.get(t, 0.0), w)
        out[phrase] = sorted(by_table.items(), key=lambda x: (-x[1], x[0]))
    return out


_NL_PHRASE_TABLE_WEIGHTS = _merge_nl_phrase_table_weights(_BASE_NL_PHRASE_TABLE_WEIGHTS, EXTRA_NL_PHRASE_TABLE_WEIGHTS)


def _dtype_nl_boost(question_lower: str, data_type: str) -> float:
    """
    Soft score when the user's wording suggests measures vs dates vs text fields
    and the column's declared type matches (from tables_columns.csv / mapping).
    """
    dt = (data_type or "").lower()
    if not dt:
        return 0.0
    q = question_lower
    b = 0.0
    if any(
        k in q
        for k in (
            " date",
            " day ",
            " month",
            " year",
            "fiscal",
            "timestamp",
            "posting date",
            "document date",
            "created on",
            "changed on",
            "period",
        )
    ) or q.strip().startswith("date "):
        if any(x in dt for x in ("date", "time")):
            b += 0.48
    if any(
        k in q
        for k in (
            "amount",
            "total",
            " sum",
            "average",
            "avg",
            "quantity",
            "qty",
            "volume",
            "balance",
            "price",
            "cost",
            "revenue",
            "net value",
            "gross",
        )
    ):
        if any(x in dt for x in ("numeric", "decimal", "double", "real", "integer", "bigint", "smallint", "int", "float")):
            b += 0.42
    if any(k in q for k in ("description", "remark", "comment", "text", "notes", "explanation")):
        if any(x in dt for x in ("text", "varchar", "character", "char")):
            b += 0.38
    if "boolean" in dt or dt == "bool":
        if any(k in q for k in ("flag", "indicator", "yes or no", "active", "blocked")):
            b += 0.35
    return b


@dataclass
class CanonicalColumn:
    name: str
    data_type: str = ""
    description: str = ""
    aliases: List[str] | None = None


@dataclass
class CanonicalTable:
    name: str
    columns: List[CanonicalColumn]
    description: str = ""
    aliases: List[str] | None = None


@dataclass
class CanonicalSchemaIndex:
    tables: Dict[str, CanonicalTable]
    alias_to_table: Dict[str, str]

    def has_table(self, table_name: str) -> bool:
        return self.resolve_table_name(table_name) is not None

    def resolve_table_name(self, table_name: str) -> Optional[str]:
        if not table_name:
            return None
        key = str(table_name).strip().lower()
        return self.alias_to_table.get(key)

    def get_table(self, table_name: str) -> Optional[CanonicalTable]:
        resolved = self.resolve_table_name(table_name)
        if not resolved:
            return None
        return self.tables.get(resolved)

    def get_table_columns_map(self) -> Dict[str, List[str]]:
        return {t.name: [c.name for c in t.columns] for t in self.tables.values()}

    def suggest_similar_columns(self, table_name: str, wrong_column: str, *, n: int = 3, cutoff: float = 0.55) -> List[str]:
        """
        Case-insensitive fuzzy match of a bad column name to real columns on the table.
        Used for validation repair hints (LLM typos like NETWRX → NETWR).
        """
        resolved = self.resolve_table_name(table_name) or str(table_name or "").strip()
        tbl = self.tables.get(resolved)
        if not tbl or not tbl.columns:
            return []
        wrong_l = str(wrong_column or "").strip().lower()
        if not wrong_l:
            return []
        by_lower: Dict[str, str] = {}
        for c in tbl.columns:
            by_lower[c.name.lower()] = c.name
            for al in c.aliases or []:
                al2 = str(al).lower().strip()
                if len(al2) >= 3 and al2 not in by_lower:
                    by_lower[al2] = c.name
        keys = list(by_lower.keys())
        hits = difflib.get_close_matches(wrong_l, keys, n=n, cutoff=cutoff)
        out: List[str] = []
        seen: set[str] = set()
        for h in hits:
            canon = by_lower[h]
            if canon not in seen:
                seen.add(canon)
                out.append(canon)
        if out:
            return out
        for c in tbl.columns:
            for al in c.aliases or []:
                al2 = str(al).lower().strip()
                if len(al2) < 4:
                    continue
                r = difflib.SequenceMatcher(None, wrong_l, al2).ratio()
                if r >= 0.72 and c.name not in seen:
                    seen.add(c.name)
                    out.append(c.name)
                    if len(out) >= n:
                        return out
        return out

    def score_tables_for_natural_language(
        self,
        question: str,
        candidate_tables: Optional[Sequence[str]] = None,
    ) -> List[Tuple[str, float]]:
        """
        Score tables by overlap between the question and table/column metadata.
        Returns (table_name, score) sorted descending — for NL-driven table shortlisting.
        """
        q = (question or "").strip().lower()
        if not q:
            return []
        q_tokens = {t for t in re.split(r"[\W_]+", q) if len(t) > 2}
        q_compact = re.sub(r"\s+", "", q)

        def _tok(s: str) -> set[str]:
            return {t for t in re.split(r"[\W_]+", (s or "").lower()) if len(t) > 2}

        pool_upper = None
        if candidate_tables:
            pool_upper = {(t or "").strip().upper() for t in candidate_tables if t}

        scores: Dict[str, float] = {}
        for phrase, weights in _NL_PHRASE_TABLE_WEIGHTS.items():
            if phrase not in q:
                continue
            for tbl, w in weights:
                resolved = self.resolve_table_name(tbl) or tbl
                if resolved not in self.tables:
                    continue
                if pool_upper is not None and resolved.upper() not in pool_upper:
                    continue
                scores[resolved] = scores.get(resolved, 0.0) + w

        for name, tbl in self.tables.items():
            if pool_upper is not None and name.upper() not in pool_upper:
                continue
            sc = scores.get(name, 0.0)
            if tbl.description:
                sc += len(q_tokens & _tok(tbl.description)) * 1.6
            for col in tbl.columns:
                cn = col.name.lower()
                if col.description:
                    sc += len(q_tokens & _tok(col.description)) * 0.45
                if col.aliases:
                    for a in col.aliases:
                        al = str(a).lower()
                        if len(al) > 2 and al in q:
                            sc += 2.5
                for phrase in SAP_COLUMN_NL_HINTS.get(cn, ()):
                    pl = phrase.lower()
                    if len(pl) > 2 and (pl in q or pl in q_compact):
                        sc += 2.35
                if len(cn) >= 4 and cn in q_tokens:
                    sc += 1.15
                if len(cn) >= 5 and cn in q.replace("-", ""):
                    sc += 0.85
                sc += _dtype_nl_boost(q, col.data_type)
            for phrase in TABLE_NAME_NL_HINTS.get(name.upper(), ()):
                pl = str(phrase).lower().strip()
                if len(pl) > 2 and (pl in q or re.sub(r"\s+", "", pl) in q_compact):
                    sc += 2.9
            scores[name] = sc

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [(t, s) for t, s in ranked if s > 0]


def _is_sap_style(table_name: str) -> bool:
    if not table_name:
        return False
    if table_name in {"vbrp"}:
        return True
    return any(ch.isalpha() for ch in table_name) and table_name.upper() == table_name


def _schema_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _csv_path() -> Path:
    return _schema_root().parent / "tables_columns.csv"


def _mapping_path() -> Path:
    return _schema_root() / "db_table_mapping.json"


def _cfg_path() -> Path:
    return _schema_root() / "schema_ai_config.json"


@lru_cache(maxsize=1)
def _skip_tables() -> set[str]:
    try:
        with _cfg_path().open("r", encoding="utf-8") as f:
            raw = json.load(f) or {}
        st = raw.get("skip_tables") or []
        return {str(t).lower() for t in st}
    except Exception:
        return set()


def _ensure_table(index: Dict[str, CanonicalTable], name: str) -> CanonicalTable:
    t = index.get(name)
    if t:
        return t
    t = CanonicalTable(name=name, columns=[])
    index[name] = t
    return t


def _add_or_merge_column(table: CanonicalTable, col: CanonicalColumn) -> None:
    for existing in table.columns:
        if existing.name.lower() == col.name.lower():
            if not existing.data_type and col.data_type:
                existing.data_type = col.data_type
            if not existing.description and col.description:
                existing.description = col.description
            if col.aliases:
                merged = set(existing.aliases or [])
                merged.update(col.aliases)
                existing.aliases = sorted(merged)
            return
    table.columns.append(col)


@lru_cache(maxsize=1)
def build_canonical_schema_index(include_non_sap: bool = False) -> CanonicalSchemaIndex:
    tables: Dict[str, CanonicalTable] = {}
    aliases: Dict[str, str] = {}
    skip = _skip_tables()

    csv_p = _csv_path()
    if csv_p.exists():
        with csv_p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                table = str(row.get("table") or "").strip()
                col = str(row.get("column") or "").strip()
                dtype = str(row.get("data_type") or "").strip()
                if not table or not col:
                    continue
                if table.lower() in skip:
                    continue
                if not include_non_sap and not _is_sap_style(table):
                    continue
                tbl = _ensure_table(tables, table)
                _add_or_merge_column(tbl, CanonicalColumn(name=col, data_type=dtype))

    mp = _mapping_path()
    if mp.exists():
        try:
            with mp.open("r", encoding="utf-8") as f:
                raw = json.load(f) or {}
        except Exception:
            raw = {}
        if isinstance(raw, dict):
            for table_name, info in raw.items():
                table = str(table_name or "").strip()
                if not table:
                    continue
                if table.lower() in skip:
                    continue
                if not include_non_sap and not _is_sap_style(table):
                    continue
                entry = info if isinstance(info, dict) else {}
                tbl = _ensure_table(tables, table)
                desc = str(entry.get("description") or "").strip()
                if desc and not tbl.description:
                    tbl.description = desc
                col_map = entry.get("columns") or {}
                if isinstance(col_map, dict):
                    for col_name, col_desc in col_map.items():
                        cdesc = str(col_desc or "").strip() if not isinstance(col_desc, dict) else str(col_desc.get("description") or "").strip()
                        _add_or_merge_column(tbl, CanonicalColumn(name=str(col_name), description=cdesc))

    _apply_table_name_nl_hints(tables)
    _apply_sap_column_nl_hints(tables)

    for table in tables.values():
        aliases[table.name.strip().lower()] = table.name
        aliases[table.name.strip().upper()] = table.name
        aliases[table.name.strip()] = table.name
        if table.aliases:
            for a in table.aliases:
                aliases[str(a).strip().lower()] = table.name
        for c in table.columns:
            if c.aliases:
                pass

    return CanonicalSchemaIndex(tables=tables, alias_to_table=aliases)


def _apply_table_name_nl_hints(tables: Dict[str, CanonicalTable]) -> None:
    """Whole-table NL phrases (e.g. 'billing header' -> VBRK) for ranking and name resolution."""
    upper_to_actual = {t.upper(): t for t in tables}
    for tbl_key, phrases in TABLE_NAME_NL_HINTS.items():
        actual = upper_to_actual.get(str(tbl_key).strip().upper())
        if not actual:
            continue
        tbl = tables[actual]
        merged = set(tbl.aliases or [])
        merged.update(p for p in phrases if p and str(p).strip())
        tbl.aliases = sorted(merged) if merged else tbl.aliases


def _apply_sap_column_nl_hints(tables: Dict[str, CanonicalTable]) -> None:
    """Attach NL phrase aliases to columns so prompts and fuzzy hints align with user wording."""
    for tbl in tables.values():
        for col in tbl.columns:
            hints = SAP_COLUMN_NL_HINTS.get(col.name.lower())
            if not hints:
                continue
            merged = set(col.aliases or [])
            merged.update(h for h in hints if h and str(h).strip())
            col.aliases = sorted(merged) if merged else col.aliases

