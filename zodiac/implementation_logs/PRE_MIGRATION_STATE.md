# Pre-Migration State

**Captured:** 2026-08-03 (local DEV environment repair)  
**Purpose:** Snapshot before applying enterprise Phase 2 / 6 / 8 migrations.  
**No schema changes made at capture time.**

---

## DATABASE_URL (credentials masked)

| Field | Value |
|-------|--------|
| Source | `zodiac/zodiac-api/.env` |
| Redacted URL | `postgresql://neondb_owner:***@ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech/neondb?sslmode=require` |
| Host | `ep-long-dust-adsylj0t-pooler.c-2.us-east-1.aws.neon.tech` |
| Database name | `neondb` |
| DB user | `neondb_owner` |
| SSL | `sslmode=require` |

## Live connection

| Field | Value |
|-------|--------|
| `current_database()` | `neondb` |
| `current_schema()` | `public` |
| `current_user` | `neondb_owner` |
| Public table count | **121** |

## Required enterprise tables (before)

| Table | Status |
|-------|--------|
| `workspace_settings` | MISSING |
| `workspace_erp_connections` | MISSING |
| `workspace_adapter_config` | MISSING |
| `erp_push_outbox` | MISSING |
| `pipeline_timelines` | MISSING |
| `pipeline_events` | MISSING |
| `pipeline_metrics` | MISSING |
| `alert_history` | MISSING |

## API health (before)

| Endpoint | Result |
|----------|--------|
| `GET /health` | **200** `{"status":"healthy","service":"zodiac-api","version":"1.0.0"}` (confirmed in a follow-up probe before migrations; an earlier combined probe timed out once due to Neon latency) |
| `GET /health/ready` | **503** `status=not_ready` — all 8 enterprise tables listed in `missing_tables` |

### `/health/ready` body (verbatim)

```json
{
  "status": "not_ready",
  "service": "zodiac-api",
  "missing_tables": [
    "workspace_settings",
    "workspace_erp_connections",
    "workspace_adapter_config",
    "erp_push_outbox",
    "pipeline_timelines",
    "pipeline_events",
    "pipeline_metrics",
    "alert_history"
  ],
  "checked_tables": [
    "workspace_settings",
    "workspace_erp_connections",
    "workspace_adapter_config",
    "erp_push_outbox",
    "pipeline_timelines",
    "pipeline_events",
    "pipeline_metrics",
    "alert_history"
  ]
}
```

## Notes

- Legacy Zodiac schema is present (121 public tables); this is not an empty database.
- Enterprise migrations have not been applied yet at this snapshot.
- Next step: run official `python ../scripts/apply_enterprise_migrations.py`.
