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
