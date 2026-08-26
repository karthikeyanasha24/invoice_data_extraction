# R4-2 Production Acceptance Report

**Date:** 2026-08-26  
**Branch:** `phase12-first-customer-ready`  
**Acceptance scope:** Post-deploy verification of `911afed` (or later containing R4-2) on `zodiac-back`  
**R4-3:** not started

---

## Final verdict

```text
R4-2 NOT PRODUCTION COMPLETE
```

### Exact blockers

1. **Absolute phrasing miss (Phase 4):** `Which products added the most revenue?` routes to `intent_sql_fast` (top revenue ranking), **not** `product_growth_decline` with absolute change. Closely related phrasing `Which products increased their revenue the most?` **does** pass R4-2.
2. **Empty single-year handling (Phase 16):** `Which products grew in 2099?` still runs a **2004 vs 2005** YoY growth query (planner pads to two default years) and returns 10 rows — not an honest “no data for 2099” response.

Full Chat UI smoke check for `Which products grew the most?` **passed** (table with 2004/2005, `revenue_change_*`, `NEW_NO_PRIOR_BASE` / `CONTINUING`, drill-downs). Remaining Full Chat multi-turn operator chain was not fully exercised in UI (API chains were).


---

## 1. Deployment

| Item | Value |
|------|--------|
| Project | `zodiac-back` only |
| URL | https://zodiac-back.vercel.app |
| Local HEAD (after ff) | `a5699e5` |
| Remote | `origin/phase12-first-customer-ready` @ `a5699e5` |
| `911afed` ancestry | **YES** — `git merge-base --is-ancestor 911afed origin/phase12-first-customer-ready` |
| R4-2 intro commit | `00d2759` Implement R4-2… |
| Product-group fix | `abce857` (live: follow-up → `product_group_breakdown`) |

### Behavioral proof (production is executing R4-2)

| Question | Pipeline | Intent | Evidence |
|----------|----------|--------|----------|
| Which products grew the most? | `deep_multidim` | `product_growth_decline` | `revenue_change_abs`, `period_status`, VBRP→VBRK |
| Which products grew the fastest? | `deep_multidim` | `product_growth_decline` | `change_mode=pct`, `ORDER BY revenue_change_pct` |
| Show their product groups. (after growth) | `deep_multidim` | `product_group_breakdown` | proves ≥ `abce857` live |

Vercel “deployment succeeded” alone was **not** used as proof.

---

## 2. R4-2 implementation (live behavior)

| Area | Status |
|------|--------|
| Growth / decline ranking | PASS |
| Revenue / GP / qty / ASP / margin variants | PASS (see probes) |
| Absolute vs % (`fastest` / `increased … most` / `%`) | PASS except **added the most revenue** |
| YoY / MoM / QoQ product change | PASS (LAG / yearly FULL OUTER JOIN) |
| Observed drivers + Why? | PASS (observed/contributor language) |
| Context follow-ups | PASS (customers, ASP, COGS, product groups, …) |
| DATA GAP recovery | PASS (logistics + net profit gaps; then revenue/COGS/customers) |
| Grain | PASS for billing growth (no EKPO/VBFA/KONV fan-out) |

---

## 3. Live probes — suite totals

### Canonical R4-2 harness (`scripts/r4_2_live_acceptance.py`)

```text
40 PASS / 1 DATA_GAP / 0 FAIL  (total 41)
P50 796ms | P95 1130ms | P99 1430ms | Max 1430ms
```

### Extra post-deploy probes (`scripts/r4_2_post_deploy_extra_probes.py`)

```text
36 PASS / 2 DATA_GAP / 2 FAIL  (total 40)
```

Fails (blockers above):
- `Which products added the most revenue?` → `intent_sql_fast`
- `Which products grew in 2099?` → false 2004/2005 growth result

### Abs vs % (mandatory)

| Question | Intent | Mode | Result |
|----------|--------|------|--------|
| grew the fastest | `product_growth_decline` | pct | PASS |
| added the most revenue | *(basic)* | — | **FAIL** |
| increased revenue by the highest percentage | `product_growth_decline` | pct | PASS |
| increased their revenue the most | `product_growth_decline` | absolute | PASS |

---

## 4. Independent SQL validation

`scripts/r4_2_independent_sql.py` against same SAP DB:

```text
total_mismatches: 0
cases: 6
```

