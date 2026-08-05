# First Customer Deployment Checklist

**Platform:** BridgeEDI / Zodiac  
**Audience:** DevOps, Engineering Lead, Customer Success  
**Rule:** Architecture is frozen. Use existing flags, migrations, and ops guides only.  
**Related:** [`PRODUCTION_READINESS_CHECKLIST.md`](PRODUCTION_READINESS_CHECKLIST.md) · [`docs/operations/`](docs/operations/) · [`CUSTOMER_ONBOARDING_IMPLEMENTATION.md`](CUSTOMER_ONBOARDING_IMPLEMENTATION.md)

Legend: `[ ]` open · `[x]` done · **P0** blocker · **P1** strongly recommended

---

## 1. Infrastructure

| ID | Item | Pri | Done |
|----|------|-----|------|
| I1 | API host/runtime provisioned (container, VM, or platform) | P0 | [ ] |
| I2 | Frontend deployed; origin listed in `CORS_ORIGINS` | P0 | [ ] |
| I3 | PostgreSQL with SSL + PITR/backups enabled | P0 | [ ] |
| I4 | Log drain / aggregation searchable by `correlation_id` | P1 | [ ] |
| I5 | Edge TLS + (recommended) WAF / rate limit | P1 | [ ] |
| I6 | Staging environment distinct from production | P0 | [ ] |
| I7 | On-call / escalation path named | P0 | [ ] |

---

## 2. Database

| ID | Item | Pri | Done |
|----|------|-----|------|
| D1 | `DATABASE_URL` points to target DB (SSL) | P0 | [ ] |
| D2 | `phase2_workspace_tables.sql` applied | P0 | [ ] |
| D3 | `phase6_erp_outbox.sql` applied | P0 | [ ] |
| D4 | `phase8_monitoring_tables.sql` applied | P0 | [ ] |
| D5 | `GET /health/ready` returns `status=ready` (no missing tables) | P0 | [ ] |
| D6 | Pool size matches worker concurrency | P1 | [ ] |
| D7 | Backup restore dry-run recorded | P1 | [ ] |

Procedure: [`docs/operations/MIGRATION_GUIDE.md`](docs/operations/MIGRATION_GUIDE.md)

---

## 3. Environment variables

| ID | Item | Pri | Done |
|----|------|-----|------|
| E1 | `SECRET_KEY` strong random (not placeholder) | P0 | [ ] |
| E2 | `API_HASH_KEY` set | P0 | [ ] |
| E3 | `API_DEBUG=false` in staging/prod | P0 | [ ] |
| E4 | `CORS_ALLOW_ALL=false`; `CORS_ORIGINS` exact | P0 | [ ] |
| E5 | `ENABLE_PIPELINE_API=false` until pilot dry-run passes | P0 | [ ] |
| E6 | `ENABLE_MONITORING_API` / `ENABLE_AI_OPS_API` deliberate | P1 | [ ] |
| E7 | `SECRET_RESOLVER` = `default` (or vault wired); not `literal` in prod | P0 | [ ] |
| E8 | AI keys present only if AI Ops / insights used | P1 | [ ] |

Reference: [`docs/operations/CONFIGURATION_GUIDE.md`](docs/operations/CONFIGURATION_GUIDE.md)

---

## 4. Secrets

| ID | Item | Pri | Done |
|----|------|-----|------|
| S1 | ERP credentials stored as `env:` / `vault:` refs only | P0 | [ ] |
| S2 | Government auth stored as secret refs only | P0 | [ ] |
| S3 | Runtime resolves `env:` vars on API host | P0 | [ ] |
| S4 | Vault path mapped (`BRIDGEEDI_VAULT_JSON` or `VAULT_ADDR`/`VAULT_TOKEN`) if using `vault:` | P0 | [ ] |
| S5 | Resolved secrets never logged | P0 | [ ] |
| S6 | Secret rotation owner + procedure documented | P1 | [ ] |

---

## 5. Certificates (Mexico / CFDI pilot)

| ID | Item | Pri | Done |
|----|------|-----|------|
| C1 | Customer FIEL/CSD (or PAC path) handled via existing certificate flows | P0 | [ ] |
| C2 | Private keys never in workspace JSON / never logged | P0 | [ ] |
| C3 | Receiver RFC mapping for customer complete | P0 | [ ] |
| C4 | Sandbox vs production SAT endpoints confirmed with customer | P0 | [ ] |

---

