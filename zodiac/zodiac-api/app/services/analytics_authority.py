"""Runtime authority policy for the AI Analyst page.

Classification of existing modules (do not treat catalog/compilers as answers):

  sql_catalog.json                         TEST FIXTURE / evaluation only
  four_stage_db_pipeline (P1–P6)           GENERIC INFRASTRUCTURE (authority)
  _deterministic_sql_if_known              LEGACY — must not emit SQL
  sales_order_analysis                     LEGACY — not a runtime answer path
  adaptive_structured_sql.build_*          GENERIC INFRASTRUCTURE (render helpers)
  adaptive_query KEYWORD → TABLES          LEGACY prompt text — not table authority
  operational_query_resolver SAT/EDI       OPERATIONAL FAST PATH (bounded domain)
  plan_satisfaction                        GENERIC INFRASTRUCTURE (hard gate)
  investigation_budget                     GENERIC INFRASTRUCTURE
"""
from __future__ import annotations

CATALOG_IS_RUNTIME_AUTHORITY = False
INTENT_FAST_PATH_IS_RUNTIME_AUTHORITY = False
SALES_ORDER_COMPILER_IS_RUNTIME_AUTHORITY = False
DETERMINISTIC_QUESTION_SQL_IS_RUNTIME_AUTHORITY = False
KEYWORD_TABLE_MAP_IS_AUTHORITY = False
FOUR_STAGE_IS_SAP_ANALYTICS_AUTHORITY = True
OPERATIONAL_SAT_EDI_ALLOWED = True
INVESTIGATION_HARD_LIMIT_SECONDS = 120
