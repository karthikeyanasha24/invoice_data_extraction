export type AnalysisTrust = {
  intent?: string;
  analysisLabel?: string;
  metric?: string;
  period?: string;
  aggregation?: string;
  grain?: string;
  rowLimit?: string;
  calculation?: string;
  limitations: string[];
  source?: string;
  domain?: string;
  tables?: string;
  joins?: string;
};

const BILLING =
  'Revenue = billing NETWR; COGS = billing WAVWR (document cost); Gross profit = Revenue − COGS; Gross margin % = Gross profit / Revenue. This is not true net profit.';

const INVENTORY =
  'Stock value = MBEW.SALK3; valuated quantity = MBEW.LBKUM; unrestricted quantity = MARD.LABST. This is a current snapshot, not historical inventory movements.';

const PURCHASE =
  'Purchase value = EKPO.NETWR at purchase-order item grain. This is not invoice COGS and not supplier profit.';

const CONCENTRATION =
  'Supplier PO value as a percentage of total PO value (EKPO.NETWR / sum of EKPO.NETWR × 100). Share is unavailable when total PO value is zero. This is not supplier profit.';

const GAP_DEFINITION =
  'No unsupported number was calculated. The question was understood; the required data is not in this extract.';

/** Business headings for every governed intent. Never show the raw slug. */
export const ANALYSIS_LABELS: Record<string, string> = {
  product_profitability: 'Revenue performance',
  product_growth: 'Sales performance',
  product_decline: 'Sales performance',
  product_growth_decline: 'Sales performance',
  supplier_concentration: 'Supplier concentration',
  suppliers_of_selection: 'Suppliers for the selected products',
  inventory_analysis: 'Inventory position',
  inventory_sales_comparison: 'Inventory versus sales',
  inventory_risk_analysis: 'High inventory with low sales',
  inventory_by_plant: 'Plant performance',
  monthly_trend: 'Monthly trend',
  quarterly_trend: 'Quarterly trend',
  customers_of_selection: 'Customer analysis',
  customer_industry_region: 'Customer analysis',
  customer_product_mix: 'Customer analysis',
  country_breakdown: 'Regional performance',
  industry_breakdown: 'Industry breakdown',
  product_group_breakdown: 'Product group breakdown',
  product_industry_region: 'Product by industry and region',
  product_by_industry: 'Product by industry',
  cogs_by_product: 'Cost of goods sold',
  margin_by_product: 'Gross margin',
  lowest_margin_products: 'Lowest-margin products',
  profit_components: 'Profit components',
  margin_decline_drivers: 'Margin decline',
  purchase_history: 'Purchase history',
  period_compare_selection: 'Year-over-year comparison',
  process_sell: 'Selling process',
  process_buy: 'Buying process',
  process_sell_and_buy: 'Selling and buying process',
  product_expiry: 'Product expiry',
  product_expiry_by_industry: 'Product expiry by industry',
  dimensional_extend: 'Further breakdown',
  sales_order_analysis: 'Sales orders',
  purchasing_overview: 'Purchasing',
  production_overview: 'Production',
  customer_master: 'Customer master',
  product_master: 'Product master',
  vendor_master: 'Vendor master',
  schema_knowledge: 'Data catalog',
  unsupported_deep: 'Governed analysis',
  logistics_cost_gap: 'Data limitation',
  inventory_aging_gap: 'Data limitation',
  inventory_turnover_gap: 'Data limitation',
  inventory_trend_gap: 'Data limitation',
  net_profit_gap: 'Data limitation',
};

export function analysisLabelFor(intent?: string): string | undefined {
  const i = (intent || '').trim().toLowerCase();
  if (!i) return undefined;
  if (ANALYSIS_LABELS[i]) return ANALYSIS_LABELS[i];
  if (i.includes('supplier_concentration') || i.includes('purchase concentration')) {
    return 'Supplier concentration';
  }
  if (i.startsWith('inventory_aging') || i.includes('net_profit') || i.includes('_gap')) {
    return 'Data limitation';
  }
  if (/_/.test(intent || '')) return 'Governed analysis';
  return intent;
}

