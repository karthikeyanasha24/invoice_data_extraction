/** Keep the full analytical explanation separate from its short overview. */
export function analystAnswerText(result: { answer?: string; summary?: string }): string {
  return result.answer?.trim() || result.summary?.trim() || '';
}

/**
 * Technical proof / SAP join keys that validate SQL integrity but should not
 * dominate the user-facing business report. Full rows stay available when the
 * analyst expands “Show technical columns”.
 */
const ALWAYS_TECHNICAL_PROOF = /^(mandt|sap_client|client_id|posnr|etenr|knumv|aubel|vgbel|vgpos|fkart|fktyp|vbtyp|rfbsk|waers_match|currency_match|proof_|join_key)$/i;
const DOCUMENT_PROOF = /^(vbeln|billing_document|billing_doc|invoice_number|document_number|sales_order|order_number|ebeln)$/i;

export function isTechnicalProofColumn(key: string, question = ''): boolean {
  const normalized = String(key || '').trim();
  if (!normalized) return false;
  const wording = question.toLowerCase();
  if (ALWAYS_TECHNICAL_PROOF.test(normalized)) {
    if (/mandt|client/i.test(normalized) && /\b(client|mandt|sap client)\b/i.test(wording)) return false;
    return true;
  }
  if (DOCUMENT_PROOF.test(normalized)) {
    const asksDocuments = /\b(invoice|billing document|document number|sales order|purchase order|vbeln|ebeln)\b/i.test(wording);
    const asksAggregatedBusiness = /\b(by industry|by customer|by country|total sales|annual sales|lowest sales|highest sales|aggregate|grouped|industry and customer)\b/i.test(wording);
    if (asksAggregatedBusiness) return true;
    if (asksDocuments) return false;
    // Aggregate-looking amount columns in the same result imply document IDs are proof grain.
    return false;
  }
  return false;
}

type BusinessConcept = { ask: RegExp; column: RegExp; label: string };

const BUSINESS_CONCEPTS: BusinessConcept[] = [
  { ask: /\bindustr(?:y|ies)|sector|brsch|brtxt\b/i, column: /industr|sector|brsch|brtxt/i, label: 'Industry' },
  { ask: /\bcustomer|sold[- ]?to|ship[- ]?to|name1|kunag|kunnr\b/i, column: /customer|sold.?to|ship.?to|name1|kunag|kunnr/i, label: 'Customer' },
  { ask: /\bcountr(?:y|ies)|land1|landx\b/i, column: /country|land1|landx/i, label: 'Country' },
  { ask: /\bcurrency|waerk|waers\b/i, column: /currency|waerk|waers/i, label: 'Currency' },
  { ask: /\byear|annual|fkdat|calendar\b/i, column: /year|fkdat|billing_year|sales_year|calendar/i, label: 'Year' },
  { ask: /\bsales|revenue|turnover|total|netwr|amount|billed\b/i, column: /sales|revenue|turnover|total|netwr|amount|billed|net_value/i, label: 'Total Sales' },
  { ask: /\bproduct|material|matnr|arktx\b/i, column: /product|material|matnr|arktx/i, label: 'Product' },
];

/** Prefer business-facing columns for the asked question; keep proof keys hidden by default. */
export function businessPresentationColumns(question: string, columns: string[]): string[] {
  const unique = [...new Set(columns.filter(Boolean))];
  if (!unique.length) return [];
  const wording = question || '';
  const business = unique.filter(column => !isTechnicalProofColumn(column, wording));
  const pool = business.length ? business : unique;
  const matched: string[] = [];
  for (const concept of BUSINESS_CONCEPTS) {
    if (!concept.ask.test(wording)) continue;
    const hit = pool.find(column => concept.column.test(column) && !matched.includes(column));
    if (hit) matched.push(hit);
  }
  // Collapse to the asked business concepts when leftover columns are only IDs /
  // codes used for validation — but never drop document columns from listings.
  const asksDocuments = /\b(invoice|billing document|document number|sales order|purchase order|vbeln|ebeln|list)\b/i.test(wording);
  if (matched.length >= 2 && !asksDocuments) {
    const extras = pool.filter(column => !matched.includes(column));
    const extrasAreNoise = extras.every(column =>
      DOCUMENT_PROOF.test(column)
      || /^(kunag|kunnr|brsch|lifnr|matnr|bukrs|vkorg)$/i.test(column)
      || /(_id|_code|_key|id$|code$)/i.test(column),
    );
    if (extras.length && extrasAreNoise) return matched;
  }
  return pool;
}

export function businessColumnLabel(key: string, question = ''): string {
  const comparison = comparisonColumnLabel(key, question);
  if (comparison !== key.replace(/_/g, ' ')) return comparison;
  for (const concept of BUSINESS_CONCEPTS) {
    if (concept.column.test(key)) return concept.label;
  }
  return key.replace(/_/g, ' ');
}

/** Project rows onto the business presentation columns without mutating source data. */
export function projectBusinessRows(
  rows: Record<string, unknown>[],
  question: string,
  columns?: string[],
): { columns: string[]; rows: Record<string, unknown>[] } {
  const sourceColumns = columns?.length
    ? columns
    : (rows[0] ? Object.keys(rows[0]) : []);
  const visible = businessPresentationColumns(question, sourceColumns);
  return {
    columns: visible,
    rows: rows.map(row => Object.fromEntries(visible.map(column => [column, row[column]]))),
  };
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

/** Format SAP YYYYMMDD values when the result column identifies a date. */
export function analystDateCell(key: string, value: unknown, semanticType?: string): string | null {
  if (value == null) return null;
  const normalizedKey = key.toLowerCase().replace(/[^a-z0-9]/g, '');
  const sapDateField = /^(fkdat|audat|erdat|aedat|budat|bldat|cpudt|wadat|lfdat|bedat|eindt|prdat|valdt|zfbdt|ersda|laeda)$/i.test(normalizedKey);
  if (semanticType !== 'date' && !normalizedKey.includes('date') && !sapDateField) return null;

  const text = String(value).trim();
  const match = /^(\d{4})(\d{2})(\d{2})$/.exec(text);
  if (!match) return text;
  const [, year, month, day] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (date.getUTCFullYear() !== Number(year) || date.getUTCMonth() !== Number(month) - 1 || date.getUTCDate() !== Number(day)) return text;
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${day} ${months[Number(month) - 1]} ${year}`;
}

export function isAnalystDateColumn(key: string, semanticType?: string): boolean {
  const normalizedKey = key.toLowerCase().replace(/[^a-z0-9]/g, '');
  return semanticType === 'date' || normalizedKey.includes('date')
    || /^(fkdat|audat|erdat|aedat|budat|bldat|cpudt|wadat|lfdat|bedat|eindt|prdat|valdt|zfbdt|ersda|laeda)$/i.test(normalizedKey);
}

export function labelComparisonText(value: string, question: string): string {
  const years = comparisonYears(question);
  if (!years) return value;
  return value.replace(/\bperiod[_ ]a\b/gi, `${years[0]} (period A)`)
    .replace(/\bperiod[_ ]b\b/gi, `${years[1]} (period B)`);
}

/** Numeric business keys label a category; their magnitude is not a measure. */
export function isAnalystChartDimension(key: string): boolean {
  return /(?:^|_)client$/i.test(key)
    || /^(client|sap_client|client_id|mandt|vbeln|kunnr|kunag|lifnr|matnr|werks|bukrs|vkorg|vtweg|spart|belnr|posnr|ebelp|ebeln|fkdat|budat|gjahr|pernr|aubel|knumv)$/i.test(key)
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
