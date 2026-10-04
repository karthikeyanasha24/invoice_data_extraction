from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("zodiac-api.semantic_metrics")

@dataclass
class Dimension:
    name: str
    description: str
    sap_fields: List[str]  # e.g., ["KNA1.KUNNR", "VBRK.KUNRG"]

@dataclass
class SemanticMetric:
    name: str
    description: str
    category: str  # e.g., "SD", "FI", "CO-PA"
    aliases: List[str]
    base_tables: List[str]
    sql_formula: str  # e.g., "SUM(CAST(VBRK.NETWR AS NUMERIC))"
    currency_field: Optional[str] = None
    time_field: Optional[str] = None
    default_dimensions: List[str] = field(default_factory=list)


class SemanticMetricRegistry:
    def __init__(self) -> None:
        self.metrics: Dict[str, SemanticMetric] = {}
        self.dimensions: Dict[str, Dimension] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        # Dimensions
        self.dimensions["customer"] = Dimension(
            name="customer",
            description="Business customer or sold-to party",
            sap_fields=["KNA1.KUNNR", "VBRK.KUNRG", "VBAK.KUNNR"]
        )
        self.dimensions["material"] = Dimension(
            name="material",
            description="Product or material sold",
            sap_fields=["MARA.MATNR", "VBRP.MATNR", "VBAP.MATNR", "MAKT.MAKTX"]
        )
        self.dimensions["profit_center"] = Dimension(
            name="profit_center",
            description="Profit center for FI/CO reporting",
            sap_fields=["CEPC.PRCTR", "BSEG.PRCTR", "VBRP.PRCTR"]
        )
        self.dimensions["cost_center"] = Dimension(
            name="cost_center",
            description="Cost center for expenses",
            sap_fields=["CSKS.KOSTL", "COEP.KOSTL", "BSEG.KOSTL"]
        )

        # SD Metrics
        self.register_metric(SemanticMetric(
            name="net_sales",
            description="Total net sales revenue from billing documents",
            category="SD",
            aliases=["revenue", "sales", "billed amount", "net revenue"],
            base_tables=["VBRK", "VBRP"],
            sql_formula="SUM(CAST(VBRK.NETWR AS NUMERIC))",
            currency_field="VBRK.WAERK",
            time_field="VBRK.FKDAT",
            default_dimensions=["customer", "material"]
        ))

        # FI/CO Metrics
        self.register_metric(SemanticMetric(
            name="posted_amount",
            description="Amount posted to FI in local currency",
            category="FI",
            aliases=["dmbtr", "local amount", "fi amount"],
            base_tables=["BKPF", "BSEG"],
            sql_formula="SUM(CAST(BSEG.DMBTR AS NUMERIC))",
            currency_field="BSEG.HWAER", # Local currency usually from T001 but implicit in DMBTR
            time_field="BKPF.BUDAT",
            default_dimensions=["profit_center", "cost_center"]
        ))
        
        # CO-PA Metrics
        self.register_metric(SemanticMetric(
            name="contribution_margin",
            description="Contribution margin from profitability analysis",
            category="CO-PA",
            aliases=["margin", "gross margin", "profit"],
            base_tables=["CE1*"], # Represents the operating concern table
            sql_formula="SUM(CAST(CE1*.VVGRW AS NUMERIC)) - SUM(CAST(CE1*.VVVKW AS NUMERIC))", # Example
            currency_field="CE1*.REC_WAERS",
            time_field="CE1*.BUDAT",
            default_dimensions=["customer", "material", "profit_center"]
        ))

        # Manufacturing
        self.register_metric(SemanticMetric(
            name="production_quantity",
            description="Total quantity produced by manufacturing orders",
            category="PP",
            aliases=["yield", "produced qty", "output"],
            base_tables=["AFKO", "AFPO"],
            sql_formula="SUM(CAST(AFPO.WEMNG AS NUMERIC))",
            time_field="AFKO.GLTRP",
            default_dimensions=["material", "plant"]
        ))

    def register_metric(self, metric: SemanticMetric) -> None:
        self.metrics[metric.name.lower()] = metric
        for alias in metric.aliases:
            self.metrics[alias.lower()] = metric

    def resolve_metric(self, term: str) -> Optional[SemanticMetric]:
        """Resolve a natural language term to a governed metric."""
        return self.metrics.get(term.lower().strip())

semantic_registry = SemanticMetricRegistry()