function definitionFor(intent?: string, isGap = false, ac: Record<string, unknown> = {}): string {
  if (isGap) return GAP_DEFINITION;
  const i = (intent || '').toLowerCase();
  const agg = typeof ac.aggregation === 'string' ? ac.aggregation.trim() : '';
  if (i.includes('sales_order')) {
    return agg || 'Sales-order value = VBAP.NETWR; sales-order count = COUNT(DISTINCT VBAK.VBELN). This is not billed revenue.';
  }
  if (i.includes('purchasing')) return agg || PURCHASE;
  if (i.includes('production')) return agg || 'Production order quantity from AFKO. This is not sales quantity.';
  if (i.includes('schema_knowledge')) return 'Catalog meaning plus migrated-schema existence. No business number was calculated.';
  if (i.includes('supplier_concentration') || i.includes('purchase concentration')) return CONCENTRATION;
  if (i.startsWith('inventory')) return INVENTORY;
  if (i.includes('supplier') || i.includes('purchase')) return PURCHASE;
  return BILLING;
}

function sourceFor(intent?: string, isGap = false, ac: Record<string, unknown> = {}): string {
  if (isGap) return 'Not available in this extract';
  const i = (intent || '').toLowerCase();
  const domain = String(ac.domain || '').toLowerCase();
  const tables = Array.isArray(ac.tables) ? ac.tables.filter(Boolean).join(', ') : '';
  if (i.includes('sales_order') || (domain === 'sales' && i.includes('order'))) {
    return tables
      ? `SAP sales orders (${tables}) — not billed invoices`
      : 'SAP sales orders (VBAK/VBAP) — not billed invoices';
  }
  if (i.includes('purchasing') || domain === 'purchasing') {
    return tables ? `Purchase orders (${tables})` : 'Purchase orders (EKKO/EKPO)';
  }
  if (i.includes('production') || domain === 'production') {
    return tables ? `Production (${tables})` : 'Production orders (AFKO)';
  }
  if (i.includes('customer_master')) return 'Customer master (KNA1)';
  if (i.includes('product_master')) return 'Material master (MARA/MAKT)';
  if (i.includes('vendor_master')) return 'Vendor master (LFA1)';
  if (i.startsWith('inventory')) return 'Current inventory valuation (not billing, not historical stock movements)';
  if (i.includes('supplier_concentration')) {
    return 'Purchase orders (not billing revenue, not supplier profit)';
  }
  if (i.includes('supplier') || i.includes('purchase')) {
    return 'Purchase orders for the selected products (not billing revenue)';
  }
  return 'Customer billing documents (governed billed-sales extract — not sales orders, not a full P&L)';
}

function grainFor(intent?: string, ac: Record<string, unknown> = {}, isGap = false): string | undefined {
  if (isGap) return 'Not applicable';
  const i = (intent || '').toLowerCase();
  if (typeof ac.fact_grain === 'string' && ac.fact_grain.trim() && i.includes('sales_order')) {
    return String(ac.fact_grain);
  }
  if (i.includes('sales_order')) return 'Sales document item (VBAP), then the requested dimension';
  if (i.includes('purchasing')) return 'Purchase-order item';
  if (i.includes('production')) return 'Production order header';
  if (i.includes('supplier_concentration')) return 'Purchase-order item, then supplier';
  const fact = typeof ac.fact_grain === 'string' ? ac.fact_grain.trim() : '';
  if (fact === 'po_item') return 'Purchase-order item, then supplier';
  if (fact) return fact;
  if (i.includes('supplier')) return 'Purchase-order item, then supplier × product';
  if (i.startsWith('inventory_by_plant')) return 'Storage location stock, then plant';
  if (i.startsWith('inventory_sales') || i.includes('inventory_risk')) {
    return 'Independent sales totals joined to independent inventory totals at product grain';
  }
  if (i.startsWith('inventory')) return 'Current material valuation snapshot';
  if (i.includes('monthly')) return 'Billing item, then calendar month';
  if (i.includes('quarterly')) return 'Billing item, then calendar quarter';
  if (i.includes('customer')) return 'Billing item, then customer';
  if (i.includes('country') || i.includes('region')) return 'Billing item, then region';
  return 'Billing item, then the selected business dimension';
}

