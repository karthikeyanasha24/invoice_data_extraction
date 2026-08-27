export type AnalysisTrust = {
  intent?: string;
  metric?: string;
  period?: string;
  calculation?: string;
  limitations: string[];
  source?: string;
};

const GOVERNED =
  'Revenue = billing NETWR; COGS = billing WAVWR (document cost); Gross profit = Revenue − COGS; Gross margin % = Gross profit / Revenue. This is not true net profit.';

export function analysisTrustFromResult(result: any): AnalysisTrust {
  const qp = result?.query_plan || result?.queryPlan || {};
  const ac = qp.analytical_context || {};
  const meta = result?.meta || {};
  const intent = String(ac.intent || qp.intent || meta.intent || '').trim() || undefined;
  const metric = String(ac.metric || ac.primary_metric || ac.selected_metric || '').trim() || undefined;
  const period = String(
    ac.period_label || ac.period || ac.time_grain || ac.comparison_window || '',
  ).trim() || undefined;
  const gaps = [
    ...(Array.isArray(meta.warnings) ? meta.warnings : []),
    ...(Array.isArray(ac.data_gaps) ? ac.data_gaps : []),
    ...(Array.isArray(meta.data_gaps) ? meta.data_gaps : []),
  ]
    .map((g) => String(g || '').trim())
    .filter(Boolean);
  const source = intent?.startsWith('inventory')
    ? 'Current inventory snapshot (not historical stock movements)'
    : 'SAP billing extract (governed metrics)';
  return {
    intent,
    metric,
    period,
    calculation: GOVERNED,
    limitations: Array.from(new Set(gaps)),
    source,
  };
}

export const DATA_GAP_TRY_INSTEAD = [
  { label: 'Show current inventory', question: 'Show inventory.' },
  { label: 'Compare inventory with sales', question: 'Show inventory versus sales.' },
  { label: 'Highest inventory products', question: 'Which products have the highest inventory?' },
];
