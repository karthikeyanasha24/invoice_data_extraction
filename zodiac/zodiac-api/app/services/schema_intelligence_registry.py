"""
Persistent schema intelligence layer — loaded once from files, indexed, reused per question.

Sources (no live DB introspection on each question):
  - schema_full.json          → physical columns + types
  - app/schema_metadata_for_llm.json → business descriptions, hints
  - sap_table_metadata.json   → rich SAP metadata (when present)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from ..data_catalog.physical import (
    column_names,
    has_column,
    has_table,
    load_physical_schema,
    resolve_table_name,
)
from ..data_catalog.registry import RELATIONSHIPS, get_table_entry

logger = logging.getLogger("zodiac-api.schema_registry")

_ROOT = Path(__file__).resolve().parents[2]
_LLM_META = Path(__file__).resolve().parents[1] / "schema_metadata_for_llm.json"
_SAP_META = _ROOT / "sap_table_metadata.json"

_TOKEN = re.compile(r"[a-z0-9_]{3,}")

# Operational / Zodiac tables only — SAP table discovery is AI-driven from catalog metadata.
_OPERATIONAL_ALIASES: Dict[str, List[str]] = {
    "sat processing log": ["sat_processing_logs"],
    "sat processing step": ["sat_processing_logs"],
    "sat log": ["sat_processing_logs"],
    "failed sat": ["sat_processing_logs"],
    "sat document": ["sat_documents", "sat_canonical_merged"],
    "edi failure": ["zodiac_invoice_failed_edi"],
    "failed edi": ["zodiac_invoice_failed_edi"],
    "supplier token": ["supplier_tokens"],
}

_OPERATIONAL_PREFIXES = ("sat_", "zodiac_", "invoice_", "supplier_", "converted_", "customer_users")


@dataclass
class ColumnMeta:
    name: str
    data_type: str = ""
    description: str = ""
    business_terms: List[str] = field(default_factory=list)


@dataclass
class TableMeta:
    table: str
    description: str = ""
    business_purpose: str = ""
    domain: str = ""
    grain: str = ""
    columns: List[ColumnMeta] = field(default_factory=list)
    important_columns: List[str] = field(default_factory=list)
    joins: Dict[str, str] = field(default_factory=dict)
    sql_hints: str = ""
    business_terms: List[str] = field(default_factory=list)
    exists: bool = True


class SchemaIntelligenceRegistry:
    """Singleton-style registry built once from schema files."""

    def __init__(self) -> None:
        self._tables: Dict[str, TableMeta] = {}
        self._term_index: Dict[str, Set[str]] = {}
        self._loaded = False

    def ensure_loaded(self) -> None:
        if self._loaded:
            return
        physical = load_physical_schema()
        llm_meta = self._read_json(_LLM_META)
        sap_meta = self._read_json(_SAP_META)

        llm_tables = llm_meta.get("tables") if isinstance(llm_meta.get("tables"), dict) else {}
        for table_key, cols in physical.items():
            resolved = resolve_table_name(table_key) or table_key
            llm = llm_tables.get(resolved) or llm_tables.get(resolved.upper()) or llm_tables.get(resolved.lower()) or {}
            sap = sap_meta.get(resolved) or sap_meta.get(resolved.upper()) or {}
            if not isinstance(llm, dict):
                llm = {}
            if not isinstance(sap, dict):
                sap = {}

            col_metas: List[ColumnMeta] = []
            important = list(llm.get("important_columns") or sap.get("important_columns") or [])
            for c in cols:
                col_name = str(c.get("col") or c)
                col_type = str(c.get("type") or "")
                col_metas.append(ColumnMeta(name=col_name, data_type=col_type))

            desc = str(
                llm.get("description")
                or sap.get("description")
                or sap.get("business_meaning")
                or ""
            )
            entry = get_table_entry(resolved) or {}
            domain = str(entry.get("primary_domain") or llm.get("business_category") or "")
            grain = str(entry.get("grain") or "")
            joins_raw = llm.get("joins") or sap.get("joins") or {}
            joins: Dict[str, str] = {}
            if isinstance(joins_raw, dict):
                joins = {str(k): str(v) for k, v in joins_raw.items()}
            elif isinstance(joins_raw, list):
                for j in joins_raw:
                    joins[str(j)] = str(j)

            terms = self._build_terms(resolved, desc, domain, important, joins)
            self._tables[resolved] = TableMeta(
                table=resolved,
                description=desc,
                business_purpose=str(sap.get("business_meaning") or desc),
                domain=domain,
                grain=grain,
                columns=col_metas,
                important_columns=important,
                joins=joins,
                sql_hints=str(llm.get("sql_hints") or sap.get("sql_hints") or ""),
                business_terms=terms,
                exists=True,
            )
            for t in terms:
                self._term_index.setdefault(t, set()).add(resolved)

        for concept, tables in _OPERATIONAL_ALIASES.items():
            for tbl in tables:
                if has_table(tbl):
                    self._term_index.setdefault(concept, set()).add(resolve_table_name(tbl) or tbl)

        self._loaded = True
        logger.info(
            "[schema_registry] loaded tables=%s term_index=%s",
            len(self._tables),
            len(self._term_index),
        )

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception as exc:
            logger.warning("[schema_registry] failed to read %s: %s", path, exc)
            return {}

    @staticmethod
    def _build_terms(
        table: str,
        description: str,
        domain: str,
        important: List[str],
        joins: Dict[str, str],
    ) -> List[str]:
        blob = f"{table} {description} {domain} {' '.join(important)} {' '.join(joins)}".lower()
        return sorted(set(_TOKEN.findall(blob)))

    def all_table_names(self, *, include_operational: bool = False) -> List[str]:
        self.ensure_loaded()
        names = sorted(self._tables.keys(), key=lambda t: t.upper())
        if include_operational:
            return names
        out = []
        for t in names:
            low = t.lower()
            if any(low.startswith(p) for p in _OPERATIONAL_PREFIXES):
                continue
            if low in {"customers"}:
                continue
            out.append(t)
        return out

    def get_table(self, table: str) -> Optional[TableMeta]:
        self.ensure_loaded()
        key = resolve_table_name(table)
        return self._tables.get(key or table)

    def table_exists(self, table: str) -> bool:
        return has_table(table)

    def lightweight_table_catalog(self, *, include_operational: bool = False) -> List[Dict[str, Any]]:
        """Pipeline 1 input — table names + descriptions only (no full column lists)."""
        self.ensure_loaded()
        out: List[Dict[str, Any]] = []
        for name in self.all_table_names(include_operational=include_operational):
            meta = self._tables.get(name)
            if not meta:
                continue
            out.append(
                {
                    "table": meta.table,
                    "description": meta.description[:280],
                    "domain": meta.domain,
                    "grain": meta.grain,
                    "business_terms": meta.business_terms[:12],
                }
            )
        return out

    def compact_catalog_text(self, *, include_operational: bool = False, max_desc: int = 120) -> str:
        """One line per table for Pipeline 1 — full catalog, no columns."""
        lines: List[str] = []
        for item in self.lightweight_table_catalog(include_operational=include_operational):
            desc = str(item.get("description") or "").replace("\n", " ")[:max_desc]
            domain = item.get("domain") or ""
            lines.append(f"- {item['table']}: {desc} [{domain}]")
        return "\n".join(lines)

    def expand_join_neighbors(self, tables: List[str]) -> List[str]:
        """Add relationship neighbors from schema metadata (not question keywords)."""
        self.ensure_loaded()
        selected_upper = {_normalize_registry_table(t).upper() for t in tables}
        expanded: List[str] = [_normalize_registry_table(t) for t in tables]
        seen = set(selected_upper)

        def add(tbl: str) -> None:
            key = _normalize_registry_table(tbl)
            u = key.upper()
            if u not in seen and has_table(key):
                seen.add(u)
                expanded.append(key)

        for rel in RELATIONSHIPS:
            src = _normalize_registry_table(str(rel.get("source_table") or ""))
            tgt = _normalize_registry_table(str(rel.get("target_table") or ""))
            if src.upper() in seen:
                add(tgt)
            if tgt.upper() in seen:
                add(src)
        return expanded

    def score_tables_for_question(self, question: str, *, include_operational: bool = False) -> List[Tuple[str, float, str]]:
        """Rule-based retrieval — top candidate tables before Pipeline 1 LLM."""
        self.ensure_loaded()
        q = (question or "").lower()
        tokens = set(_TOKEN.findall(q))
        scores: Dict[str, float] = {}
        reasons: Dict[str, str] = {}

        def bump(table: str, score: float, reason: str) -> None:
            if not has_table(table):
                return
            key = resolve_table_name(table) or table
            scores[key] = scores.get(key, 0.0) + score
            reasons.setdefault(key, reason)

        for concept, tables in _OPERATIONAL_ALIASES.items():
            if concept in q:
                for t in tables:
                    bump(t, 8.0, f"operational concept: {concept}")

        for name in self.all_table_names(include_operational=include_operational):
            meta = self._tables.get(name)
            if not meta:
                continue
            if name.lower() in tokens or name.upper() in {t.upper() for t in tokens}:
                bump(name, 6.0, "table name in question")
            overlap = len(tokens.intersection(set(meta.business_terms)))
            if overlap:
                bump(name, overlap * 1.5, f"{overlap} term overlap")

        for rel in RELATIONSHIPS:
            src = str(rel.get("source_table") or "")
            tgt = str(rel.get("target_table") or "")
            if src in scores:
                bump(tgt, 1.5, f"join neighbor of {src}")
            if tgt in scores:
                bump(src, 1.5, f"join neighbor of {tgt}")

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [(t, s, reasons.get(t, "")) for t, s in ranked]

    def columns_for_tables(self, tables: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Pipeline 2 input — column metadata ONLY for selected tables."""
        self.ensure_loaded()
        out: Dict[str, List[Dict[str, Any]]] = {}
        for table in tables:
            meta = self.get_table(table)
            if not meta:
                continue
            cols: List[Dict[str, Any]] = []
            important_set = {c.lower() for c in meta.important_columns}
            for c in meta.columns:
                cols.append(
                    {
                        "name": c.name,
                        "type": c.data_type,
                        "important": c.name.lower() in important_set,
                    }
                )
            out[meta.table] = cols
        return out

    def column_detail_for_selection(self, tables: List[str]) -> str:
        """Human/LLM-readable column block for Pipeline 2 & 3."""
        self.ensure_loaded()
        lines: List[str] = []
        for table in tables:
            meta = self.get_table(table)
            if not meta:
                lines.append(f"{table}: ABSENT FROM SCHEMA")
                continue
            imp = meta.important_columns or [c.name for c in meta.columns[:20]]
            lines.append(f"{meta.table}: {meta.description[:200]}")
            lines.append(f"  important_columns: {', '.join(imp[:30])}")
            if meta.joins:
                lines.append(f"  joins: {json.dumps(meta.joins)}")
            if meta.sql_hints:
                lines.append(f"  sql_hints: {meta.sql_hints[:300]}")
        return "\n".join(lines)

    def find_tables_for_concept(
        self,
        concept: str,
        *,
        include_operational: bool = False,
        limit: int = 3,
    ) -> List[Tuple[str, float, str]]:
        """Rank tables from schema metadata for a business concept (no hardcoded SAP mappings)."""
        self.ensure_loaded()
        c = (concept or "").lower().strip()
        if not c:
            return []
        tokens = set(_TOKEN.findall(c))
        scores: Dict[str, float] = {}
        reasons: Dict[str, str] = {}

        def bump(table: str, score: float, reason: str) -> None:
            if not has_table(table):
                return
            key = resolve_table_name(table) or table
            scores[key] = scores.get(key, 0.0) + score
            reasons.setdefault(key, reason)

        for tok in tokens:
            for tbl in self._term_index.get(tok, set()):
                bump(tbl, 3.0, f"term index: {tok}")

        for name in self.all_table_names(include_operational=include_operational):
            meta = self._tables.get(name)
            if not meta:
                continue
            blob = (
                f"{meta.table} {meta.description} {meta.domain} {meta.grain} "
                f"{meta.business_purpose} {' '.join(meta.important_columns)}"
            ).lower()
            if c in blob:
                bump(name, 5.0, f"description match: {concept}")
            overlap = len(tokens.intersection(set(meta.business_terms)))
            if overlap:
                bump(name, overlap * 2.0, f"{overlap} business-term overlap")

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [(t, s, reasons.get(t, "")) for t, s in ranked[:limit]]

    def table_covers_concept(self, table: str, concept: str) -> bool:
        meta = self.get_table(table)
        if not meta:
            return False
        c = (concept or "").lower().strip()
        if not c:
            return False
        blob = (
            f"{meta.table} {meta.description} {meta.domain} {meta.grain} "
            f"{' '.join(meta.important_columns)} {' '.join(meta.business_terms)}"
        ).lower()
        if c in blob or any(c in t for t in meta.business_terms):
            return True
        # Underscored concepts ("sales_order") match spaced metadata ("sales order").
        spaced = c.replace("_", " ")
        if spaced != c and (spaced in blob or all(tok in blob for tok in spaced.split() if len(tok) > 2)):
            return True
        # Document-count concepts are covered by transactional header tables.
        if c in {"sales_order", "sales_orders", "order", "orders", "count"}:
            if any(tok in blob for tok in ("sales order", "sales document", "order header")):
                return True
            if meta.table.upper() in {"VBAK", "VBAP", "LIKP", "EKKO", "VBRK"} and c.startswith("sales"):
                return True
        return False

    def resolve_data_limitation(self, question: str, selected_tables: List[str]) -> Optional[str]:
        """Return user-facing limitation message when concept cannot be mapped."""
        q = (question or "").lower()
        if not selected_tables and "sat" in q and "process" in q:
            if has_table("sat_processing_logs"):
                return None
            return (
                "Data limitation: the available schema does not contain a table representing "
                "SAT processing logs, so failed SAT processing steps cannot be retrieved."
            )
        if not selected_tables:
            return (
                "Data limitation: no tables in the indexed schema match this question. "
                "Try rephrasing with a business metric and dimension (customer, material, billing, etc.)."
            )
        return None

    def suggested_joins(self, tables: List[str]) -> List[Dict[str, str]]:
        self.ensure_loaded()
        joins: List[Dict[str, str]] = []
        table_set = {resolve_table_name(t) or t for t in tables}
        for rel in RELATIONSHIPS:
            src = str(rel.get("source_table") or "")
            tgt = str(rel.get("target_table") or "")
            key = str(rel.get("join_key") or "")
            if src in table_set and tgt in table_set and key:
                joins.append(
                    {
                        "left_table": src,
                        "right_table": tgt,
                        "join_key": key,
                        "reason": str(rel.get("description") or "catalog relationship"),
                    }
                )
        return joins


def _normalize_registry_table(table: str) -> str:
    return resolve_table_name(table) or table


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaIntelligenceRegistry:
    reg = SchemaIntelligenceRegistry()
    reg.ensure_loaded()
    return reg


def warmup_schema_registry() -> Dict[str, Any]:
    reg = get_schema_registry()
    return {
        "ok": True,
        "tables": len(reg.all_table_names(include_operational=True)),
        "sap_tables": len(reg.all_table_names(include_operational=False)),
    }