function aggregationFor(intent?: string, ac: Record<string, unknown> = {}, isGap = false): string | undefined {
  if (isGap) return 'Not applicable';
  const i = (intent || '').toLowerCase();
  if (i.includes('supplier_concentration')) return 'Supplier-level purchase-order value and share of total PO value';
  const fromCtx = typeof ac.aggregation === 'string'
    ? ac.aggregation.trim()
    : typeof ac.aggregation_grain === 'string'
      ? String(ac.aggregation_grain).trim()
      : '';
  if (fromCtx) return fromCtx;
  if (i.startsWith('inventory')) return 'Product (and plant when requested) on the current snapshot';
  if (i.includes('supplier')) return 'Supplier × product on purchase-order items';
  if (i.includes('monthly')) return 'Calendar month from billing date (FKDAT)';
  if (i.includes('quarterly')) return 'Calendar quarter from billing date (FKDAT)';
  if (i.includes('customer')) return 'Customer on already-aggregated billing totals';
  return 'Billing item, then grouped by the selected dimension';
}

function isDataGapResult(result: any): boolean {
  const qp = result?.query_plan || result?.queryPlan || {};
  const meta = result?.meta || {};
  const status = String(result?.answer_status || result?.answerStatus || '').toUpperCase();
  return Boolean(qp.data_gap || meta.data_gap || status === 'CANNOT_ANSWER');
}

export function analysisTrustFromResult(result: any): AnalysisTrust {
  const qp = result?.query_plan || result?.queryPlan || {};
  const ac = qp.analytical_context || qp.investigation_state || {};
  const meta = result?.meta || {};
  const calc = result?.calculation || {};
  const mode = String(result?.mode || meta.mode || result?.route || '').toLowerCase();
  if (mode === 'general_chat' || mode === 'general') {
    return { limitations: [] };
  }
  const intent = String(ac.intent || qp.intent || meta.intent || '').trim() || undefined;
  const gap = isDataGapResult(result);
  const metric = String(ac.metric || ac.primary_metric || ac.selected_metric || calc.definition || '').trim() || undefined;
  const period =
    String(calc.period || ac.period_label || ac.period || ac.time_grain || ac.comparison_window || '').trim() ||
    (gap ? 'Not applicable' : intent?.startsWith('inventory') ? 'Current snapshot' : 'Not specified in this result');
  const gaps = [
    ...(Array.isArray(calc.limitations) ? calc.limitations : []),
    ...(Array.isArray(meta.warnings) ? meta.warnings : []),
    ...(Array.isArray(ac.data_gaps) ? ac.data_gaps : []),
    ...(Array.isArray(meta.data_gaps) ? meta.data_gaps : []),
    ...(gap && meta.reason ? [String(meta.reason)] : []),
  ]
    .map((g) => String(g || '').trim())
    .filter(Boolean);
  const total = result?.totalCount ?? result?.rowCount ?? meta?.row_count;
  const rowLimit = gap
    ? 'No rows — the requested metric is not in this extract'
    : total != null && Number.isFinite(Number(total)) && Number(total) >= 0
      ? `${Number(total)} row${Number(total) === 1 ? '' : 's'} returned (display may be paginated)`
      : undefined;
  const tablesList = Array.isArray(ac.tables) ? ac.tables.map(String).filter(Boolean) : [];
  const fromCalc = String(calc.source || '').split(',').map((s: string) => s.trim()).filter(Boolean);
  const joinsList = Array.isArray(ac.joins) ? ac.joins.map(String).filter(Boolean) : [];
  return {
    intent,
    analysisLabel: gap ? (analysisLabelFor(intent) || 'Data limitation') : analysisLabelFor(intent),
    metric,
    period,
    aggregation: aggregationFor(intent, ac, gap),
    grain: String(calc.grain || '') || grainFor(intent, ac, gap),
    rowLimit,
    calculation: String(calc.definition || '') || definitionFor(intent, gap, ac),
    limitations: Array.from(new Set(gaps)),
    source: fromCalc.length ? fromCalc.join(' + ') : sourceFor(intent, gap, ac),
    domain: String(ac.domain || qp.domain || meta.domain || '').trim() || undefined,
    tables: tablesList.length ? tablesList.join(' → ') : (fromCalc.length ? fromCalc.join(' → ') : undefined),
    joins: joinsList.length ? joinsList.join('; ') : undefined,
  };
}

/**
 * Replace leftover developer headings (including restored history) with the
 * same business titles used by current investigations. Never leave a raw slug.
 */
