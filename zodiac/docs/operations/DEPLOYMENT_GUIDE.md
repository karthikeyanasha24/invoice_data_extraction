# Deployment Guide

**Scope:** BridgeEDI (`zodiac-api`, `zodiac-front`)  
**Related:** [CONFIGURATION_GUIDE.md](CONFIGURATION_GUIDE.md) · [MIGRATION_GUIDE.md](MIGRATION_GUIDE.md) · [ROLLBACK_GUIDE.md](ROLLBACK_GUIDE.md)

---

## 1. Components

| Component | Runtime | Entry |
|-----------|---------|-------|
| API | Python 3.11+ / FastAPI / uvicorn | `app.server:app` (`Dockerfile` or Vercel `index.py`) |
| Front | Next.js | `zodiac-front` |
| DB | PostgreSQL | `DATABASE_URL` |

There is **no Celery**. Background work today is in-process / asyncio. Multi-instance deployments must not assume in-memory SAT `status_tracker` is shared.

---

## 2. Pre-deploy checklist

1. Apply SQL migrations (Phase 2, 6, 8) — see Migration Guide.  
2. Set production secrets (`SECRET_KEY`, `API_HASH_KEY`, `DATABASE_URL`).  
3. Set `CORS_ORIGINS` to exact frontend origins; `CORS_ALLOW_ALL=false`.  
4. Keep `ENABLE_PIPELINE_API=false` until pilot ready.  
5. `API_DEBUG=false`.  
6. Run enterprise unit suite from `zodiac-api`:

```bash
python -m unittest discover -s app/tests -p "test_*.py" -q
```

---

## 3. API deploy (container)

```bash
cd zodiac/zodiac-api
docker build -t bridgeedi-api:release .
docker run -p 8000:8000 --env-file .env.production bridgeedi-api:release
```

Health probes:

- `GET /` — liveness  
- `GET /api/v1/pipeline/health` — pipeline flag  
- `GET /api/v1/monitoring/health` — monitoring flag  
- `GET /api/v1/ai/health` — AI Ops flag  

---

## 4. API deploy (Vercel / serverless)

- Entry: `zodiac-api/index.py` + `vercel.json`  
- Ensure `DATABASE_URL` and pool settings suit serverless (`DATABASE_POOL_SIZE` small).  
- Prefer external object storage when `DEPLOY_ENV=PROD`.

---

## 5. Frontend deploy

```bash
cd zodiac/zodiac-front
npm ci
npm run build
# deploy .next / hosting platform artifact
```

Point public API base URL at the production API. Confirm CORS allows the front origin.

---

## 6. Post-deploy verification

| Check | Expected |
|-------|----------|
| Login | JWT issued |
| Workspace list | Only assigned / admin |
| SAT health path (Mexico pilot) | Existing flow unchanged |
| Monitoring summary (pilot ws) | 200 when enabled |
| Pipeline `/run` | 404 if flag off |
| AI Ops summary | 200; scoped to workspace |

---

## 7. Pilot enablement sequence

1. Deploy with pipeline API **off**.  
2. Create/verify workspace settings (`monitoring_enabled`, `ai_scoped`).  
3. Configure ERP/adapter **secret refs** (not plaintext).  
4. Enable `ENABLE_PIPELINE_API=true` in staging → dry-run.  
5. Set workspace `pipeline_enabled=true` for pilot only.  
6. Promote same flags to production after sign-off.
