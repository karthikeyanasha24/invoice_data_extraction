"""
Regression: semantic dictionary fast-path must not return industry SQL without industry intent.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.semantic_sql_resolver import semantic_fast_path_matches_question  # noqa: E402


def main() -> int:
    sql_industry = (
        'SELECT t."brtxt" AS industry, SUM(v."netwr") AS value FROM vbrp v '
        'JOIN "VBRK" r ON v."vbeln" = r."vbeln" JOIN kna1 k ON r."kunag" = k."kunnr" '
        'LEFT JOIN "T016T" t ON k."brsch" = t."brsch" GROUP BY t."brtxt"'
    )
    assert semantic_fast_path_matches_question("revenue by customer", sql_industry) is False
    assert semantic_fast_path_matches_question("revenue by industry", sql_industry) is True
    assert semantic_fast_path_matches_question("top industries by revenue", sql_industry) is True
    print("OK: semantic_fast_path_matches_question")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
