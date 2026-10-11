/** Keep the full analytical explanation separate from its short overview. */
export function analystAnswerText(result: { answer?: string; summary?: string }): string {
  return result.answer?.trim() || result.summary?.trim() || '';
}

/** Named comparison measures are amounts, not chronological axes. */
export function isComparisonMeasure(key: string): boolean {
  return /^(period_[ab]|(?:base|comparison)_period(?:_amount|_value|_total)?|(?:sales|netwr|amount|total)_\d{4})$/i.test(key);
}

export function defaultAnalystChartType(preferred: string, available: string[]): string {
  return available.includes(preferred) ? preferred : (available.includes('bar') ? 'bar' : 'table');
}

type CurrencyChart = { currency?: string; title?: string; data?: any[] };

export function analystChartCurrency(chart: CurrencyChart): string {
  const row = chart.data?.[0];
  const key = row && Object.keys(row).find(name => /^(currency|waerk|waers)$/i.test(name));
  return String(chart.currency || (key ? row[key] : '') || chart.title?.match(/\(([A-Z]{3})\)$/)?.[1] || 'Other').trim();
}

/** Start with the currency that has the most chart observations; no amounts are combined. */
export function defaultAnalystCurrency(charts: CurrencyChart[]): string {
  const counts = new Map<string, number>();
  for (const chart of charts) {
    const currency = analystChartCurrency(chart);
    counts.set(currency, (counts.get(currency) || 0) + (chart.data?.length || 0));
  }
  return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0]?.[0] || '';
}
