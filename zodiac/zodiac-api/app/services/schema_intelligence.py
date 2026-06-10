from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("zodiac-api.schema_intelligence")


@dataclass
class ColumnProfile:
    name: str
    data_type: str
    description: str = ""
    semantic_role: str = ""  # e.g., "amount", "date", "key", "dimension"
    is_primary_key: bool = False
    is_foreign_key: bool = False


@dataclass
class JoinEdge:
    source_table: str
    source_column: str
    target_table: str
    target_column: str
    relationship_type: str = "1:N"  # e.g., "1:1", "1:N", "N:1"
    confidence: float = 1.0


@dataclass
class TableProfile:
    name: str
    columns: Dict[str, ColumnProfile]
    table_type: str = "unknown"  # "transaction", "master", "text"
    description: str = ""
    domain: str = ""  # e.g., "FI", "CO", "MM", "SD"
    row_count_estimate: Optional[int] = None


class SchemaIntelligenceService:
    """
    Phase 1: Schema Intelligence Layer
    Builds a metadata graph from SAP catalog and schema files.
    """

    def __init__(self) -> None:
        self.tables: Dict[str, TableProfile] = {}
        self.join_graph: List[JoinEdge] = []
        self._initialized: bool = False

    def initialize(self, schema_export_path: Path, table_knowledge_path: Path) -> None:
        """Load schemas and build intelligence graph."""
        if self._initialized:
            return

        self._load_schema_export(schema_export_path)
        self._load_table_knowledge(table_knowledge_path)
        self._infer_join_edges()
        self._classify_table_types()
        self._enrich_columns()

        self._initialized = True
        logger.info("SchemaIntelligenceService initialized with %d tables and %d join edges.", len(self.tables), len(self.join_graph))

    def _load_schema_export(self, path: Path) -> None:
        if not path.exists():
            logger.warning("Schema export not found at %s", path)
            return

        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        tables_meta = data.get("tables_meta", {})
        for table_name, columns in tables_meta.items():
            profile = TableProfile(name=table_name, columns={})
            for col in columns:
                col_name = col.get("column", "")
                data_type = col.get("data_type", "")
                if col_name:
                    profile.columns[col_name] = ColumnProfile(
                        name=col_name,
                        data_type=data_type
                    )
            self.tables[table_name] = profile

    def _load_table_knowledge(self, path: Path) -> None:
        if not path.exists():
            return
        
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
            
        for table_name, info in data.items():
            if table_name in self.tables:
                tbl = self.tables[table_name]
                tbl.description = info.get("description", "")
                
                # Knowledge can have explicit joins
                for join_hint in info.get("joins", []):
                    pass # We will parse explicit joins later
                    
    def _classify_table_types(self) -> None:
        """Infer table type (transaction, master, text) based on naming conventions and typical SAP structures."""
        for name, profile in self.tables.items():
            name_upper = name.upper()
            if name_upper.endswith("T"):  # Often Text tables like MAKT, CSKT, LFA1 is exception but generally T means Text
                if name_upper in {"MAKT", "CSKT", "T016T"}:
                    profile.table_type = "text"
            elif name_upper in {"VBRK", "VBRP", "VBAK", "VBAP", "LIKP", "LIPS", "EKKO", "EKPO", "BKPF", "BSEG"}:
                profile.table_type = "transaction"
            elif name_upper in {"MARA", "KNA1", "LFA1", "CSKS", "CEPC"}:
                profile.table_type = "master"
                
    def _enrich_columns(self) -> None:
        """Enrich columns with semantic roles (amount, date, key)."""
        amount_fields = {"NETWR", "DMBTR", "WRBTR", "MWSBK"}
        date_fields = {"FKDAT", "BUDAT", "BLDAT", "ERDAT", "AEDAT"}
        
        for tbl in self.tables.values():
            for col_name, col in tbl.columns.items():
                cu = col_name.upper()
                if cu in amount_fields:
                    col.semantic_role = "amount"
                elif cu in date_fields:
                    col.semantic_role = "date"
                elif cu in {"MANDT", "VBELN", "MATNR", "KUNNR", "LIFNR", "BUKRS", "GJAHR", "BELNR"}:
                    col.semantic_role = "key"

    def _resolve_column_key(self, table: str, col: str) -> Optional[str]:
        """SAP exports use lowercase column keys; edge definitions may be uppercase."""
        cols = self.tables[table].columns
        if col in cols:
            return col
        low = col.lower()
        if low in cols:
            return low
        up = col.upper()
        if up in cols:
            return up
        return None

    def _infer_join_edges(self) -> None:
        """Automatically detect relationships based on common SAP keys."""
        # This is a naive implementation; the enterprise version will be much more sophisticated
        known_relations = [
            ("VBRK", "VBELN", "VBRP", "VBELN"),
            ("VBAK", "VBELN", "VBAP", "VBELN"),
            ("LIKP", "VBELN", "LIPS", "VBELN"),
            ("EKKO", "EBELN", "EKPO", "EBELN"),
            ("BKPF", "BELNR", "BSEG", "BELNR"),
            ("BKPF", "BUKRS", "BSEG", "BUKRS"),
            ("BKPF", "GJAHR", "BSEG", "GJAHR"),
            # Master-data joins (added when both tables appear in schema prompt → retrieve_context hints)
            ("VBRK", "KUNAG", "KNA1", "KUNNR"),
            ("VBRK", "KUNRG", "KNA1", "KUNNR"),
            ("VBAK", "KUNNR", "KNA1", "KUNNR"),
            ("LIKP", "KUNNR", "KNA1", "KUNNR"),
            ("VBRP", "MATNR", "MAKT", "MATNR"),
            ("VBAP", "MATNR", "MAKT", "MATNR"),
            ("EKPO", "MATNR", "MAKT", "MATNR"),
            ("LIPS", "MATNR", "MAKT", "MATNR"),
            ("EKKO", "LIFNR", "LFA1", "LIFNR"),
            ("MARD", "MATNR", "MARA", "MATNR"),
            ("MARD", "MATNR", "MAKT", "MATNR"),
            ("MBEW", "MATNR", "MARA", "MATNR"),
            ("MBEW", "MATNR", "MAKT", "MATNR"),
            # Pricing (header knumv → condition records)
            ("VBRK", "KNUMV", "KONV", "KNUMV"),
            ("VBAK", "KNUMV", "KONV", "KNUMV"),
            # Schedule lines
            ("VBAP", "VBELN", "VBEP", "VBELN"),
            # Document flow (preceding ↔ subsequent document numbers)
            ("VBAK", "VBELN", "VBFA", "VBELV"),
            ("VBRK", "VBELN", "VBFA", "VBELN"),
            ("LIKP", "VBELN", "VBFA", "VBELN"),
            ("BSAD", "KUNNR", "KNA1", "KUNNR"),
            ("BSAD", "BELNR", "BSEG", "BELNR"),
        ]
        
        for src, scol, tgt, tcol in known_relations:
            if src not in self.tables or tgt not in self.tables:
                continue
            sk = self._resolve_column_key(src, scol)
            tk = self._resolve_column_key(tgt, tcol)
            if sk and tk:
                self.join_graph.append(JoinEdge(src, sk, tgt, tk))

    def resolve_entities(self, query: str) -> List[TableProfile]:
        """Explicit SAP table tokens plus domain keywords (always merged, deduped)."""
        import re

        # Strip generative routing block if present
        text = re.sub(
            r"\[ZODIAC_GENERATIVE_CLIENT_ROUTING\].*?\[/ZODIAC_GENERATIVE_CLIENT_ROUTING\]",
            "",
            query,
            flags=re.DOTALL,
        )

        words = re.findall(r"\b[A-Za-z0-9_]+\b", text.upper())
        candidates: List[TableProfile] = []
        for word in words:
            if word in self.tables and self.tables[word] not in candidates:
                candidates.append(self.tables[word])

        def _append_table(name: str) -> None:
            u = name.upper()
            if u in self.tables and self.tables[u] not in candidates:
                candidates.append(self.tables[u])

        # Keyword domains always augment explicit table mentions (deduped; planner caps breadth).
        lower_text = text.lower()
        if any(k in lower_text for k in ("billing", "invoice", "revenue", "sales")):
            for t in ("VBRK", "VBRP", "KNA1"):
                _append_table(t)
        if "delivery" in lower_text or "shipment" in lower_text:
            for t in ("LIKP", "LIPS"):
                _append_table(t)
        if "purchase" in lower_text or "procurement" in lower_text or re.search(r"\bpo\b", lower_text):
            for t in ("EKKO", "EKPO", "LFA1"):
                _append_table(t)
        if "customer" in lower_text or "payer" in lower_text or "sold-to" in lower_text:
            _append_table("KNA1")
        if "vendor" in lower_text or "supplier" in lower_text:
            _append_table("LFA1")
        if "material" in lower_text or "product" in lower_text:
            for t in ("MARA", "MAKT"):
                _append_table(t)
        if any(
            k in lower_text
            for k in ("finance", "accounting", "gl ", "ledger", "posting", "journal")
        ):
            for t in ("BKPF", "BSEG"):
                _append_table(t)
        if any(
            k in lower_text
            for k in (
                "inventory",
                "stock",
                "warehouse",
                "plant stock",
                "bin",
                "storage location",
                "goods movement",
                "mm ",
                "moving average",
                "valuation",
            )
        ):
            for t in ("MARD", "MBEW", "MARA", "MAKT"):
                _append_table(t)
            _append_table("MKPF")
        if (
            "plant" in lower_text
            or "factory" in lower_text
            or re.search(r"\bwerk\b", lower_text)
            or "storage location" in lower_text
            or re.search(r"\bsloc\b", lower_text)
        ):
            for t in ("MARD", "LIKP", "LIPS", "EKPO", "VBRP"):
                _append_table(t)
        if any(
            k in lower_text
            for k in (
                "pricing",
                "condition record",
                "condition type",
                "discount",
                "net price",
                "rebate",
            )
        ) or re.search(r"\bkschl\b", lower_text):
            for t in ("KONV", "VBRK", "VBRP", "VBAK", "VBAP"):
                _append_table(t)
        if any(
            k in lower_text
            for k in (
                "schedule line",
                "schedule lines",
                "confirmed quantity",
                "delivery schedule",
                "requested delivery",
            )
        ) or re.search(r"\bvbep\b", lower_text):
            for t in ("VBEP", "VBAP", "VBAK"):
                _append_table(t)
        if any(
            k in lower_text
            for k in (
                "document flow",
                "preceding document",
                "subsequent document",
                "flow between",
            )
        ) or re.search(r"\bvbfa\b", lower_text):
            for t in ("VBFA", "VBAK", "VBRK", "LIKP", "VBRP"):
                _append_table(t)
        if any(
            k in lower_text
            for k in (
                "accounts receivable",
                "open item",
                "open items",
                "customer balance",
                "clearing document",
                "ar aging",
                "outstanding balance",
            )
        ) or re.search(r"\bdunning\b", lower_text):
            for t in ("BSAD", "BSEG", "BKPF", "KNA1"):
                _append_table(t)
        if any(k in lower_text for k in ("cost center", "cost centre")):
            _append_table("CSKS")
        if any(
            k in lower_text
            for k in ("purchase requisition", "requisition", "pr line")
        ) or re.search(r"\beban\b", lower_text):
            _append_table("EBAN")

        # ── SAT / CFDI / Inbound document routing ────────────────────────────
        # "SAT documents", "CFDI", "inbound invoice", "inbound document",
        # "supplier sent", "payment complement" all map to sat_documents.
        _SAT_TRIGGERS = (
            "sat document", "sat invoice", "sat credit", "cfdi",
            "inbound document", "inbound invoice", "inbound sat",
            "payment complement", "sat_document", "received document",
            "most sat", "supplier sent", "suppliers sent",
        )
        if any(k in lower_text for k in _SAT_TRIGGERS) or re.search(r"\bsat\b", lower_text):
            for t in ("sat_documents", "sat_simple_merged"):
                if t in self.tables and self.tables[t] not in candidates:
                    candidates.insert(0, self.tables[t])  # highest priority

        return candidates

    def suggest_join_paths(self, tables: List[str]) -> List[JoinEdge]:
        """Given a set of tables, return the shortest join path."""
        # Graph search algorithm
        return []

schema_intelligence = SchemaIntelligenceService()
