# R4-4 Production Acceptance Report

**Date:** 2026-08-28  
**Branch:** `phase12-first-customer-ready`  
**Scope:** Supplier concentration by product (purchase-order grain)  
**R4-5 / R4-6:** not started (delivery cycle and customer mix were not data-governed enough to ship in this assignment)

---

## Final verdict

```text
R4-4 NOT COMPLETE ON PRODUCTION
```

The capability is implemented, unit-tested, and grain-guarded on this branch. Live `zodiac-back` still routes `Show supplier concentration.` to `suppliers_of_selection` (R3 listing). Independent SQL vs AI comparison is **BLOCKED** until that intent is live.

Production R3–R4-3 remain safe. This CLI cannot see the `zodiac-back` Vercel project and did not deploy `zodiac-api-nu`.

---

## 1. Discovery (why this, not aging / turnover / net profit)

| Question | Finding |
| --- | --- |
| Business value | Purchase share / single-source visibility without inventing supplier profit |
| Schema | `EKPO` / `EKKO` / `LFA1` present |
| Already in R3 | `suppliers_of_selection` lists suppliers × product with PO value |
| What is new | Intent `supplier_concentration` with `share_of_po_value_pct` |
| Grain | `po_item`; no `VBRP ⋈ EKPO` monetary fan-out |
| Not R4-4 | Inventory aging, true turnover, net profit (still DATA GAP; MSEG/ACDOCA absent) |
| Not implemented | HHI, automated risk flags, supplier profit, delivery cycle (R4-5), customer mix (R4-6) |

`Show their suppliers.` remains `suppliers_of_selection`. Concentration phrases: supplier concentration / purchase share / single-source.

---

## 2. Metric and grain

| Metric | Definition | Grain | Source |
| --- | --- | --- | --- |
| Share of PO value | Supplier PO net value / all selected PO net value | supplier on `po_item` | `EKPO.NETWR` window |

This is **association**, not supplier profit, not invoice COGS, not a single-source policy threshold.

Unsafe pattern rejected by grain guard:

```text
VBRP JOIN EKPO SUM(NETWR)
```

---

## 3. Local tests

`tests/test_r4_4_supplier_concentration.py`

- R3 suppliers follow-up unchanged
- Concentration intent + SQL uses EKPO/EKKO/LFA1, `SHARE_OF_PO_VALUE_PCT`, no VBRP
- Product context preserved
- Grain `po_item` / aggregation `supplier`
- Adversarial VBRP⋈EKPO flagged unsafe; compiled concentration SQL is not

Pytest (R3 + R4-1 + R4-2 + R4-3 + R4-4 goldens): **76 PASS**.

---

## 4. Independent SQL

Script: `scripts/r4_4_independent_sql.py` (uses `DATABASE_URL`; credentials not committed).

PO-grain share from production-shaped data (top 5):

| Supplier | Share of PO value |
| --- | --- |
| 0000005557 | 49.35% |
| 0000001095 | 42.02% |
| 0000001075 | 1.96% |
| 0000000300 | 1.35% |
| 0000001235 | 0.74% |

AI vs independent comparison: **BLOCKED** (`ai_intent` is not `supplier_concentration` on live `zodiac-back`).

Do not treat the DB shares as a live AI PASS.

---

## 5. Live `zodiac-back` probes (2026-08-28)

`scripts/r4_4_live_acceptance.py`

| Probe | Intent | Verdict |
| --- | --- | --- |
| Highest profits | `product_profitability` | PASS |
| Show their suppliers | `suppliers_of_selection` | PASS |
| Show supplier concentration | `suppliers_of_selection` | **NOT_DEPLOYED** |
| Show supplier profit | `suppliers_of_selection` (PO listing, no VBRP fan-out) | PASS (no fan-out) |
| Inventory aging | CANNOT_ANSWER | DATA GAP |
| Show inventory again | `inventory_analysis` | PASS |

Counts: **4 PASS / 1 DATA GAP / 1 NOT_DEPLOYED / 0 FAIL**.

---

## 6. Engineering checklist

| Gate | Status |
| --- | --- |
| Schema audit | PASS (EKPO/EKKO/LFA1) |
| Metric definition | PASS |
| Grain definition | PASS (`po_item`) |
| Semantic intent | PASS locally |
| SQL implementation | PASS locally |
| Grain guard | PASS locally |
| Follow-up resolver | PASS locally |
| Context preservation | PASS locally |
| DATA GAP (aging / net profit / supplier profit as profit) | PASS (aging/net profit live; profit not attributed via VBRP⋈EKPO) |
| Golden tests | PASS |
| Independent SQL vs AI | **BLOCKED** until live intent |
| Performance | Not measured for new intent (not live) |
| Frontend chip | Implemented locally; not on www |
| Full Chat | Existing R3–R4-3 chain PASS on live; concentration not live |
| Production deploy | **BLOCKED** (no `zodiac-back` in this Vercel account) |

---

## 7. Required to finish R4-4

1. Deploy this branch to existing **`zodiac-back`** only (never `zodiac-api-nu`).
2. Re-run `scripts/r4_4_live_acceptance.py` — expect `supplier_concentration` and `has_share=true`.
3. Re-run `scripts/r4_4_independent_sql.py` — expect AI vs DB share match (no unexplained material mismatch).
4. Re-run frozen R3 / R4-1 / R4-2 / R4-3 live suites (must stay 23/2/0, 47/2/0, 40/1/0, 31/6/0).

Until then, production is **safe to leave as V2 + R4-3**.
