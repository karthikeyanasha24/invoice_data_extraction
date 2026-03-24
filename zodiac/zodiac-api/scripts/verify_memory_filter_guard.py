"""
Regression guard for ai_query_memory scored reuse.

Ensures similarity scoring remains conservative enough that questions differing by
explicit year/category filters do not hit fuzzy reuse threshold.
"""
from __future__ import annotations

import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lightweight stubs so ai_query_memory_service can import in minimal environments.
if "sqlalchemy" not in sys.modules:
    sqlalchemy_stub = types.ModuleType("sqlalchemy")
    sqlalchemy_stub.case = lambda *args, **kwargs: None  # type: ignore
    sqlalchemy_orm_stub = types.ModuleType("sqlalchemy.orm")
    sqlalchemy_orm_stub.Session = object  # type: ignore
    sys.modules["sqlalchemy"] = sqlalchemy_stub
    sys.modules["sqlalchemy.orm"] = sqlalchemy_orm_stub

from app.services.ai_query_memory_service import _similarity_score


def main() -> int:
    threshold = 17

    record_sql_1999_cat_a = """
    SELECT SUM(CAST(NULLIF(TRIM(CAST(v."netwr" AS TEXT)), '') AS NUMERIC)) AS total_sales
    FROM vbrp v
    JOIN "VBRK" r ON LPAD(TRIM(v."vbeln"),10,'0') = LPAD(TRIM(r."vbeln"),10,'0')
    WHERE SUBSTRING(TRIM(r."fkdat"),1,4) = '1999' AND r."fktyp" = 'A'
    """

    # Same intent family, but explicit filter differs (year/category); should not reuse.
    score_filter_mismatch = _similarity_score(
        question="total sales for year 2000 and billing category B",
        record_question="total sales for year 1999 and billing category A",
        record_sql=record_sql_1999_cat_a,
        source="user",
        use_count=5,
    )
    assert (
        score_filter_mismatch < threshold
    ), f"Expected score < {threshold} for mismatched filters, got {score_filter_mismatch}"

    # Exact logical match should still pass threshold.
    score_match = _similarity_score(
        question="total sales for year 1999 and billing category A",
        record_question="total sales for year 1999 and billing category A",
        record_sql=record_sql_1999_cat_a,
        source="user",
        use_count=1,
    )
    assert score_match >= threshold, f"Expected score >= {threshold} for true match, got {score_match}"

    print("OK: memory filter guard scoring")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
