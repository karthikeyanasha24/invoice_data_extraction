/** Keep the full analytical explanation separate from its short overview. */
export function analystAnswerText(result: { answer?: string; summary?: string }): string {
  return result.answer?.trim() || result.summary?.trim() || '';
}

/** Named comparison measures are amounts, not chronological axes. */
export function isComparisonMeasure(key: string): boolean {
  return /^(period_[ab]|(?:base|comparison)_period(?:_amount|_value|_total)?|(?:sales|netwr|amount|total)_\d{4})$/i.test(key);
}

/** Explain period aliases only when the question names exactly two years. */
export function comparisonYears(question: string): [string, string] | null {
  const years = [...new Set((question.match(/\b(?:19|20)\d{2}\b/g) || []))];
  return years.length === 2 ? [years[0], years[1]] : null;
}

export function comparisonColumnLabel(key: string, question: string): string {
  const years = comparisonYears(question);
  if (!years) return key.replace(/_/g, ' ');
  if (/^period_a$/i.test(key)) return `${years[0]} (period A)`;
  if (/^period_b$/i.test(key)) return `${years[1]} (period B)`;
  if (/^change$/i.test(key)) return `Change (${years[1]} − ${years[0]})`;
  return key.replace(/_/g, ' ');
}

export function labelComparisonText(value: string, question: string): string {
  const years = comparisonYears(question);
  if (!years) return value;
  return value.replace(/\bperiod[_ ]a\b/gi, `${years[0]} (period A)`)
    .replace(/\bperiod[_ ]b\b/gi, `${years[1]} (period B)`);
}

/** Numeric business keys label a category; their magnitude is not a measure. */
export function isAnalystChartDimension(key: string): boolean {
  return /^(client|sap_client|client_id|mandt|vbeln|kunnr|kunag|lifnr|matnr|werks|bukrs|vkorg|vtweg|spart|belnr|posnr|ebelp|ebeln|fkdat|budat|gjahr|pernr|aubel|knumv)$/i.test(key)
    || /(_id|_code|_no|_key|_num|id$|code$|no$|num$|sno$|ref$|seq$)/i.test(key);
}

export function isAnalystChartDate(key: string, value: unknown): boolean {
  if (isComparisonMeasure(key)) return false;
  // Four-digit counts and amounts are not years merely because of their value.
  return /date|month|period|year|quarter|week/i.test(key)
    || /^\d{4}-\d{2}(-\d{2})?$/.test(String(value ?? '').trim());
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