## 6. Workspace

| ID | Item | Pri | Done |
|----|------|-----|------|
| W1 | Customer record created (`/customers`) | P0 | [ ] |
| W2 | Workspace settings enabled | P0 | [ ] |
| W3 | Admin user can open `/workspace/{id}` | P0 | [ ] |
| W4 | Customer user assigned only to this workspace | P0 | [ ] |
| W5 | `GET .../onboarding-status` → `ready=true` | P0 | [ ] |
| W6 | `flags.erp_update_mode=auto` (unless customer requires otherwise) | P0 | [ ] |
| W7 | `pipeline_enabled=false` until staging invoice dry-run | P0 | [ ] |

---

## 7. ERP

| ID | Item | Pri | Done |
|----|------|-----|------|
| R1 | Active ERP connection: `base_url` + `auth_type` | P0 | [ ] |
| R2 | Secret refs resolve in staging | P0 | [ ] |
| R3 | Staging connectivity test (auth + sample confirmation) | P0 | [ ] |
| R4 | Callback URL registered if customer requires webhook | P1 | [ ] |
| R5 | Outbox uniqueness verified after first push | P1 | [ ] |
| R6 | Dual-write policy agreed (`erp_update_mode`) | P0 | [ ] |

---

## 8. Government

| ID | Item | Pri | Done |
|----|------|-----|------|
| G1 | Adapter enabled (`mx_cfdi` for Mexico pilot) | P0 | [ ] |
| G2 | `endpoint_url_ref` points to **sandbox** first | P0 | [ ] |
| G3 | Auth secret ref resolves | P0 | [ ] |
| G4 | Sandbox submit success recorded (correlation_id) | P0 | [ ] |
| G5 | Idempotency / duplicate submit behavior accepted | P1 | [ ] |
| G6 | Production government URL cutover plan signed | P0 | [ ] |

---

## 9. Monitoring

| ID | Item | Pri | Done |
|----|------|-----|------|
| M1 | `monitoring_enabled=true` on workspace | P0 | [ ] |
| M2 | Monitoring UI tab loads for pilot | P0 | [ ] |
| M3 | Timeline/events visible after sample run | P0 | [ ] |
| M4 | Alert subscription / on-call wired (ops) | P1 | [ ] |
| M5 | Runbooks RB-1..RB-3 bookmarked | P0 | [ ] |

---

## 10. AI Ops

| ID | Item | Pri | Done |
|----|------|-----|------|
| A1 | `ai_scoped=true` | P0 | [ ] |
| A2 | AI Ops tab answers ops questions from monitoring only | P0 | [ ] |
| A3 | Confirmed: AI does **not** join invoice pipeline | P0 | [ ] |
| A4 | Cross-workspace AI blocked for customer users | P0 | [ ] |

---

## 11. Testing

| ID | Item | Pri | Done |
|----|------|-----|------|
| T1 | Unit suites green (onboarding, secrets, readiness, isolation) | P0 | [ ] |
| T2 | Staging journey recorded (see demo package / report §Staging) | P0 | [ ] |
| T3 | Failure tests recorded (creds, gov down, ERP down, secrets, flags) | P0 | [ ] |
| T4 | Mexico SAT/sandbox invoice smoke (existing path) | P0 | [ ] |
| T5 | Pipeline dry-run only after T4 + onboarding ready | P0 | [ ] |
| T6 | Rollback flag flip rehearsed (`ENABLE_PIPELINE_API=false`) | P0 | [ ] |

Demo / validation: [`demo/first_customer/`](demo/first_customer/)

---

## 12. Rollback

| ID | Item | Pri | Done |
|----|------|-----|------|
| X1 | Flag rollback path known ([`ROLLBACK_GUIDE.md`](docs/operations/ROLLBACK_GUIDE.md)) | P0 | [ ] |
| X2 | Previous API/frontend image tagged | P0 | [ ] |
| X3 | Migrations left in place (expand-only; no DROP) | P0 | [ ] |
| X4 | Customer comms template ready | P1 | [ ] |
| X5 | Escape hatch: SAT/V1/V2 remain if pipeline disabled | P0 | [ ] |

---

## Sign-off

| Role | Name | Date | Initials |
|------|------|------|----------|
| Engineering Lead | | | |
| DevOps | | | |
| Security | | | |
| Customer Success | | | |

**Pilot gate:** ☐ Ready for staging cutover · ☐ Ready for limited production · ☐ Hold
