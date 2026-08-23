# Multi-dimensional BI — Metric & Relationship Support Matrix

Generated from live schema inventory (`schema_full.json`, `schema_ai_config.json`, `sql_catalog.json`).
**Do not invent joins or metrics beyond this matrix.**

## Metrics

| Metric | Status | Definition (governed) | Tables | Caveats |
|--------|--------|-----------------------|--------|---------|
| Revenue / net sales | **supported** | `SUM(vbrp.netwr)` | vbrp, VBRK | Invoice net value — not profit |
| COGS | **supported** | `SUM(vbrp.wavwr)` | vbrp, VBRK | Document cost in doc currency. Not ACDOCA (absent from schema_full) |
| Gross profit | **supported** | Revenue − COGS (NETWR − WAVWR) | vbrp, VBRK | Not true net profit |
| Gross margin % | **supported** | Gross profit / Revenue × 100 | vbrp, VBRK | Depends on WAVWR population |
| Invoice count | **supported** | `COUNT(DISTINCT VBRK.vbeln)` | VBRK | |
| Quantity | **supported** | `SUM(vbrp.fkimg)` | vbrp | |
| Net profit / EBIT | **unavailable** | — | — | Operating costs not linked at product grain |
| Logistics / freight cost | **unavailable** | — | LIKP/LIPS counts only | No reliable cost amount linkage |
| Product expiry | **partial** | MARA MHDHB/MHDRZ/SLED_BBD; LIPS.VFDAT | MARA, LIPS | Fields exist; completeness varies |
| Actual vs budget/target | **unavailable** | — | — | No budget/target cube in schema_full |

## Dimensions

| Dimension | Status | Source | Notes |
|-----------|--------|--------|-------|
| Product | supported | vbrp.matnr + MAKT.maktx | |
| Customer | supported | VBRK.kunag + KNA1 | |
| Industry | supported | KNA1.brsch + T016T.brtxt | |
| Country / region | **partial** | VBRK.land1 (country) | REGIO/BZIRK limited; treated as country BI |
| Year / period | supported | VBRK.fkdat | |
| Currency | supported | VBRK.waerk | Mixed-currency rankings must stay grouped |

## Relationships (approved)

| From → To | Keys | Confidence | Meaning |
|-----------|------|------------|---------|
| vbrp → VBRK | vbeln | high | Billing item → header |
| VBRK → KNA1 | kunag = kunnr | high | Sold-to customer |
| KNA1 → T016T | brsch | high | Industry text |
| vbrp → MAKT/MARA | matnr | high | Product master |
| VBAK → VBAP | vbeln | high | Sales order |
| LIKP → LIPS | vbeln | high | Delivery |
| EKKO → EKPO | ebeln | high | Purchase order |
| VBFA | vbtyp_v / vbtyp_n | medium | Document flow order→delivery→billing |
| vbrp ↔ EKPO | matnr only | **low / unsafe for COGS** | Prefer WAVWR for invoice COGS |

## Process stages present

| Stage | Tables | BI support |
|-------|--------|------------|
| Purchase | EKKO, EKPO, LFA1 | counts / PO value |
| Inventory | MBEW, MARD | stock value / qty; slow/fast via billed qty proxy |
| Sales order | VBAK, VBAP | orders |
| Delivery | LIKP, LIPS | counts; cost limited |
| Billing | VBRK, vbrp | full revenue/COGS proxy |
| Finance GL | FAGLFLEXA, BSEG | PC/cost center — not product net profit |

## Deep intents (analytical_deep_dive)

| Intent | Supported |
|--------|-----------|
| product_profitability / lowest_margin / COGS / components | yes (WAVWR) |
| customers_of_selection / industry / country | yes |
| product × industry × region | yes |
| period compare / monthly trend | yes |
| margin decline + customer drivers | yes (YoY margin Δ) |
| inventory analysis | partial (MBEW + velocity proxy) |
| expiry / expiry by industry | partial |
| process sell / buy | stage counts + VBFA |
| net profit / logistics cost / budget | data gap |

## Engine path

```text
classify_turn → (NON_BUSINESS / CLARIFICATION)
             → try deep_multidim (governed plan→SQL)
             → FOLLOWUP_DELTA / intent_sql_fast / sql_catalog / universal
```

Adaptive follow-up / clarification hardening remains intact.
