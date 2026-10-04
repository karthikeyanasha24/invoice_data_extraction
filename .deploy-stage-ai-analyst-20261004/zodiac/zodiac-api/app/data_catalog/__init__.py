"""Governed SAP data catalog — single source of truth for R5 source selection.

Physical structure always comes from the migrated schema snapshot (schema_full.json)
or a live information_schema inventory. Documentation / glossary never invents columns.
External research never becomes executable SQL.
"""
from .physical import (
    catalog_table_names,
    column_names,
    has_column,
    has_table,
    load_physical_schema,
    sap_business_tables,
)
from .registry import (
    DIMENSIONS,
    METRICS,
    RELATIONSHIPS,
    TABLE_ENTRIES,
    domain_for_table,
    get_metric,
    get_table_entry,
    tables_for_domain,
)
from .source_selector import SourceSpec, select_source

__all__ = [
    "DIMENSIONS",
    "METRICS",
    "RELATIONSHIPS",
    "TABLE_ENTRIES",
    "SourceSpec",
    "catalog_table_names",
    "column_names",
    "domain_for_table",
    "get_metric",
    "get_table_entry",
    "has_column",
    "has_table",
    "load_physical_schema",
    "sap_business_tables",
    "select_source",
    "tables_for_domain",
]
