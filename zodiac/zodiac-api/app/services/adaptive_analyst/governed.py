"""Optional governed execution under the orchestrator (preserves R3/R4 SQL)."""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("zodiac-api.adaptive_analyst.governed")

ExecuteSql = Callable[..., List[Dict[str, Any]]]


def try_governed_database(
    question: str,
    db: Any,
    execute_sql: ExecuteSql,
    *,
    prior_plan: Optional[Dict[str, Any]] = None,
    prior_rows: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Return None so catalog/compiler shortcuts cannot answer SAP analytics."""
    return None
