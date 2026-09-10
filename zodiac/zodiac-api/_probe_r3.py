from app.services.adaptive_currency_strategy import inject_currency_filter_sql
from app.services.semantic_requirements import required_semantics
from app.services.adaptive_structured_sql import build_partitioned_topn_sql, build_relative_document_list_sql

sql = """SELECT * FROM (
  SELECT inner_q.*, ROW_NUMBER() OVER (PARTITION BY "country" ORDER BY "total_sales" DESC) AS rank_in_partition
  FROM (
SELECT TRIM(c."land1") AS "country", SUM(k."netwr") AS "total_sales"
FROM "VBRK" k LEFT JOIN "KNA1" c ON 1=1
GROUP BY 1
  ) inner_q
) ranked WHERE rank_in_partition <= 5"""
out = inject_currency_filter_sql(sql, "VBRK", "waerk", "USD")
over_part = out.split("PARTITION BY", 1)[1].split(")", 1)[0] if "PARTITION BY" in out else ""
print("BAD_IN_OVER", "WHERE" in over_part)
print("HAS_USD_FILTER", "waerk" in out and "USD" in out)
print("PART", build_partitioned_topn_sql("Show the top 5 customers in each country by billed sales.", ["VBRK", "KNA1"])[:180])
print("REL", build_relative_document_list_sql("Show invoices from last month.", ["VBRK"])[:200])
print("DATE", required_semantics("Show invoices from last month.").get("date_filter"))
print("GROWTH", required_semantics("Which country had the highest sales growth?").get("clarification"))
