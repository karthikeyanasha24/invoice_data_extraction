"""
Strict intent contract shared across the entire Generative AI pipeline.

No layer beyond intent extraction may reinterpret the user's question.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Literal, Optional, TypedDict


IntentType = Literal[
    "trend",
    "ranking",
    "comparison",
    "lookup",
    "distribution",
    "raw_inspection",
    "aggregate",
    "breakdown",
]

TimeGranularity = Literal["year", "month", "quarter", "none"]
DomainType = Literal["sap", "app", "mixed"]


@dataclass(frozen=True)
class ColumnRef:
    table: str
    column: str


@dataclass(frozen=True)
class FilterSpec:
    column_ref: ColumnRef
    operator: str
    value: Any


@dataclass(frozen=True)
class DimensionSpec:
    logical: str
    column_ref: ColumnRef
    transform: Literal["YEAR", "MONTH", "QUARTER", "NONE"] = "NONE"
    alias: Optional[str] = None


@dataclass(frozen=True)
class MetricSpec:
    logical: str
    aggregation: Literal["SUM", "AVG", "COUNT", "COUNT_DISTINCT", "NONE"] = "SUM"
    column_ref: Optional[ColumnRef] = None
    alias: Optional[str] = None
    # For derived metrics like profit_margin
    derived: bool = False
    components: Optional[Dict[str, ColumnRef]] = None


@dataclass(frozen=True)
class RankingSpec:
    enabled: bool = False
    order: Literal["desc", "asc"] = "desc"
    limit: int = 5


@dataclass(frozen=True)
class ComparisonSpec:
    enabled: bool = False
    periods: List[str] = field(default_factory=list)


@dataclass
class Intent:
    intent_type: IntentType
    metric: MetricSpec
    dimensions: List[DimensionSpec] = field(default_factory=list)
    filters: List[FilterSpec] = field(default_factory=list)
    time_granularity: TimeGranularity = "none"
    ranking: RankingSpec = field(default_factory=RankingSpec)
    comparison: ComparisonSpec = field(default_factory=ComparisonSpec)
    explicit_tables: List[str] = field(default_factory=list)
    domain: DomainType = "sap"
    debug: Dict[str, Any] = field(default_factory=dict)
    has_customer_names: bool = True

    def to_json(self) -> Dict[str, Any]:
        """Strict JSON (no dataclass objects)."""
        d = asdict(self)
        return d

