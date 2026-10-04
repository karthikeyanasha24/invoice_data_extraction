# SQL migrations (expand-only)

| File | Phase |
|------|-------|
| `phase2_workspace_tables.sql` | Customer Workspace |
| `phase6_erp_outbox.sql` | ERP push idempotency outbox |
| `phase8_monitoring_tables.sql` | Pipeline monitoring / alerts |

Run manually against PostgreSQL. Scripts use `IF NOT EXISTS` where possible.

Helper: `python zodiac/scripts/apply_enterprise_migrations.py` (requires `DATABASE_URL`).  
Optional API startup: `AUTO_APPLY_ENTERPRISE_SCHEMA=true` runs SQLAlchemy `create_all` (dev/staging convenience).

Ops procedure: [`../../docs/operations/MIGRATION_GUIDE.md`](../../docs/operations/MIGRATION_GUIDE.md)  
Production gate: [`../../PRODUCTION_READINESS_CHECKLIST.md`](../../PRODUCTION_READINESS_CHECKLIST.md)
