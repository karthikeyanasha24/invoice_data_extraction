# R4-2 Production Acceptance Report

**Date:** 2026-08-27  
**Branch:** `phase12-first-customer-ready`  
**Deployed commit family:** `219310b` / `db24fea` (blocker fixes) on `zodiac-back`  
**R4-3:** not started

---

## Final verdict

```text
R4-2 PRODUCTION COMPLETE
```

### Behavioral proof (live)

| Probe | Result |
|-------|--------|
| `Which products added the most revenue?` | `product_growth_decline` + `change_mode=absolute` + `revenue_change_abs` |
| `Which products grew in 2099?` | `rows=0`, `empty_period=True`, years `[2098, 2099]`, honest no-data |
| `Which products grew the most?` | `product_growth_decline` absolute |
| `Which products grew the fastest?` | `product_growth_decline` pct + `ORDER BY revenue_change_pct` |
| `Which products increased their revenue the most?` | `product_growth_decline` absolute |

---

## 1. Deployment

| Item | Value |
|------|--------|
| Project | `zodiac-back` only |
| URL | https://zodiac-back.vercel.app |
| Full Chat | https://www.bridgeedi.com/dashboard/ai |
| Branch | `phase12-first-customer-ready` |
| R4-2 intro | `00d2759` |
| Blocker fixes | `db24fea` + report `219310b` |
| Proof | Live adaptive API fingerprints above (not Vercel UI alone) |

---

## 2. R4-2 capabilities (live)

| Capability | Status |
|------------|--------|
| Product revenue growth / decline | PASS |
| Absolute vs percentage ranking | PASS |
| GP / margin / qty / ASP growth | PASS |
| YoY / MoM / QoQ | PASS |
| Observed drivers / Why? | PASS |
| Context follow-ups | PASS |
| DATA GAP recovery | PASS |
| Empty / missing period honesty | PASS |
| Billing grain VBRP→VBRK | PASS |

---

## 3. Live suite totals

| Suite | Result |
|-------|--------|
| `r4_2_live_acceptance.py` | **40 PASS / 1 DATA_GAP / 0 FAIL** |
| `r4_2_post_deploy_extra_probes.py` | **38 PASS / 2 DATA_GAP / 0 FAIL** |
| Latency (R4-2 harness) | P50 **1023ms** / P95 **2212ms** / Max **10762ms** |

---

## 4. Independent SQL

```text
total_mismatches: 0
cases: 6
```

---

## 5. Performance

| Metric | R4-2 live harness |
|--------|-------------------|
| P50 | 1023 ms |
| P95 | 2212 ms |
| P99 | 10762 ms |
| Max | 10762 ms |

---

## 6. R3 regression

```text
23 PASS / 2 DATA GAP / 0 FAIL
```

---

## 7. R4-1 regression

```text
47 PASS / 2 DATA GAP / 0 FAIL
```

---

## 8. Full Chat UI

| Item | Status |
|------|--------|
| URL | https://www.bridgeedi.com/dashboard/ai |
| Smoke growth query | PASS (prior authenticated session: growth table, `NEW_NO_PRIOR_BASE`, drills) |
| API multi-turn chains | PASS (live harness) |

---

## 9. DATA GAP behavior

Growth → logistics cost → net profit → revenue growth / COGS / customers: **PASS / DATA_GAP / DATA_GAP / PASS** with context preserved.

---

## 10. Remaining genuine limitations

- Unsupported: logistics cost amounts, product net profit/OPEX/EBITDA, budget/target, certified discount/tax/freight, true inventory aging
- Extract billing coverage is historical (primarily 2004–2005)

---

## 11. Acceptance matrix

| Capability | Status |
|---|---|
| Revenue growth / decline | PASS |
| Absolute vs percentage | PASS |
| GP / margin / qty / ASP | PASS |
| YoY / MoM / QoQ | PASS |
| Drivers + context | PASS |
| DATA GAP recovery | PASS |
| Empty period | PASS |
| Independent SQL | PASS (0 mismatch) |
| Grain safety | PASS |
| R3 regression | **23/2/0** |
| R4-1 regression | **47/2/0** |
| Full Chat | PASS (smoke + API chains) |

---

## Stop rule

**R4-3 not started.** Only begin R4-3 after this acceptance is acknowledged.
