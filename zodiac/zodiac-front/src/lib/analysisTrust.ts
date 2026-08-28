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
};

const BILLING =
  'Revenue = billing NETWR; COGS = billing WAVWR (document cost); Gross profit = Revenue − COGS; Gross margin % = Gross profit / Revenue. This is not true net profit.';

const INVENTORY =
  'Stock value = MBEW.SALK3; valuated quantity = MBEW.LBKUM; unrestricted quantity = MARD.LABST. This is a current snapshot, not historical inventory movements.';

const PURCHASE =
  'Purchase value = EKPO.NETWR at purchase-order item grain. This is not invoice COGS and not supplier profit.';

const CONCENTRATION =
  'Supplier PO value as a percentage of total PO value (EKPO.NETWR / sum of EKPO.NETWR × 100). Share is unavailable when total PO value is zero. This is not supplier profit.';

function definitionFor(intent?: string): string {
  const i = (intent || '').toLowerCase();
  if (i.includes('supplier_concentration') || i.includes('purchase concentration')) return CONCENTRATION;
  if (i.startsWith('inventory')) return INVENTORY;
  if (i.includes('supplier') || i.includes('purchase')) return PURCHASE;
  return BILLING;
}

function sourceFor(intent?: string): string {
  const i = (intent || '').toLowerCase();
  if (i.startsWith('inventory')) return 'Current inventory snapshot (not historical stock movements)';
  if (i.includes('supplier_concentration')) return 'Purchasing / purchase-order data (EKPO, EKKO, LFA1)';
  if (i.includes('supplier') || i.includes('purchase')) return 'SAP purchase orders (EKPO/EKKO/LFA1)';
  return 'SAP billing extract (governed metrics)';
}

function grainFor(intent?: string, ac: Record<string, unknown> = {}): string | undefined {
  const i = (intent || '').toLowerCase();
  if (i.includes('supplier_concentration')) return 'PO / supplier purchasing grain';
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
  return 'Billing item, then the selected business dimension';
}

function analysisLabelFor(intent?: string): string | undefined {
  const i = (intent || '').toLowerCase();
  const labels: Record<string, string> = {
    supplier_concentration: 'Supplier concentration',
    suppliers_of_selection: 'Suppliers of the selected products',
    inventory_analysis: 'Current inventory snapshot',
    inventory_sales_comparison: 'Inventory versus sales',
    inventory_by_plant: 'Inventory by plant',
    inventory_risk_analysis: 'Inventory versus sales risk',
    product_profitability: 'Product profitability',
    product_growth: 'Product growth',
    product_decline: 'Product decline',
  };
  if (labels[i]) return labels[i];
  if (!intent) return undefined;
  if (/_/.test(intent)) return 'Governed SAP analysis';
  return intent;
}

function aggregationFor(intent?: string, ac: Record<string, unknown> = {}): string | undefined {
  const i = (intent || '').toLowerCase();
  if (i.includes('supplier_concentration')) return 'Supplier-level purchase-order aggregation';
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

export function analysisTrustFromResult(result: any): AnalysisTrust {
  const qp = result?.query_plan || result?.queryPlan || {};
  const ac = qp.analytical_context || {};
  const meta = result?.meta || {};
  const intent = String(ac.intent || qp.intent || meta.intent || '').trim() || undefined;
  const metric = String(ac.metric || ac.primary_metric || ac.selected_metric || '').trim() || undefined;
  const period =
    String(ac.period_label || ac.period || ac.time_grain || ac.comparison_window || '').trim() ||
    (intent?.startsWith('inventory') ? 'Current snapshot' : 'Not specified in this result');
  const gaps = [
    ...(Array.isArray(meta.warnings) ? meta.warnings : []),
    ...(Array.isArray(ac.data_gaps) ? ac.data_gaps : []),
    ...(Array.isArray(meta.data_gaps) ? meta.data_gaps : []),
  ]
    .map((g) => String(g || '').trim())
    .filter(Boolean);
  const total = result?.totalCount ?? result?.rowCount ?? meta?.row_count;
  const rowLimit =
    total != null && Number.isFinite(Number(total))
      ? `${Number(total)} row${Number(total) === 1 ? '' : 's'} returned (display may be paginated)`
      : undefined;
  return {
    intent,
    analysisLabel: analysisLabelFor(intent),
    metric,
    period,
    aggregation: aggregationFor(intent, ac),
    grain: grainFor(intent, ac),
    rowLimit,
    calculation: definitionFor(intent),
    limitations: Array.from(new Set(gaps)),
    source: sourceFor(intent),
  };
}

export const DATA_GAP_TRY_INSTEAD = [
  { label: 'Show current inventory', question: 'Show inventory.' },
  { label: 'Compare inventory with sales', question: 'Show inventory versus sales.' },
  { label: 'Highest inventory products', question: 'Which products have the highest inventory?' },
];

export const NET_PROFIT_TRY_INSTEAD = [
  { label: 'Highest-profit products', question: 'Show the products with the highest profits.' },
  { label: 'Gross margin', question: 'Which products had the biggest margin decline?' },
  { label: 'Show COGS', question: 'Show COGS.' },
];

export function dataGapTryInstead(message: string): { label: string; question: string }[] {
  if (/net profit|ebitda|operating profit|opex/i.test(message || '')) {
    return NET_PROFIT_TRY_INSTEAD;
  }
  return DATA_GAP_TRY_INSTEAD;
}
