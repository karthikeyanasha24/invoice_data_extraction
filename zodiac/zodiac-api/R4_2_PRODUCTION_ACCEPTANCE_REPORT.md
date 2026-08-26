# R4-2 Production Acceptance Report

## Verdict

```text
R4-2 NOT PRODUCTION COMPLETE
```

**Blocker:** Local implementation and unit/golden tests are green, but this machine cannot deploy to `zodiac-back` (no Vercel project link). Production still runs the prior baseline until Andy deploys the pushed commit, then live R3 / R4-1 / R4-2 + Full Chat acceptance must pass.

---

## Implementation

### Architecture changes

- Added governed growth layer `product_growth.py` (absolute / % / period status / mode / metric / direction / period grain).
- Extended deep planner with intent `product_growth_decline` after R4-1 time grain and R3 `margin_decline_drivers`.
- YoY SQL: yearly CTE + `FULL OUTER JOIN` prev/curr years; MoM/QoQ: period LAG filtered to latest period.
- Companion customer-mix query for observed drivers.
- Follow-up resolver: growth/decline/why/metric preserve on `product_growth_decline`.
- Interpret: observed-contributor language + approximate volume/price decomposition disclaimer.
- Empty-period allowlist includes `product_growth_decline`.

### Files changed

| File | Change |
|------|--------|
| `app/services/product_growth.py` | **NEW** canonical growth helpers |
| `app/services/analytical_deep_dive.py` | Intent, SQL, interpret, empty period, charts |
| `app/services/analytical_followup_resolver.py` | Growth/decline follow-ups + ASP phrases |
| `app/services/business_semantic_layer.py` | Drilldowns for quantity / ASP |
| `tests/test_r4_2_product_growth_decline.py` | **NEW** suite |
| `tests/test_r3_golden_benchmark.py` | R4-2 golden + routing assertions |
| `scripts/r4_2_live_acceptance.py` | **NEW** live harness |
| `scripts/r4_2_independent_sql.py` | **NEW** independent SQL harness |
| `docs/architecture/R4_2_PRODUCT_GROWTH.md` | Architecture note |

### Semantic / planner / SQL / context / UI

- Semantic concepts: GROWTH, DECLINE, PERIOD_COMPARISON, PRODUCT_CHANGE, DRIVER_ANALYSIS (via filters + comparisons, not phrase patches).
- Context fields: `growth_metric`, `growth_direction`, `change_mode`, `period_grain`.
- UI: no dedicated Frontend change required; table/chart consume `revenue_change_abs` and existing product labels. Full Chat live proof pending deploy.

---

## Metrics

| Definition | Formula |
|------------|---------|
| Absolute change | `current − previous` |
| Percentage growth | `((current − previous) / previous) * 100` when `previous ≠ 0`, else `NULL` |
| Margin change | `margin_curr − margin_prev` (percentage points) |
| NEW | prior ≈ 0 and current ≠ 0 → `NEW_NO_PRIOR_BASE` |
| FULL DECLINE | current ≈ 0 and prior ≠ 0 → `FULL_DECLINE_NO_CURRENT` |

Supported metrics: Revenue, COGS, Gross Profit, Margin %, Quantity, ASP, Invoice Count.

---

## Growth analysis

Supported: revenue / GP / COGS / quantity / ASP / margin improvement & decline; absolute vs percentage ranking; YoY / MoM / QoQ.

---

## Driver analysis

Observed contributors: ASP Δ, quantity Δ, COGS Δ, margin pp, customer mix sample. Language uses **observed contributor / associated change**, not causal certainty. Approximate volume + price decomposition labeled illustrative.

---

## Accuracy

Independent SQL script: `scripts/r4_2_independent_sql.py` (run after deploy against same SAP DB). **Not yet executed against live R4-2 code** (deploy pending).

---

## Testing (local)

| Suite | Result |
|-------|--------|
| `tests/test_r4_2_product_growth_decline.py` | PASS |
| `tests/test_r4_1_month_quarter_trends.py` | PASS (R4-1 regression) |
| `tests/test_r3_golden_benchmark.py` | PASS (incl. R4-2 routing) |
| `tests/test_andy_deep_dive_cases.py` + R3 deep / follow-up | PASS |

Expected production regression after deploy:

```text
R3:   23 PASS / 2 DATA GAP / 0 FAIL
R4-1: 47 PASS / 2 DATA GAP / 0 FAIL
R4-2: 0 unexpected FAIL
```

Live R3/R4-1/R4-2 and Full Chat: **pending Andy deploy**.

---

## Performance

Local harnesses do not replace production latency. After deploy run:

```bash
python scripts/r4_2_live_acceptance.py
```

and record P50 / P95 / P99 / Max from `r4_2_live_acceptance.json`.

---

## Production

| Item | Value |
|------|-------|
| Project | `zodiac-back` only (never `zodiac-api-nu`) |
| Branch | `phase12-first-customer-ready` |
| Deploy | **Blocked on Karth machine** — Andy must verify `.vercel/project.json` → `zodiac-back` then `npx vercel --prod` |
| Behavioral proof | `Which products grew the most?` → intent `product_growth_decline` + SQL with `revenue_change_abs` / `period_status` |

---

## Full Chat

Pending deploy. Target: https://www.bridgeedi.com/dashboard/ai

---

## Remaining DATA GAPs

- Logistics cost / freight cost amounts
- Product-level net profit / OPEX / EBITDA
- Certified discount / tax / freight
- Budget / target
- True inventory aging

---

## Acceptance matrix (local code)

| Capability | Pipeline | SQL | Data | Accuracy | Context | UI | Latency | Status |
|------------|----------|-----|------|----------|---------|----|---------|--------|
| Product revenue growth | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| Product revenue decline | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| GP growth / decline | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| Quantity / ASP growth | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| Margin improve / decline | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| Absolute vs % | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| YoY / MoM / QoQ | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| Drivers / customer mix | local OK | OK | — | pending live | OK | pending | pending | LOCAL |
| DATA GAP recovery | local OK | — | gap | — | OK | pending | pending | LOCAL |
| R3 / R4-1 regression | local OK | — | — | — | — | — | — | LOCAL |
| Full Chat / Production | — | — | — | — | — | — | — | **BLOCKED** |

---

## Next step for Andy

1. Pull `phase12-first-customer-ready`.
2. Confirm Vercel project name is **`zodiac-back`**.
3. `npx vercel --prod`.
4. `python scripts/r3_post_deploy_live_acceptance.py`
5. `python scripts/r4_1_live_acceptance.py`
6. `python scripts/r4_2_live_acceptance.py`
7. `python scripts/r4_2_independent_sql.py`
8. Full Chat manual chain.
9. Only then mark **R4-2 PRODUCTION COMPLETE**.
