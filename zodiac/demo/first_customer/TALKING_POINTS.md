# Talking Points — First Customer Pilot

## Positioning

- BridgeEDI is a **multi-customer workspace platform** on top of proven Mexico CFDI/SAT processing.  
- First customer uses the **same architecture** already built — configuration, not a rewrite.  
- Escape hatch: turn off the new pipeline; existing SAT/V1/V2 keep running.

## Value for the customer

1. **Exclusive workspace** — settings, ERP, adapters, monitoring, AI Ops scoped to them.  
2. **Secret hygiene** — vault/env references; no passwords in config tables.  
3. **Controlled ERP updates** — avoid double-write with `erp_update_mode`.  
4. **Operational visibility** — stage timelines and alerts per invoice correlation.  
5. **AI for operations** — answers from monitoring aggregates, not invoice mutation.

## Architecture (existing diagrams only)

Point to `docs/architecture/01_SYSTEM_ARCHITECTURE.md` and sequence diagrams.  
Flow: Workspace → Pipeline (opt-in) → Country Adapter → Government → Confirmation → ERP → Monitoring → AI Ops.

## What we are not changing in this pilot

- No SAT redesign  
- No V1/V2 rewrite  
- No new framework layers  
- No automated remediations from AI

## Risk honesty (builds trust)

- Pipeline API is **opt-in** and starts off in production.  
- App-level circuit breakers / DLQ are limited; edge rate limit + runbooks cover pilot scale.  
- Government and ERP must be validated in **their** sandbox before production URLs.

## Ask

Conditional production pilot: one workspace, sandbox→prod cutover checklist, flag-based rollback.
