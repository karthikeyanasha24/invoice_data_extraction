# AI SQL routing (Zodiac)

**Next priority for billing analytics:** enforce calendar year on **FKDAT** and currency clarity (**WAERK**) for year-scoped revenue/ranking questions; explicit-table routing remains the foundation for named tables.

## Precedence order

1. **Explicit table names** in the user message (quoted identifiers, `FROM`/`JOIN`, `schema_ai_config.json` `skip_tables`, `ai_*` names, and uppercase SAP-style tokens) are resolved first.
2. **App tables** (`skip_tables`, e.g. `ai_analysis_memory`) are queried on the **app** `Session` (`db`), not the SAP read replica.
3. **Unknown names** → short clarification (no substitution with another table).
4. **SAP-only explicit** → schema-driven LLM with `forced_tables` (no deterministic templates, no intent fallbacks, no entity-table injection that would add e.g. LFA1).
5. **Explicit SAP only, failure** → error response; **adaptive** and **standard** `sap_sql_agent` are **not** used (avoids wrong-table substitution).
6. Otherwise: deterministic billing shortcuts (when allowed), `ai_query_memory` reuse (must reference explicit tables if named), procurement-from-list, then schema-driven → adaptive → standard → PO fallback.

## `sql_path_reason`

The API payload includes **`sql_path_reason`** (and **`performance.sql_path_reason`**) for support, e.g.:

- `explicit_app_table`, `explicit_table_unknown`, `explicit_table_mixed_catalog`, `explicit_sap_forced_failed`
- `deterministic_pre`, `memory_hit`, `llm_primary_schema_driven`, `llm_primary_adaptive`, `llm_primary_standard`, `purchase_order_fallback`

## Year + billing (FKDAT)

When the question includes a **calendar year** and **ranking / revenue / “by customer”** intent over **VBRK/VBRP**, SQL must filter billing date via **FKDAT** (e.g. `SUBSTRING(TRIM(r.fkdat),1,4) = 'YYYY'`). The precision validator **rejects** SQL that omits this. **`sanitize_generated_sap_sql(sql, question)`** also **auto-injects** a `WHERE SUBSTRING(TRIM(alias.fkdat),1,4) = 'YYYY'` when it can infer a **VBRK** alias (best-effort before execute). **WAERK**: sums of `netwr` without currency in the query get a **warning**; charts and analytics copy append a **mixed-currency** note when sample rows show multiple `waerk`/`waers` values.

## Mixed app + SAP

If the user names both an app table and a SAP table in one question, the assistant returns a short **split template** (run one catalog per message); it does not run a hybrid query.
