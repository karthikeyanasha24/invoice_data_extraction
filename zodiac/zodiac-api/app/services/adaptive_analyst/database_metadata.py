"""Generic DATABASE_METADATA capability for Adaptive AI Analyst.

Distinguishes schema/catalog introspection from business analytics.

Operations (capabilities, not phrase handlers):
  COUNT_TABLES, LIST_TABLES, COUNT_COLUMNS, LIST_COLUMNS,
  DESCRIBE_TABLE, SEARCH_TABLES, SEARCH_COLUMNS, DESCRIBE_SCHEMA

Answers are derived from the authorized schema catalog dict
({table: [{col, type}, ...]}), never from hardcoded counts or /health.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
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
LIST_DATA_SOURCES = "LIST_DATA_SOURCES"

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
_FIELD_TARGET = re.compile(
    r"\b(?:column\s+names?|fields?)\s+(?:for|representing|that\s+represent|"
    r"corresponding\s+to)\s+(.+?)(?:[?.!]|$)",
    re.I,
)
_SOURCE_INVENTORY = re.compile(
    r"^\s*(?:which|what|list|show|describe|how\s+many|tell\s+me\s+(?:about\s+)?)\s+"
    r"(?:(?:me|the|all|connected|available)\s+)*(?:data\s+sources?|databases?|datasets?|connections?)\b.{0,55}"
    r"\b(?:connected|available|accessible|have|access)\b|"
    r"^\s*(?:which|what|list|show|describe)\s+(?:the\s+)?(?:connected|available)\s+"
    r"(?:data\s+sources?|databases?|datasets?)\b",
    re.I,
)
_CONTEXTUAL_CATALOG_REFERENCE = re.compile(
    r"\b(?:those|these|that|same|above|previous|prior|earlier)\b|"
    r"\bjust\s+(?:said|mention(?:ed)?|list(?:ed)?|show(?:ed)?)\b|"
    r"\byou\s+just\s+(?:said|mention(?:ed)?|list(?:ed)?|show(?:ed)?)\b|"
    r"\byou\s+(?:said|mention(?:ed)?|list(?:ed)?|show(?:ed)?)\b|"
    r"\bfrom\s+the\s+results?\b",
    re.I,
)
_ANALYSIS_EXECUTION_CUE = re.compile(
    r"\b(?:run|execute|perform|calculate|compare|rank|return)\b",
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
    list_all: bool = False
    topic_terms: List[str] = field(default_factory=list)


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


def _meaning_tokens(text: str) -> set[str]:
    """Small linguistic normalization shared by query and catalog labels."""
    tokens = set(re.findall(r"[a-z0-9]+", (text or "").lower().replace("_", " ")))
    normalized = {
        token[:-3] + "y" if token.endswith("ies") else
        token[:-1] if token.endswith("s") and not token.endswith("ss") and token != "sales" else token
        for token in tokens
    }
    return normalized - _STOP_TOKENS


def _split_topics(text: str) -> List[str]:
    topics = []
    for part in re.split(r"\s*(?:,|\band\b|\bor\b)\s*", text, flags=re.I):
        part = re.sub(r"[?.!].*$", "", part).strip(" ,;:-")
        part = re.sub(r"\b(?:information|data|available|in the database)\b", "", part, flags=re.I)
        part = re.sub(r"\s+", " ", part).strip()
        if _meaning_tokens(part):
            topics.append(part)
    return topics[:8]


def _field_request(question: str) -> Tuple[List[str], List[str]]:
    """Extract requested field meanings and optional business scope, not answers."""
    q = (question or "").strip()
    direct = re.search(
        r"\b(?:fields?|columns?)\b.{0,25}\b(?:store|stores|represent|represents|contain|contains|hold|holds)\s+(?:the\s+)?(.+?)(?:[?.!]|$)",
        q, re.I,
    )
    if direct:
        return _split_topics(direct.group(1)), []
    explicit = _FIELD_TARGET.search(q)
    if explicit:
        return _split_topics(explicit.group(1)), []
    pre = re.search(
        r"\b(?:which|what|show|list)\s+(?:the\s+)?(.+?)\s+(?:fields?|columns?)\b(?:\s+(?:are\s+)?available)?\s+(?:for|in|on|of)\s+(.+?)(?:[?.!]|$)",
        q, re.I,
    )
    if pre and not re.search(r"\b(?:all|exact|physical)\b", pre.group(1), re.I):
        return _split_topics(pre.group(1)), _split_topics(pre.group(2))
    return [], []


def _table_topics(question: str) -> List[str]:
    match = re.search(
        r"\btables?\s+(?:(?:contain|contains|containing|store|stores|have|hold|holds|include|includes)\s+|(?:for|about|with|related\s+to)\s+)(.+?)(?:[?.!]|$)",
        question or "", re.I,
    )
    return _split_topics(match.group(1)) if match else _search_terms(question)


def _table_semantics(table: str) -> Dict[str, str]:
    try:
        from ..schema_intelligence_registry import get_schema_registry

        meta = get_schema_registry().get_table(table)
    except Exception:
        meta = None
    return {
        "description": str(getattr(meta, "description", "") or ""),
        "domain": str(getattr(meta, "domain", "") or ""),
        "grain": str(getattr(meta, "grain", "") or ""),
    }


def _column_meanings(table: str) -> Dict[str, str]:
    mapping_path = Path(__file__).resolve().parents[2] / "table_mapping" / f"{table.upper()}.json"
    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        str(column).lower(): str(label).replace("_", " ").lower()
        for column, label in mapping.items()
        if label and not str(label).startswith("[")
    }


def _topic_table_score(topic: str, table: str, semantics: Dict[str, str]) -> float:
    requested = _meaning_tokens(topic)
    if not requested:
        return 0.0
    # The primary subject describes the table's role. A flow description that
    # mentions a downstream invoice does not turn a delivery table into billing.
    primary = re.split(r"[.;]", semantics["description"], maxsplit=1)[0]
    role_tokens = _meaning_tokens(primary + " " + semantics["grain"])
    matched = requested & role_tokens
    if not matched:
        return 0.0
    score = 8.0 * len(matched) / len(requested)
    score += 3.0 * len(requested & _meaning_tokens(semantics["domain"])) / len(requested)
    if requested <= role_tokens:
        score += 6.0
    if requested <= _meaning_tokens(primary):
        score += 3.0
        primary_tokens = _meaning_tokens(primary)
        score += 4.0 * len(matched) / max(1, len(primary_tokens))
        if "master" in primary_tokens:
            score += 2.0
    return score


def search_column_meanings(
    plan: MetadataPlan, schema: Dict[str, List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Resolve meanings only to physical fields within the authorized catalog."""
    tables = [plan.table_name] if plan.table_name in schema else sorted(schema)
    table_roles = {table: _table_semantics(table) for table in tables}
    if plan.topic_terms and not plan.table_name:
        scores = {
            table: max(_topic_table_score(topic, table, table_roles[table]) for topic in plan.topic_terms)
            for table in tables
        }
        best_scope = max(scores.values(), default=0)
        tables = [table for table in tables if scores[table] >= max(4.0, best_scope - 3.0)]
    selected: List[Dict[str, Any]] = []
    for term in plan.search_terms:
        physical_matches = [
            {
                "table": table, "column": column["col"], "type": column["type"],
                "matched_term": term,
                "meaning": _column_meanings(table).get(str(column["col"]).lower(), str(column["col"])),
                "table_role": table_roles[table]["description"],
            }
            for table in tables for column in schema[table]
            if str(column["col"]).lower() == term.lower().strip()
        ]
        if physical_matches:
            selected.extend(row for row in physical_matches if not any(
                existing["table"] == row["table"] and existing["column"] == row["column"]
                for existing in selected
            ))
            continue
        requested = _meaning_tokens(term)
        # Amount/value and identifier/number are language equivalents, not
        # dataset-specific field or table substitutions.
        requested = {"value" if token == "amount" else "number" if token == "identifier" else token for token in requested}
        ranked = []
        for table in tables:
            semantics = table_roles[table]
            mappings = _column_meanings(table)
            primary = re.split(r"[.;]", semantics["description"], maxsplit=1)[0]
            primary_tokens = _meaning_tokens(primary)
            scope_tokens = set().union(*(_meaning_tokens(topic) for topic in plan.topic_terms)) if plan.topic_terms else requested
            for column in schema[table]:
                physical_name = str(column["col"])
                description = mappings.get(physical_name.lower(), "")
                label_tokens = _meaning_tokens(description)
                label_tokens = {"value" if token == "amount" else token for token in label_tokens}
                exact_name = term.lower().strip() == physical_name.lower()
                overlap = len(requested & label_tokens)
                if not overlap and not exact_name:
                    continue
                scope_overlap = len(scope_tokens & label_tokens)
                table_relevance = _topic_table_score(" ".join(scope_tokens), table, semantics)
                is_primary_grain = bool(primary_tokens & {"header", "master"})
                starts_with_target = description.startswith(term.lower())
                rank = (
                    exact_name, bool(requested) and requested <= label_tokens,
                    overlap / max(1, len(requested)), scope_overlap,
                    table_relevance, is_primary_grain, starts_with_target,
                    -len(physical_name), overlap / max(1, len(label_tokens)),
                )
                ranked.append((rank, {
                    "table": table, "column": physical_name, "type": column["type"],
                    "matched_term": term, "meaning": description or physical_name,
                    "table_role": semantics["description"],
                }))
        if ranked:
            ranked.sort(key=lambda item: item[0], reverse=True)
            row = ranked[0][1]
            if not any(existing["table"] == row["table"] and existing["column"] == row["column"] for existing in selected):
                selected.append(row)
    return selected


