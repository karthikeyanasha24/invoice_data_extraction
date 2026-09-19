"""Temporary regression check for year-2000 sales failures."""
from __future__ import annotations

import re

from app.services.adaptive_currency_strategy import inject_currency_filter_sql
from app.services.plan_satisfaction import result_matches_analytical_intent


def main() -> None:
    sql = (
        'SELECT SUM(CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "total_sales", '
        '"VBRK"."fkdat", SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) AS "year"\n'
        'FROM "VBRK"\n'
        "WHERE TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)) <> '' "
        "AND SUBSTRING(TRIM(CAST(\"VBRK\".\"fkdat\" AS TEXT)), 1, 4) = '2000'\n"
        'GROUP BY "VBRK"."fkdat"'
    )
    fixed = inject_currency_filter_sql(sql, "VBRK", "waerk", "USD")
    print("snippet:\n", fixed[fixed.lower().find("from") :])
    assert len(re.findall(r"\bWHERE\b", fixed, flags=re.I)) == 1, fixed
    assert "waerk" in fixed.lower()
    assert "USD" in fixed
    assert "fkdat" in fixed.lower()

    sql2 = (
        'SELECT SUM(CAST("VBRK"."netwr" AS NUMERIC)) AS total FROM "VBRK" '
        "WHERE SUBSTRING(\"VBRK\".\"fkdat\", 1, 4) = '2000' AND \"VBRK\".\"waerk\" = 'USD' "
        'GROUP BY "VBRK"."fkdat"'
    )
    assert inject_currency_filter_sql(sql2, "VBRK", "waerk", "USD") == sql2

    q = "show me sales for the year 2000"
    polluted = {
        "dimensions": ["date", "product", "customer", "country", "region", "sales_person"],
        "group_by": [],
        "measure": {"concept": "sales", "aggregation": "SUM"},
        "time_filter": {"type": "calendar_year", "value": "2000", "years": ["2000"]},
    }
    rows = [{"year": "2000", "total_sales": 12345.67}]
    sql3 = (
        'SELECT SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) AS "year", '
        'SUM(CAST(NULLIF(TRIM(CAST("VBRK"."netwr" AS TEXT)), \'\') AS NUMERIC)) AS "total_sales" '
        'FROM "VBRK" WHERE SUBSTRING(TRIM(CAST("VBRK"."fkdat" AS TEXT)), 1, 4) = \'2000\' GROUP BY 1'
    )
    warnings = result_matches_analytical_intent(rows, q, polluted, sql=sql3)
    print("warnings", warnings)
    assert not any("customer" in w or "country" in w for w in warnings)
    print("ALL UNIT CHECKS OK")


if __name__ == "__main__":
    main()
