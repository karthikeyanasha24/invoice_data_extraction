/** Database numbers use a canonical decimal point. Ambiguous locale text is not guessed. */
export function analystNumeric(value: unknown): number {
  if (typeof value === 'number') return Number.isFinite(value) ? value : NaN;
  if (typeof value !== 'string' || !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$/.test(value.trim())) return NaN;
  return Number(value);
}

/** Exact string/BigInt rounding for display; never convert money through Number. */
export function analystDecimal(value: unknown, precision?: number): string {
  const raw = String(value ?? '').trim();
  const match = /^([+-]?)(\d+)(?:\.(\d*))?$/.exec(raw);
  if (!match) return value == null ? '—' : raw;
  let sign = match[1] === '-' ? '-' : '';
  let whole = match[2].replace(/^0+(?=\d)/, '');
  let fraction = match[3] || '';
  if (precision != null) {
    const digits = Math.max(0, Math.min(precision, 20));
    const rounded = BigInt(whole + fraction.padEnd(digits, '0').slice(0, digits)) + BigInt(Number(fraction[digits] || 0) >= 5 ? 1 : 0);
    const text = rounded.toString().padStart(digits + 1, '0');
    whole = digits ? text.slice(0, -digits) : text;
    fraction = digits ? text.slice(-digits) : '';
    if (rounded === BigInt(0)) sign = '';
  }
  return sign + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction ? '.' + fraction : '');
}

export function matchingResultRow(rows: Record<string, unknown>[], point: Record<string, unknown>): number | null {
  const keys = Object.keys(point).filter(k => !k.startsWith('__') && rows.some(r => k in r));
  if (!keys.length) return null;
  const matches = rows.map((row, i) => ({row, i})).filter(({row}) => keys.every(k => String(row[k] ?? '') === String(point[k] ?? '')));
  return matches.length === 1 ? matches[0].i : null;
}
