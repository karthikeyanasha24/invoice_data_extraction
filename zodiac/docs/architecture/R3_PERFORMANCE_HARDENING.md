# R3 performance baseline & hardening notes (2026-08-26)

## Method

- Target: `https://zodiac-back.vercel.app`
- Harness: `zodiac/zodiac-api/scripts/r3_perf_baseline.py`
- Sample: **12 warm requests** per scenario after 1 warmup (N=12 practical; not 20 due to live load)
- Results artifact: `r3_perf_baseline.json` (local; do not commit secrets/dumps)

## Warm-path percentiles (client total ms)

| Scenario | P50 | P75 | P90 | P95 | P99 | Max | Queries | deep_ms≈ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| basic_sales | 381 | — | — | 499 | 541 | 552 | — | — |
| highest_profit | 758 | — | — | 1016 | 1044 | 1052 | 1 | 371 |
| cogs | 703 | — | — | 807 | 836 | 844 | 1 | 218 |
| lowest_margin | 743 | — | — | 904 | 911 | 913 | 1 | 381 |
| product→customer | 674 | — | — | 829 | 833 | 834 | 1 | 255 |
| product→industry | 655 | — | — | 1001 | 1107 | 1134 | 1 | 188 |
| supplier | 523 | — | — | 909 | 994 | 1016 | 1 | 167 |
| product_group | 791 | — | — | 1020 | 1157 | 1192 | 1 | 177 |
| ASP | 788 | — | — | 950 | 1004 | 1018 | 1 | 218 |
| inventory | 901 | — | — | 1153 | 1230 | 1250 | **2** | 474 |
| purchase_history | 707 | — | — | 958 | 960 | 961 | 1 | 257 |
| root_cause | 630 | — | — | 801 | 853 | 867 | 2 | 146 |
| **year_compare** | **2745** | — | — | **3106** | **3191** | **3213** | 1 | **2267** |
| regions follow-up | 719 | — | — | 968 | 1028 | 1043 | 1 | 122 |

## Bottleneck evidence

| Finding | Evidence | Classification |
|---------|----------|----------------|
| Prior Max ≈9444ms on purchase history | Warm P95≈958ms; cold/warm ≈873–1347ms | **Not** steady SQL cost; prior spike = cold start / transient |
| Year compare dominates P95 | Warm P50≈2745ms; deep_ms≈2267ms of that | **SQL/DB execution** on `period_compare` |
| Inventory slower than peers | qcount=2; deep_ms≈474 | **Multi-query** (MBEW + billing velocity) |
| Most R3 follow-ups meet P50&lt;1s | supplier/cogs/root_cause etc. | Healthy warm path |
| Gateway/network overhead | Client − deep_ms ≈ 300–500ms typical | Vercel + persist + RTT |

## Cold / warm pairs (45s idle)

| Scenario | coldish | warm | Interpretation |
|----------|--------:|-----:|----------------|
| purchase_history | 873 | 852–1347 | No multi-second cold cliff in this window |
| highest_profit | 731 | 724–1053 | Stable |
| year_compare | 3944 | 2677–2905 | Mild cold adder (~1.2s); warm still DB-bound |

## Optimizations applied (code, not yet production-deployed)

1. **Inventory**: run `billing_velocity_proxy` only when question asks sales/compare/slow/fast — snapshot-only asks use MBEW alone.
2. **Year compare**: when product selection exists, tighten LIMIT to selection×years (not fixed 200).
3. **Instrumentation**: return `plan_ms` / `db_ms` / `transform_ms` / `per_query_ms` in deep meta for future live attribution.

Regression: **35/35** R3-related pytest PASS locally after these changes.

## Targets vs measured (warm)

| Target | Status |
|--------|--------|
| P50 &lt; 1s | **Met** for all scenarios except year_compare |
| P95 &lt; 3s | **Met** except year_compare (P95≈3.1s borderline) |
| P99 &lt; 5s | **Met** all measured scenarios |
| Occasional &gt;5s | Document as **cold start / transient**; do not optimize application blindly |

## Production recommendation

1. Keep `036b52a` as the accepted behavioral baseline.
2. Deploy the hardening commit (inventory skip + compare LIMIT + timings) via Andy → `zodiac-back` only.
3. Re-run `r3_perf_baseline.py` after deploy; expect inventory P50 drop and year_compare improvement when selection-filtered.
4. Next SQL work: EXPLAIN `period_compare` on the SAP extract (TRIM joins) — only with measured plans.
5. Do not parallelize DB sessions until per-query timings prove multi-query waits dominate (root_cause already fast).
