# Environment Ready for QA

**Updated:** 2026-08-03 (post full manual QA)  
**Status:** **READY** for continued Workspace configuration QA / single-customer pilot with minor fixes

---

## Environment

| Item | Value |
|------|--------|
| Deploy | DEV |
| API | `http://127.0.0.1:8000` |
| Frontend | `http://localhost:3000` |
| Database | Neon `neondb` (see PRE_MIGRATION_STATE / diagnostic) |

## Database / Tables

All 8 enterprise tables **EXISTS**. Public table count was 129 after migrations.

## Health

| Endpoint | Result |
|----------|--------|
| `/health` | healthy |
| `/health/ready` | ready (`missing_tables: []`) |

## Migrations

| Applied | Failed | Pending |
|---------|--------|---------|
| phase2, phase6, phase8 | none | none |

## Workspace

| Check | Status |
|-------|--------|
| List / Overview / activity / onboarding APIs | **200** for admin QA user |
| Monitoring / AI Ops APIs | **200** (empty data OK) |
| Pilot `DE875243162` settings row | Still **missing** (`has_settings=false`) — enable via UI |

## User

| Account | Permissions |
|---------|-------------|
| `ashakarthikeyan24` (id 11) | Temporary `is_admin=true` — **rollback after QA** |

## Manual QA

| Item | Status |
|------|--------|
| Ready | Yes — see `MANUAL_QA_FINAL_REPORT.md` |
| Blocked | None for shell APIs; config incomplete for full onboarding Ready |
| Remaining | Enable workspace settings; fix minor UX/format bugs; rollback admin |

**Environment is now ready for full Workspace manual testing** (configuration steps next; live pipeline/gov/ERP integrations still out of scope until intentionally enabled).
