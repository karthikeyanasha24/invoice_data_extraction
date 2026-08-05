# Migration Guide

**Policy:** Expand-only. Never alter existing production invoice/SAT tables for BridgeEDI phases.

Location: `zodiac-api/app/migrations/`  
Index: `zodiac-api/app/migrations/README.md`

---

## 1. Required scripts (in order)

| Order | File | Purpose |
|-------|------|---------|
| 1 | `phase2_workspace_tables.sql` | Workspace settings, ERP connections, adapter config |
| 2 | `phase6_erp_outbox.sql` | ERP push idempotency outbox |
| 3 | `phase8_monitoring_tables.sql` | Timelines, events, metrics, alert_history |

All use `IF NOT EXISTS` where possible — safe to re-run.

---

## 2. How to apply

```bash
# Example with psql
psql "$DATABASE_URL" -f app/migrations/phase2_workspace_tables.sql
psql "$DATABASE_URL" -f app/migrations/phase6_erp_outbox.sql
psql "$DATABASE_URL" -f app/migrations/phase8_monitoring_tables.sql
```

Record version + timestamp in your change ticket.

**Note:** Application startup does **not** auto-run these SQL files. `Base.metadata.create_all` may create missing ORM tables in some bootstrap scripts, but production must apply the SQL migrations explicitly for indexes/constraints parity.

---

## 3. Verification queries

```sql
SELECT to_regclass('public.workspace_settings');
SELECT to_regclass('public.erp_push_outbox');
SELECT to_regclass('public.pipeline_timelines');
SELECT to_regclass('public.pipeline_events');
SELECT to_regclass('public.pipeline_metrics');
SELECT to_regclass('public.alert_history');
```

---

## 4. Rollback stance

Do **not** drop phase tables to “undo” a release. Disable features with flags instead.  
If a table must be removed later, schedule a dedicated, reviewed deprecation migration (out of Phase 10 scope).

---

## 5. ORM registration

`app/database.py` `init_models()` imports workspace, ERP outbox, and monitoring models so metadata stays consistent with migrations.
