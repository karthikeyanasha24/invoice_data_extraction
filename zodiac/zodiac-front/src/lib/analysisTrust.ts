export type AnalysisTrust = {
  intent?: string;
  metric?: string;
  period?: string;
  aggregation?: string;
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

function definitionFor(intent?: string): string {
  const i = (intent || '').toLowerCase();
  if (i.startsWith('inventory')) return INVENTORY;
  if (i.includes('supplier') || i.includes('purchase')) return PURCHASE;
  return BILLING;
}

function sourceFor(intent?: string): string {
  const i = (intent || '').toLowerCase();
  if (i.startsWith('inventory')) return 'Current inventory snapshot (not historical stock movements)';
  if (i.includes('supplier') || i.includes('purchase')) return 'SAP purchase orders (EKPO/EKKO/LFA1)';
  return 'SAP billing extract (governed metrics)';
}

function aggregationFor(intent?: string, ac: Record<string, unknown> = {}): string | undefined {
  const fromCtx = String(ac.aggregation || ac.aggregation_grain || ac.grain || '').trim();
  if (fromCtx) return fromCtx;
  const i = (intent || '').toLowerCase();
  if (i.startsWith('inventory')) return 'Product (and plant when requested) on the current snapshot';
  if (i.includes('supplier_concentration')) return 'Supplier on purchase-order item totals, then share of those totals';
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
    metric,
    period,
    aggregation: aggregationFor(intent, ac),
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