def is_database_metadata_question(question: str) -> bool:
    """True when the question asks about schema/catalog, not business facts."""
    q = (question or "").strip()
    if not q:
        return False
    ql = q.lower()

    # Referential questions about an earlier answer need conversation context.
    # Do not answer them with an unrelated global catalog count/list before the
    # dialogue resolver can inspect the prior turn.
    if _CONTEXTUAL_CATALOG_REFERENCE.search(ql):
        return False
    if _SOURCE_INVENTORY.search(ql):
        return True

    # Mentioning schema/columns as a constraint on an analysis does not change
    # the requested capability from analytics to catalog introspection.
    if _BUSINESS_FACT.search(ql) and _ANALYSIS_EXECUTION_CUE.search(ql):
        return False

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
        # Follow-ups like "list all 121" / "I want all listed" after a table preview.
        if re.search(
            r"(?i)\b(list|show|give|want|need)\s+(?:me\s+)?all\s+\d+\b"
            r"|\b(?:list|show)\s+all\s*(?:listed)?\s*[?.!]*$"
            r"|\b(all|every)\s+(of\s+them|tables?)\b"
            r"|\b\d+\s+to\s+be\s+listed\b",
            ql,
        ):
            return True
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
    if _SOURCE_INVENTORY.search(ql):
        return MetadataPlan(operation=LIST_DATA_SOURCES, confidence=0.96)
    field_targets, scope = _field_request(q)
    if field_targets:
        return MetadataPlan(
            operation=SEARCH_COLUMNS,
            table_name=table,
            search_terms=field_targets,
            topic_terms=[] if table else scope,
            confidence=0.95,
        )
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
            return MetadataPlan(operation=SEARCH_TABLES, search_terms=_table_topics(q), confidence=0.88)
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

    wants_all = bool(
        re.search(
            r"(?i)\b(all|entire|full|complete)\b|\ball\s+\d+\b|\b\d+\s+to\s+be\s+listed\b",
            ql,
        )
    )
    if (
        re.search(r"\btables?|entities\b", ql)
        or _LIST_CUE.search(ql)
        or wants_all
    ):
        if wants_all or _LIST_CUE.search(ql) or re.search(r"\bwhat\b|\bwhich\b|\bavailable\b|\bexist", ql):
            return MetadataPlan(operation=LIST_TABLES, confidence=0.92, list_all=wants_all)
        return MetadataPlan(operation=LIST_TABLES, confidence=0.8, list_all=wants_all)

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

    if op == LIST_DATA_SOURCES:
        domains: Dict[str, List[str]] = {}
        for table in tables_sorted:
            semantics = _table_semantics(table)
            domain = semantics["domain"] or "unclassified schema tables"
            domains.setdefault(domain, []).append(table)
        rows = [
            {"domain": domain, "table_count": len(names), "tables": ", ".join(names)}
            for domain, names in sorted(domains.items())
        ]
        scope = "; ".join(f"{domain}: {len(names)} tables" for domain, names in sorted(domains.items()))
        return MetadataResult(
            operation=op,
            value=rows,
            rows=rows,
            summary=(
                f"The connected schema exposes {table_count} tables across these catalog domains: {scope}. "
                "This inventory verifies available tables; the schema catalog does not identify database server or connection-provider details."
            ),
            evidence={"source": "schema_catalog_and_table_metadata", "table_count": table_count},
        )

    if op == LIST_TABLES:
        rows = [{"table": t, "column_count": len(schema_n[t])} for t in tables_sorted]
        list_all = bool(getattr(plan, "list_all", False))
        if list_all or table_count <= 40:
            # Full list when asked ("all 121") or small schemas.
            listing = ", ".join(tables_sorted)
            summary = f"There are {table_count} tables available: {listing}."
        else:
            preview = ", ".join(tables_sorted[:20])
            more = f" (showing 20 of {table_count}; ask to list all {table_count} tables to see every name)"
            summary = f"There are {table_count} tables available{more}: {preview}."
        return MetadataResult(
            operation=op,
            value=tables_sorted,
            rows=rows,
            summary=summary,
            evidence={
                "source": "schema_catalog",
                "table_count": table_count,
                "listed_all": bool(list_all or table_count <= 40),
            },
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
        selected = search_column_meanings(plan, schema_n)
        if selected:
            labels = [f"{row['matched_term']} → {row['table']}.{row['column']} ({row['meaning']})" for row in selected]
            return MetadataResult(
                operation=op,
                value=selected,
                rows=selected,
                summary=f"Verified schema field matches: {', '.join(labels)}.",
                evidence={"source": "schema_catalog_and_column_mappings", "match_count": len(selected)},
            )
        return MetadataResult(
            operation=op, value=[], rows=[],
            summary=f"No verified columns matched {', '.join(plan.search_terms) or 'the requested meaning'} in the connected schema.",
            evidence={"source": "schema_catalog_and_column_mappings", "match_count": 0},
        )

    if op == SEARCH_TABLES:
        rows: List[Dict[str, Any]] = []
        shared_grains = set().union(*(_meaning_tokens(topic) for topic in plan.search_terms)) & {"header", "item", "line", "detail"}
        for topic in plan.search_terms:
            ranked = []
            topic_tokens = _meaning_tokens(topic)
            requested_grains = shared_grains
            for table in tables_sorted:
                semantics = _table_semantics(table)
                role = _meaning_tokens(semantics["description"].split(".")[0] + " " + semantics["grain"])
                if requested_grains and not requested_grains & role:
                    continue
                score = _topic_table_score(topic, table, semantics)
                if score:
                    ranked.append((score, table, semantics))
                elif any(term == table.lower() or term in c["col"].lower() for term in topic_tokens for c in schema_n[table]):
                    ranked.append((2.0, table, semantics))
            ranked.sort(key=lambda item: (-item[0], item[1].upper()))
            if not ranked:
                continue
            # A broad topic can match dozens of incidental columns. Present the
            # directly described table roles for each topic, not their union.
            cutoff = max(2.0, ranked[0][0] - 4.0)
            for score, table, semantics in ranked[:3]:
                if score < cutoff:
                    continue
                existing = next((row for row in rows if row["table"] == table), None)
                if existing:
                    existing["matched_topics"] += ", " + topic
                    continue
                rows.append({
                    "table": table, "matched_topics": topic,
                    "role": semantics["description"], "domain": semantics["domain"],
                    "grain": semantics["grain"], "score": score,
                    "evidence": "verified physical table and catalog role",
                })
        if not rows:
            return MetadataResult(
                operation=op, value=[], rows=[],
                summary=f"No tables in the connected schema clearly match {', '.join(plan.search_terms) or 'that topic'} from verified catalog evidence.",
                evidence={"source": "schema_catalog_and_table_metadata", "match_count": 0},
            )
        listing = "; ".join(f"{row['table']}: {row['role'] or row['matched_topics']}" for row in rows)
        return MetadataResult(
            operation=op,
            value=[row["table"] for row in rows], rows=rows,
            summary=f"Relevant connected tables by verified catalog role: {listing}",
            evidence={"source": "schema_catalog_and_table_metadata", "match_count": len(rows)},
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
        "type": "database_metadata",
        "mode": "database_metadata",
        "route": "database_metadata",
        "answer_status": "SUCCESS",
        "failure_class": "SUCCESS",
        "sql": "",
        "rowCount": len(rows),
        "data": rows[:500],
        "charts": [],
        "summary": result.summary,
        "answer": result.summary,
        # Do not echo summary into keyFindings — frontend would render it twice.
        "keyFindings": [],
        "question": (question or "")[:500],
        "presentation": presentation,
        "meta": {
            "mode": "database_metadata",
            "capability": CAPABILITY,
            "operation": plan.operation,
            "confidence": plan.confidence,
            "evidence": result.evidence,
            "presentation": presentation,
            "list_all": bool(getattr(plan, "list_all", False)),
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
