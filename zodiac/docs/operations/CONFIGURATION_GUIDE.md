# Configuration Guide

---

## 1. Core runtime

| Variable | Required | Production guidance |
|----------|----------|---------------------|
| `DATABASE_URL` | Yes | Postgres DSN; prefer SSL |
| `SECRET_KEY` | Yes | Strong random; never default |
| `API_HASH_KEY` | Yes | Strong random for API keys |
| `ALGORITHM` | No | `HS256` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | Tighten from long defaults |
| `API_HOST` / `API_PORT` | No | Bind as appropriate |
| `API_DEBUG` | No | **`false` in prod** |
| `DATABASE_POOL_SIZE` | No | Match worker concurrency |
| `DATABASE_MAX_OVERFLOW` | No | Cap under serverless |

---

## 2. CORS

| Variable | Production |
|----------|------------|
| `CORS_ORIGINS` | Comma-separated exact origins (frontends) |
| `CORS_ALLOW_ALL` | **`false`** |

Phase 10: middleware honors `CORS_ORIGINS`. `CORS_ALLOW_ALL=true` disables credentialed CORS and allows `*` — local debug only.

---

## 3. BridgeEDI feature flags

| Variable | Default | Meaning |
|----------|---------|---------|
| `ENABLE_PIPELINE_API` | `false` | Exposes `/api/v1/pipeline/*` |
| `ENABLE_MONITORING_API` | `true` | Exposes `/api/v1/monitoring/*` |
| `ENABLE_AI_OPS_API` | `true` | Exposes `/api/v1/ai/*` |
| `DEPLOY_ENV` | `DEV` | `STAGING`/`PRODUCTION` tighten startup config checks |
| `AUTO_APPLY_ENTERPRISE_SCHEMA` | `false` | If true, SQLAlchemy `create_all` on startup (prefer SQL migrations in prod) |
| `ALERT_WEBHOOK_URL` | unset | Optional JSON webhook for monitoring alerts |

See also: [`../../zodiac-api/.env.example`](../../zodiac-api/.env.example)

### Workspace settings (DB)

| Field | Default | Meaning |
|-------|---------|---------|
| `pipeline_enabled` | `false` | Orchestrator gate per customer |
| `monitoring_enabled` | `true` | Skip monitoring stage when false |
| `ai_scoped` | `true` | AI Ops allowed for workspace |

Pipeline requires **both** deployment flag and workspace `pipeline_enabled`.

---

## 4. Secrets policy

Workspace ERP / adapter credentials must be **refs**, not plaintext:

- Allowed prefixes: `vault:`, `env:`, `secret:`, `arn:`, `kms:`, `ref:`  
- `endpoint_url_ref` may also be `https://...`

### Runtime resolution (PR2)

Central module: `app/core/secrets` (shared by ERP + Government connectors).

| Ref | Behaviour |
|-----|-----------|
| Literal (`password123`) | Returned as-is |
| `env:VAR` | Reads `os.environ[VAR]`; structured error if missing |
| `vault:path/to/secret` | `BRIDGEEDI_VAULT_JSON`, or `BRIDGEEDI_VAULT_*` bridge, or Vault HTTP (`VAULT_ADDR` + `VAULT_TOKEN`) |
| `secret:` / `arn:` / `kms:` / `ref:` | `PROVIDER_NOT_CONFIGURED` until wired |
| Unknown `foo:…` | `UNKNOWN_PROVIDER` — no silent fallback |

| Variable | Purpose |
|----------|---------|
| `SECRET_RESOLVER=literal` | Legacy: prefixed refs stay unresolved |
| `BRIDGEEDI_VAULT_JSON` | JSON map path → value (tests/staging) |
| `VAULT_ADDR` / `VAULT_TOKEN` | Live Vault KV HTTP |

Never log resolved secret values.

---

## 5. Frontend

Configure the public API base URL used by `zodiac-front` to the production API. Ensure that origin appears in `CORS_ORIGINS`.
