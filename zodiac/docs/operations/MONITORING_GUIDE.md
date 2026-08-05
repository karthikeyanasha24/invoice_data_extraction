# Monitoring Guide

**Sources of truth:** Phase 8 monitoring stores + Phase 9 AI Ops (read-only consumer).

---

## 1. What to watch

| Signal | Where |
|--------|-------|
| Transaction status (RUNNING/COMPLETED/FAILED/RETRYING) | `pipeline_timelines` / Monitoring UI |
| Stage timeline | `pipeline_events` |
| Latency | `pipeline_metrics` (`pipeline.latency_ms`) + timeline `latency_ms` |
| Alerts | `alert_history` (log channel today) |
| Workspace dashboard | `GET /api/v1/monitoring/workspaces/{id}/summary` |
| Ops narrative | `GET /api/v1/ai/workspace/{id}/summary` |

AI Ops **must not** be used as a substitute for invoice audit tables.

---

## 2. Operator workflows

### Find a failed invoice run

1. Workspace → Monitoring → Latest transactions (FAILED).  
2. Copy `correlation_id`.  
3. `GET /api/v1/monitoring/workspaces/{id}/timelines/{correlation_id}`.  
4. Note `failed_stage`, `failure_reason`, government/ERP refs.

### Daily health (pilot)

Ask AI Ops: “What failed today?” / “Retry statistics?” / “Average processing time?”  
Or open AI Ops tab for recommendations (advisory only).

### Government / ERP symptoms

| Alert type | Meaning |
|------------|---------|
| `government_unavailable` | Gov connector failures |
| `erp_unavailable` | ERP path failures |
| `repeated_retry` | Elevated retries |
| `high_latency` | Above threshold (~60s default evaluation) |

Email/Slack/webhook channels are **stubs** — rely on log drains / paging until integrations ship.

---

## 3. Log queries

Search application logs for:

```text
correlation_id=<uuid>
[monitoring]
[audit]
[ai-ops-audit]
[alert:
▶ pipeline start
■ pipeline
```

---

## 4. SLOs (recommended starting points)

| Metric | Pilot target |
|--------|--------------|
| Pipeline dry-run success | ≥ 99% |
| End-to-end (excl. external) | Baseline in staging, then set |
| Monitoring persist failure rate | Soft-fail; alert if sustained warnings |
| Workspace isolation incidents | **Zero** |

Tune after two weeks of pilot data.

---

## 5. Feature flags

- Disable Monitoring API: `ENABLE_MONITORING_API=false`  
- Disable workspace monitoring stage: `monitoring_enabled=false`  
- Pipeline still completes; observability reduced.
