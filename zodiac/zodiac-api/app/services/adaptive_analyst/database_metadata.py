"""Generic DATABASE_METADATA capability for Adaptive AI Analyst.

Distinguishes schema/catalog introspection from business analytics.

Operations (capabilities, not phrase handlers):
  COUNT_TABLES, LIST_TABLES, COUNT_COLUMNS, LIST_COLUMNS,
  DESCRIBE_TABLE, SEARCH_TABLES, SEARCH_COLUMNS, DESCRIBE_SCHEMA

Answers are derived from the authorized schema catalog dict
({table: [{col, type}, ...]}), never from hardcoded counts or /health.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

CAPABILITY = "DATABASE_METADATA"

COUNT_TABLES = "COUNT_TABLES"
LIST_TABLES = "LIST_TABLES"
COUNT_COLUMNS = "COUNT_COLUMNS"
LIST_COLUMNS = "LIST_COLUMNS"
DESCRIBE_TABLE = "DESCRIBE_TABLE"
SEARCH_TABLES = "SEARCH_TABLES"
SEARCH_COLUMNS = "SEARCH_COLUMNS"
DESCRIBE_SCHEMA = "DESCRIBE_SCHEMA"

# Schema/catalog entities — subject of introspection (not business measures).
_SCHEMA_ENTITY = re.compile(
    r"\b("
    r"tables?|columns?|fields?|schema|entities|entity|catalog|metadata|"
    r"database\s+structure|db\s+schema|data\s+dictionary"
    r")\b",
    re.I,
)

# Strong business-fact signals that usually mean analytics, not metadata —
# unless the question also targets schema entities (e.g. tables containing customer).
_BUSINESS_FACT = re.compile(
    r"\b("
    r"revenue|sales|billing|invoice|invoices|orders?|purchas\w*|vendor|vendors|"
    r"profit|margin|inventory|stock|shipments?|deliver(?:y|ies)|payment"
    r")\b",
    re.I,
)

_RANKING_ANALYTICS = re.compile(
    r"\b(top\s+\d+|highest|lowest|biggest|most|least)\b.{0,40}\b"
    r"(customer|customers|product|products|vendor|vendors|country|region)\b",
    re.I,
)

_COUNT_CUE = re.compile(
    r"\b(how\s+many|count(?:\s+of)?|number\s+of|how\s+much|total\s+number)\b",
    re.I,
)
_LIST_CUE = re.compile(
    r"\b(list|show|display|enumerate|available|exist|access\s+to|what\s+are|"
    r"which\s+are|tell\s+me\s+(?:the\s+)?(?:tables?|columns?|fields?))\b",
    re.I,
)
_DESCRIBE_CUE = re.compile(
    r"\b(describe|structure\s+of|profile|definition\s+of)\b|"
    r"\b(columns?|fields?)\s+(?:in|on|of|for)\b|"
    r"\bwhat\s+columns?\b|"
    r"\bwhat\s+fields?\b",
    re.I,
)
_SEARCH_CUE = re.compile(
    r"\b(contain|contains|containing|related\s+to|about|with\s+(?:customer|sales|"
    r"billing|vendor|product|order)|have\s+(?:a\s+)?(?:column|field)|"
    r"which\s+tables?\s+(?:have|contain|include)|"
    r"tables?\s+(?:with|for|about))\b",
    re.I,
)
_SCHEMA_OVERVIEW = re.compile(
    r"\b(show\s+(?:me\s+)?(?:the\s+)?schema|describe\s+(?:the\s+)?schema|"
    r"database\s+schema|what\s+(?:database\s+)?tables?\s+do\s+you\s+have|"
    r"what\s+entities\s+are\s+available)\b",
    re.I,
)

# SAP-style table names (alphanumeric 3–6 chars common in extracts).
_TABLE_TOKEN = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,15})\b")

_STOP_TOKENS = frozenset(
    {
        "the",
        "and",
        "for",
        "how",
        "many",
        "what",
        "which",
        "show",
        "list",
        "tell",
        "me",
        "you",
        "your",
        "have",
        "has",
        "are",
        "is",
        "in",
        "on",
        "of",
        "to",
        "do",
        "does",
        "can",
        "could",
        "please",
        "table",
        "tables",
        "column",
        "columns",
        "field",
        "fields",
        "schema",
        "database",
        "count",
        "number",
        "available",
        "exist",
        "exists",
        "access",
        "describe",
        "contain",
        "contains",
        "related",
        "information",
        "data",
        "there",
        "all",
        "with",
        "from",
        "about",
    }
)


@dataclass
class MetadataPlan:
    capability: str = CAPABILITY
    operation: str = COUNT_TABLES
    table_name: Optional[str] = None
    search_terms: List[str] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class MetadataResult:
    operation: str
    value: Any
    rows: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)


def _normalize_schema(schema: Optional[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for tname, cols in (schema or {}).items():
        key = str(tname)
        cleaned: List[Dict[str, Any]] = []
        for c in cols or []:
            if isinstance(c, dict):
                col = str(c.get("col") or c.get("name") or c.get("column") or "").strip()
                typ = str(c.get("type") or c.get("data_type") or "text").strip()
            else:
                col = str(c).strip()
                typ = "text"
            if col:
                cleaned.append({"col": col, "type": typ})
        out[key] = cleaned
    return out


def _schema_index(
    schema: Dict[str, List[Dict[str, Any]]],
) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    """Return (lower_table -> canonical, lower_table -> [col lower])."""
    tables: Dict[str, str] = {}
    cols: Dict[str, List[str]] = {}
    for t, clist in schema.items():
        tables[t.lower()] = t
        cols[t.lower()] = [str(c.get("col") or "").lower() for c in clist]
    return tables, cols


def _resolve_table_mention(question: str, schema: Dict[str, List[Dict[str, Any]]]) -> Optional[str]:
    tables, _ = _schema_index(schema)
    q = question or ""
    # Prefer exact case-insensitive token matches against known tables.
    for m in _TABLE_TOKEN.finditer(q):
        tok = m.group(1)
        if tok.lower() in _STOP_TOKENS:
            continue
        hit = tables.get(tok.lower())
        if hit:
            return hit
    return None


def _search_terms(question: str) -> List[str]:
    q = (question or "").lower()
    # Topic phrases after contain/related/about
    terms: List[str] = []
    for pat in (
        r"contain(?:s|ing)?\s+([a-z0-9_ \-]{2,40})",
        r"related\s+to\s+([a-z0-9_ \-]{2,40})",
        r"about\s+([a-z0-9_ \-]{2,40})",
        r"with\s+([a-z0-9_ \-]{2,40})",
        r"customer[-\s]?related",
        r"sales\s+data",
        r"billing\s+data",
    ):
        m = re.search(pat, q, re.I)
        if m:
            if m.lastindex:
                raw = m.group(1)
            else:
                raw = m.group(0)
            raw = re.split(r"[?.!,]| in the | from | of the ", raw)[0]
            for part in re.findall(r"[a-z0-9_]{3,}", raw.lower()):
                if part not in _STOP_TOKENS and part not in terms:
                    terms.append(part)
    # Common business topics used as metadata search seeds
    for seed in (
        "customer",
        "customers",
        "sales",
        "billing",
        "invoice",
        "vendor",
        "product",
        "material",
        "order",
        "purchase",
    ):
        if seed in q and seed not in terms and seed.rstrip("s") not in terms:
            # only if question is schema-search shaped
            if _SEARCH_CUE.search(q) or "related" in q:
                terms.append(seed.rstrip("s") if seed.endswith("s") and seed != "sales" else seed)
    return terms[:8]


def is_database_metadata_question(question: str) -> bool:
    """True when the question asks about schema/catalog, not business facts."""
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()

    # Ranking / measure analytics are never metadata.
    if _RANKING_ANALYTICS.search(ql) and not _SCHEMA_ENTITY.search(ql):
        return False

    has_entity = bool(_SCHEMA_ENTITY.search(ql))
    # "What columns does VBRK have?" / "Describe VBRK" without the word table/column
    # still metadata if a describe cue + table-like token appears — resolved later
    # with schema; here use describe cue + alphanumeric token of table shape.
    describe_shaped = bool(
        _DESCRIBE_CUE.search(ql)
        or re.search(r"\bdescribe\s+[a-z][a-z0-9_]{2,}\b", ql)
        or re.search(r"\b(?:columns?|fields?)\s+(?:does|in|of|for)\s+[a-z][a-z0-9_]{2,}", ql)
    )

    if not has_entity and not describe_shaped:
        return False

    # "How many sales orders" — count of business facts, not tables/columns.
    if _COUNT_CUE.search(ql) and _BUSINESS_FACT.search(ql) and not re.search(
        r"\b(tables?|columns?|fields?|schema|entities)\b", ql
    ):
        return False

    # Capability/help is separate (what can I ask?) — leave to general_chat.
    if re.search(r"\bwhat can i ask\b|\bcapabilities\b|\bhow does this work\b", ql):
        return False

    return True


def classify_metadata_operation(
    question: str,
    schema: Optional[Dict[str, Any]] = None,
) -> Optional[MetadataPlan]:
    """Map NL to a metadata operation. Returns None if not DATABASE_METADATA."""
    if not is_database_metadata_question(question):
        return None

    schema_n = _normalize_schema(schema)
    q = (question or "").strip()
    ql = q.lower()
    table = _resolve_table_mention(q, schema_n) if schema_n else None
    terms = _search_terms(q)

    # Named-table describe / list columns
    if table and (
        _DESCRIBE_CUE.search(ql)
        or re.search(rf"\b(describe|columns?|fields?)\b.*\b{re.escape(table.lower())}\b", ql)
        or re.search(rf"\b{re.escape(table.lower())}\b.*\b(columns?|fields?|structure)\b", ql)
        or re.search(rf"\bdescribe\s+{re.escape(table.lower())}\b", ql)
    ):
        if re.search(r"\b(columns?|fields?)\b", ql) and not re.search(r"\bdescribe\b", ql):
            return MetadataPlan(operation=LIST_COLUMNS, table_name=table, confidence=0.92)
        return MetadataPlan(operation=DESCRIBE_TABLE, table_name=table, confidence=0.93)

    # Search schema for topic / column
    if _SEARCH_CUE.search(ql) or (terms and re.search(r"\bwhich\s+tables?\b", ql)):
        # Prefer column search when a known column name is mentioned
        if schema_n:
            _, cols_idx = _schema_index(schema_n)
            all_cols = {c for cl in cols_idx.values() for c in cl}
            mentioned = [
                t for t in re.findall(r"[a-z][a-z0-9_]{2,}", ql) if t in all_cols and t not in _STOP_TOKENS
            ]
            if mentioned:
                return MetadataPlan(
                    operation=SEARCH_COLUMNS,
                    search_terms=mentioned[:5],
                    confidence=0.9,
                )
        if terms:
            return MetadataPlan(operation=SEARCH_TABLES, search_terms=terms, confidence=0.88)
        return MetadataPlan(operation=SEARCH_TABLES, search_terms=terms, confidence=0.7)

    # Counts
    if _COUNT_CUE.search(ql):
        if re.search(r"\bcolumns?|fields?\b", ql):
            if table:
                return MetadataPlan(operation=LIST_COLUMNS, table_name=table, confidence=0.9)
            return MetadataPlan(operation=COUNT_COLUMNS, confidence=0.95)
        if re.search(r"\btables?|entities|schema\b", ql):
            return MetadataPlan(operation=COUNT_TABLES, confidence=0.96)
        # "what's the table count"
        if "table" in ql:
            return MetadataPlan(operation=COUNT_TABLES, confidence=0.94)

    # Schema overview
    if _SCHEMA_OVERVIEW.search(ql):
        if re.search(r"\bentit", ql):
            return MetadataPlan(operation=LIST_TABLES, confidence=0.85)
        return MetadataPlan(operation=DESCRIBE_SCHEMA, confidence=0.86)

    # List tables / columns
    if re.search(r"\bcolumns?|fields?\b", ql) and not re.search(r"\btables?\b", ql):
        if table:
            return MetadataPlan(operation=LIST_COLUMNS, table_name=table, confidence=0.9)
        return MetadataPlan(operation=COUNT_COLUMNS, confidence=0.75)

    if re.search(r"\btables?|entities\b", ql) or _LIST_CUE.search(ql):
        if _LIST_CUE.search(ql) or re.search(r"\bwhat\b|\bwhich\b|\bavailable\b|\bexist", ql):
            return MetadataPlan(operation=LIST_TABLES, confidence=0.9)
        return MetadataPlan(operation=LIST_TABLES, confidence=0.8)

    # Fallback for schema-entity questions
    if re.search(r"\btables?\b", ql):
        return MetadataPlan(operation=LIST_TABLES, confidence=0.7)
    if re.search(r"\bcolumns?|fields?|schema\b", ql):
        return MetadataPlan(operation=DESCRIBE_SCHEMA, confidence=0.65)
    return MetadataPlan(operation=DESCRIBE_SCHEMA, confidence=0.6)


def execute_metadata_plan(
    plan: MetadataPlan,
    schema: Optional[Dict[str, Any]],
) -> MetadataResult:
    """Execute against the authorized schema catalog. Read-only; no SQL needed."""
    schema_n = _normalize_schema(schema)
    tables_sorted = sorted(schema_n.keys(), key=lambda t: t.upper())
    table_count = len(tables_sorted)
    col_count = sum(len(schema_n[t]) for t in tables_sorted)

    op = plan.operation

    if op == COUNT_TABLES:
        return MetadataResult(
            operation=op,
            value=table_count,
            rows=[{"table_count": table_count}],
            summary=f"There are {table_count} tables available in the connected database.",
            evidence={"source": "schema_catalog", "table_count": table_count},
        )

    if op == COUNT_COLUMNS:
        return MetadataResult(
            operation=op,
            value=col_count,
            rows=[{"column_count": col_count, "table_count": table_count}],
            summary=(
                f"There are {col_count} columns across {table_count} tables "
                "in the connected database."
            ),
            evidence={"source": "schema_catalog", "column_count": col_count},
        )

    if op == LIST_TABLES:
        rows = [{"table": t, "column_count": len(schema_n[t])} for t in tables_sorted]
        preview = ", ".join(tables_sorted[:20])
        more = "" if table_count <= 20 else f" (showing 20 of {table_count})"
        return MetadataResult(
            operation=op,
            value=tables_sorted,
            rows=rows,
            summary=f"There are {table_count} tables available{more}: {preview}.",
            evidence={"source": "schema_catalog", "table_count": table_count},
        )

    if op == DESCRIBE_SCHEMA:
        sample = tables_sorted[:15]
        return MetadataResult(
            operation=op,
            value={"table_count": table_count, "column_count": col_count, "sample_tables": sample},
            rows=[{"table": t, "column_count": len(schema_n[t])} for t in sample],
            summary=(
                f"The connected database schema has {table_count} tables and "
                f"{col_count} columns. Sample tables: {', '.join(sample)}."
            ),
            evidence={"source": "schema_catalog"},
        )

    if op in {LIST_COLUMNS, DESCRIBE_TABLE}:
        tname = plan.table_name
        if not tname or tname not in schema_n:
            return MetadataResult(
                operation=op,
                value=None,
                rows=[],
                summary=(
                    f"Table '{tname or '?'}' was not found in the connected schema."
                    if tname
                    else "No table was identified to describe."
                ),
                evidence={"source": "schema_catalog", "found": False},
            )
        cols = schema_n[tname]
        rows = [{"table": tname, "column": c["col"], "type": c["type"]} for c in cols]
        col_list = ", ".join(f"{c['col']} ({c['type']})" for c in cols[:40])
        more = "" if len(cols) <= 40 else f" … and {len(cols) - 40} more"
        verb = "Description of" if op == DESCRIBE_TABLE else "Columns in"
        return MetadataResult(
            operation=op,
            value={"table": tname, "columns": cols},
            rows=rows,
            summary=f"{verb} {tname} ({len(cols)} columns): {col_list}{more}.",
            evidence={"source": "schema_catalog", "table": tname, "column_count": len(cols)},
        )

    if op == SEARCH_COLUMNS:
        terms = [t.lower() for t in plan.search_terms]
        hits: List[Dict[str, Any]] = []
        for t in tables_sorted:
            for c in schema_n[t]:
                cl = c["col"].lower()
                if any(term == cl or term in cl for term in terms):
                    hits.append({"table": t, "column": c["col"], "type": c["type"]})
        if not hits:
            return MetadataResult(
                operation=op,
                value=[],
                rows=[],
                summary=(
                    "No columns matched "
                    f"{', '.join(plan.search_terms) or 'the search terms'} "
                    "in the connected schema."
                ),
                evidence={"source": "schema_catalog", "match_count": 0},
            )
        tables_hit = sorted({h["table"] for h in hits})
        return MetadataResult(
            operation=op,
            value=hits,
            rows=hits[:100],
            summary=(
                f"Found {len(hits)} matching column(s) across {len(tables_hit)} table(s): "
                + ", ".join(tables_hit[:12])
                + ("…" if len(tables_hit) > 12 else "")
                + "."
            ),
            evidence={"source": "schema_catalog", "match_count": len(hits)},
        )

    if op == SEARCH_TABLES:
        terms = [t.lower() for t in plan.search_terms]
        # Synonym seeds for common business topics → known SAP table families
        topic_hints = {
            "customer": ("kna1", "kunnr", "kunag", "name1"),
            "sales": ("vbak", "vbap", "vbrk", "vbrp", "netwr"),
            "billing": ("vbrk", "vbrp", "fkdat", "netwr"),
            "invoice": ("vbrk", "vbrp", "vbeln"),
            "vendor": ("lfa1", "lifnr", "ekko", "ekpo"),
            "product": ("mara", "makt", "matnr"),
            "material": ("mara", "makt", "matnr"),
            "order": ("vbak", "vbap", "ekko", "ekpo"),
            "purchase": ("ekko", "ekpo"),
        }
        expanded = list(terms)
        for t in terms:
            for hint in topic_hints.get(t, ()):
                if hint not in expanded:
                    expanded.append(hint)

        scored: List[Tuple[int, str, List[str]]] = []
        for t in tables_sorted:
            tl = t.lower()
            colnames = [c["col"].lower() for c in schema_n[t]]
            reasons: List[str] = []
            score = 0
            for term in expanded:
                if term == tl or term in tl:
                    score += 5
                    reasons.append(f"table name matches '{term}'")
                for c in colnames:
                    if term == c or (len(term) >= 4 and term in c):
                        score += 2
                        reasons.append(f"column '{c}'")
                        break
            if score:
                scored.append((score, t, reasons[:4]))
        scored.sort(key=lambda x: (-x[0], x[1].upper()))
        if not scored:
            return MetadataResult(
                operation=op,
                value=[],
                rows=[],
                summary=(
                    "No tables in the connected schema clearly match "
                    f"{', '.join(plan.search_terms) or 'that topic'} "
                    "based on table/column names. I will not invent business meaning."
                ),
                evidence={"source": "schema_catalog", "match_count": 0},
            )
        rows = [
            {"table": t, "score": s, "evidence": "; ".join(r)}
            for s, t, r in scored[:25]
        ]
        top = ", ".join(f"{t} ({'; '.join(r)})" for _, t, r in scored[:8])
        return MetadataResult(
            operation=op,
            value=[t for _, t, _ in scored],
            rows=rows,
            summary=(
                f"Based on schema evidence, {len(scored)} table(s) may relate to "
                f"{', '.join(plan.search_terms) or 'the topic'}. Top matches: {top}."
            ),
            evidence={"source": "schema_catalog", "match_count": len(scored)},
        )

    return MetadataResult(
        operation=op,
        value=None,
        rows=[],
        summary="Unsupported metadata operation.",
        evidence={"source": "schema_catalog"},
    )


def build_metadata_payload(
    question: str,
    plan: MetadataPlan,
    result: MetadataResult,
) -> Dict[str, Any]:
    """HTTP/analysis payload for DATABASE_METADATA answers."""
    rows = result.rows or []
    presentation = "table" if len(rows) > 1 else "none"
    return {
        "type": "analysis",
        "mode": "database_metadata",
        "route": "database_metadata",
        "answer_status": "SUCCESS",
        "failure_class": "SUCCESS",
        "sql": "",
        "rowCount": len(rows),
        "data": rows[:200],
        "charts": [],
        "summary": result.summary,
        "answer": result.summary,
        "keyFindings": [result.summary] if result.summary else [],
        "question": (question or "")[:500],
        "presentation": presentation,
        "meta": {
            "mode": "database_metadata",
            "capability": CAPABILITY,
            "operation": plan.operation,
            "confidence": plan.confidence,
            "evidence": result.evidence,
            "presentation": presentation,
        },
        "pipeline": "database_metadata",
        "sql_generation_method": "schema_catalog",
        "llm_calls": 0,
    }


def answer_database_metadata(
    question: str,
    schema: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Full DATABASE_METADATA path: classify → execute → payload. None if not metadata."""
    plan = classify_metadata_operation(question, schema=schema)
    if plan is None:
        return None
    result = execute_metadata_plan(plan, schema)
    return build_metadata_payload(question, plan, result)
