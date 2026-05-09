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
        ]
        
        for src, scol, tgt, tcol in known_relations:
            if src in self.tables and tgt in self.tables:
                if scol in self.tables[src].columns and tcol in self.tables[tgt].columns:
                    self.join_graph.append(JoinEdge(src, scol, tgt, tcol))

    def resolve_entities(self, query: str) -> List[TableProfile]:
        """Return candidate tables based on explicit mentions in the text."""
        import re
        # Strip generative routing block if present
        text = re.sub(r'\[ZODIAC_GENERATIVE_CLIENT_ROUTING\].*?\[/ZODIAC_GENERATIVE_CLIENT_ROUTING\]', '', query, flags=re.DOTALL)
        
        words = re.findall(r'\b[A-Za-z0-9_]+\b', text.upper())
        candidates = []
        for word in words:
            if word in self.tables and self.tables[word] not in candidates:
                candidates.append(self.tables[word])
                
        # If no explicit tables found, maybe try to match keywords
        if not candidates:
            # naive fallback
            lower_text = text.lower()
            if "sales" in lower_text or "billing" in lower_text:
                if "VBRK" in self.tables: candidates.append(self.tables["VBRK"])
                if "vbrp" in self.tables: candidates.append(self.tables["vbrp"])
            if "purchase" in lower_text or "po" in lower_text:
                if "EKKO" in self.tables: candidates.append(self.tables["EKKO"])
                if "EKPO" in self.tables: candidates.append(self.tables["EKPO"])
            if "finance" in lower_text or "accounting" in lower_text:
                if "BKPF" in self.tables: candidates.append(self.tables["BKPF"])
                if "BSEG" in self.tables: candidates.append(self.tables["BSEG"])
                
        return candidates

    def suggest_join_paths(self, tables: List[str]) -> List[JoinEdge]:
        """Given a set of tables, return the shortest join path."""
        # Graph search algorithm
        return []

schema_intelligence = SchemaIntelligenceService()
