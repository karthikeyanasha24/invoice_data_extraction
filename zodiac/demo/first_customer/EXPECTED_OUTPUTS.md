# Expected Outputs — Demo / Staging

## Health

| Check | Expected |
|-------|----------|
| `GET /health` | `status: healthy` |
| `GET /health/ready` | `status: ready`, `missing_tables: []` |
| Ready with missing migrations | HTTP **503**, lists missing tables |

## Onboarding

| Check | Expected |
|-------|----------|
| Incomplete workspace | `ready: false`, `missing` includes e.g. `erp_configured` |
| Fully configured pilot | `ready: true`, `missing: []` |

## Invoice / government / ERP (staging)

| Stage | Expected |
|-------|----------|
| Upload / ingest | Invoice accepted; customer_id scoped |
| Adapter submit (sandbox) | Success or structured retryable error — not silent drop |
| Confirmation | Status visible in UI or monitoring timeline |
| ERP update | Success **or** skipped when `erp_fulfilled_in_submit` + `erp_update_mode=auto` |
| Monitoring | Timeline row with stages; correlation_id present |
| AI Ops | Natural-language ops answer; no invoice table writes |

## Failure expectations

| Fault | Expected |
|-------|----------|
| Invalid ERP credentials | Auth failure; non-retryable or limited retries; monitoring event |
| Government unavailable | Retry per government policy; then failed stage; alert |
| Missing `env:` secret | Structured resolve error; request not sent with raw `env:VAR` as token |
| `pipeline_enabled=false` | Pipeline API rejects / skips orchestrator for workspace |
| Adapter `enabled=false` | Onboarding not ready; submit path does not use that country |

## Dashboards to show

1. Workspace Overview — readiness banner  
2. Workspace Monitoring — timeline  
3. Workspace AI Ops — “failures today”  
4. API `/docs` — health + workspace onboarding-status (optional tech appendix)