Covered: top revenue growth, absolute increase, fastest %, decline, GP growth, margin improvement — AI vs independent ranking/values aligned.

---

## 5. Performance (R4-2 live harness)

| Metric | ms |
|--------|-----|
| P50 | 796 |
| P95 | 1130 |
| P99 | 1430 |
| Max | 1430 |

R3 harness also recorded approx P50 701 / P95 1524 / Max 11620 on concurrent load.

---

## 6. R3 regression

```text
23 PASS / 2 DATA GAP / 0 FAIL
```

(`scripts/r3_post_deploy_live_acceptance.py` — `canonical_verdict`)

---

## 7. R4-1 regression

First concurrent run hit SSL handshake timeout. **Retry alone:**

```text
47 PASS / 2 DATA GAP / 0 FAIL
```

(`scripts/r4_1_live_acceptance.py`)

---

## 8. Full Chat UI

| Item | Status |
|------|--------|
| URL | https://www.bridgeedi.com/dashboard/ai |
| Auth | Operator session available |
| Smoke: `Which products grew the most?` | **PASS** — growth table with prev/curr years, abs/pct change, `NEW_NO_PRIOR_BASE` / `CONTINUING`, explore-further drills |
| Full multi-turn UI chain (17 turns) | **PARTIAL** — not fully re-run in UI; equivalent API chains PASS |

---

## 9. DATA GAP behavior

| Turn | Result |
|------|--------|
| Which products grew the most? | PASS |
| Show logistics cost. | DATA_GAP / CANNOT_ANSWER |
| Show net profit. | DATA_GAP / CANNOT_ANSWER |
| Show revenue growth. | PASS (context kept) |
| Show COGS. | PASS |
| Show customers. | PASS |

---

## 10. Remaining genuine limitations

- Unsupported: logistics cost amounts, product net profit/OPEX, budget/target, certified discount/tax/freight, true inventory aging
- Phrasing gap: “added the most revenue” not entering R4-2 growth path
- Single missing year (e.g. only 2099) padded to default 2004/2005 instead of honest empty
- Full Chat operator UI acceptance still outstanding

---

## 11. Acceptance matrix

| Capability | Pipeline | SQL | Data | Accuracy | Context | UI | Latency | Status |
|---|---|---|---|---|---|---|---|---|
| Revenue growth | OK | OK | OK | OK | OK | — | OK | PASS |
| Revenue decline | OK | OK | OK | OK | OK | — | OK | PASS |
| GP growth / decline | OK | OK | OK | OK | OK | — | OK | PASS |
| Quantity / ASP | OK | OK | OK | OK | OK | — | OK | PASS |
| Margin improve / decline* | OK | OK | OK | OK | OK | — | OK | PASS |
| Absolute growth | partial | — | — | — | — | — | — | **FAIL** (“added most”) |
| Percentage growth | OK | OK | OK | OK | OK | — | OK | PASS |
| YoY / MoM / QoQ | OK | OK | OK | OK | OK | — | OK | PASS |
| Growth/decline drivers | OK | OK | OK | OK | OK | — | OK | PASS |
| Customer mix / drills | OK | OK | OK | OK | OK | — | OK | PASS |
| Product → supplier/inventory | OK | OK | OK | — | OK | — | OK | PASS |
| DATA GAP recovery | OK | — | gap | — | OK | — | OK | PASS |
| Empty period (single missing year) | — | — | — | — | — | — | — | **FAIL** |
| R3 regression | — | — | — | — | — | — | — | **23/2/0** |
| R4-1 regression | — | — | — | — | — | — | — | **47/2/0** |
| Full Chat | OK smoke | OK | OK | OK | — | OK | — | **SMOKE PASS** / full chain partial |
| Independent SQL | — | OK | OK | **0 mismatch** | — | — | — | PASS |

\*R3 “biggest margin decline” still correctly routes to `margin_decline_drivers`.

---

## Git check

```text
branch: phase12-first-customer-ready
HEAD:   a5699e5
911afed is ancestor of origin/HEAD: YES
```

Not committed: secrets, live JSON dumps, tokens.

Reusable scripts used/added for acceptance:
- `scripts/r4_2_live_acceptance.py`
- `scripts/r4_2_independent_sql.py`
- `scripts/r4_2_post_deploy_extra_probes.py` (new harness, local)

---

## Stop rule

**R4-3 not started.** No R4-2 rewrite performed in this acceptance pass.
