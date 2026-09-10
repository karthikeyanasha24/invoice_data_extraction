from app.services.semantic_requirements import required_semantics
from app.services.plan_satisfaction import sql_satisfies_analytical_intent, result_matches_analytical_intent
q = "Which country had the highest sales growth and which customers contributed most to that growth?"
req = required_semantics(q)
print("period", req.get("period_compare"))
print("growth", req.get("growth"))
sql = 'SELECT "KNA1"."land1" AS "country", SUM(VBRK.netwr) AS "total_sales" FROM "VBRK" JOIN "KNA1" ON 1=1 GROUP BY 1'
print("sql_ok", sql_satisfies_analytical_intent(sql, q))
print("warn", result_matches_analytical_intent([{"country":"US","customer_id":"1","customer_name":"A","total_sales":9}], q, sql=sql))