export function humanizePublicSummary(text: string, intent?: string): string {
  let out = String(text || '');
  // Stored history used: **Deep analysis** — intent `inventory_analysis`
  out = out.replace(
    /\*{0,2}Deep analysis\*{0,2}[\s\S]{0,24}?intent\s*`?([\w.]+)`?/gi,
    (_m, slug: string) => analysisLabelFor(slug) || analysisLabelFor(intent) || 'Governed analysis',
  );
  out = out.replace(/^(#{1,3}\s+)([\w]+(?:_[\w]+)+)\s*$/gm, (_m, hashes: string, slug: string) => {
    return `${hashes}${analysisLabelFor(slug) || 'Result'}`;
  });
  out = out.replace(/^\*{0,2}([\w]+(?:_[\w]+)+)\*{0,2}\s*$/m, (m, slug: string) => {
    const label = analysisLabelFor(slug);
    return label ? `**${label}**` : m;
  });
  const label = analysisLabelFor(intent);
  if (label && intent && /_/.test(intent)) {
    out = out.replace(new RegExp(intent.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi'), label);
  }
  out = out.replace(/\b(deep_multidim|dimensional_extend)\b/gi, '');
  out = out.replace(/psycopg2\.[A-Za-z0-9_.]+/gi, '');
  out = out.replace(/\b(GroupingError|UndefinedColumn|UndefinedTable|ProgrammingError)\b/g, '');
  out = out.replace(/table [A-Za-z0-9_]+ not in verified selection[^.]*\.?/gi, '');
  out = out.replace(/\n{3,}/g, '\n\n').trim();
  return out;
}

export function humanizeDataGapMessage(message: string): string {
  return String(message || '')
    .replace(
      /I cannot accurately answer [«"]([^»"]+)[»"] with the currently linked datasets\./gi,
      'The available data does not support “$1”.',
    )
    .replace(/\*\*Why:\*\*/g, 'What is missing:')
    .replace(/\*\*What I can answer instead:\*\*/g, 'You can ask instead:')
    .replace(/Data gap — refusing to invent unsupported metrics or joins\./gi, '')
    .replace(/\bschema_full\b/gi, 'this extract')
    .replace(/\bMSEG\b/g, 'inventory movement history')
    .replace(/\bdeep_multidim\b/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

export const DATA_GAP_TRY_INSTEAD = [
  { label: 'Show current inventory', question: 'Show inventory.' },
  { label: 'Compare inventory with sales', question: 'Show inventory versus sales.' },
  { label: 'Highest inventory products', question: 'Which products have the highest inventory?' },
];

export const NET_PROFIT_TRY_INSTEAD = [
  { label: 'Highest-profit products', question: 'Show the products with the highest profits.' },
  { label: 'Gross margin', question: 'Which products had the biggest margin decline?' },
  { label: 'Show revenue', question: 'Show monthly revenue.' },
];

export const LOGISTICS_TRY_INSTEAD = [
  { label: 'Show inventory', question: 'Show inventory.' },
  { label: 'Show sales', question: 'Which products grew the most?' },
  { label: 'Show revenue', question: 'Show monthly revenue.' },
];

export const CONCENTRATION_TRY_INSTEAD = [
  { label: 'Show supplier concentration', question: 'Show supplier concentration.' },
  { label: 'Show suppliers of this selection', question: 'Show their suppliers.' },
];

export function dataGapTryInstead(message: string): { label: string; question: string }[] {
  const m = message || '';
  if (/net profit|ebitda|operating profit|opex|true net/i.test(m)) return NET_PROFIT_TRY_INSTEAD;
  if (/logistics|freight|hhi|budget|plan variance|supplier profit|supplier risk/i.test(m)) {
    if (/supplier profit|hhi|supplier risk/i.test(m)) return CONCENTRATION_TRY_INSTEAD;
    return LOGISTICS_TRY_INSTEAD;
  }
  if (/aging|turnover|inventory trend/i.test(m)) return DATA_GAP_TRY_INSTEAD;
  return DATA_GAP_TRY_INSTEAD;
}

export function summaryHasDeveloperHeading(text: string): boolean {
  return /\*{0,2}Deep analysis\*{0,2}[\s\S]{0,24}?intent\s*`?[\w.]+/i.test(text || '')
    || /(?:^|\n)#{1,3}\s+[\w]+(?:_[\w]+)+/m.test(text || '');
}
