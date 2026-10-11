/** Adapt the plot to its actual card width, including split-screen tablets. */
export function analystChartLayout(width: number) {
  const compact = width < 520;
  return {
    compact,
    height: compact ? 280 : 340,
    visibleCategories: Math.max(3, Math.min(16, Math.floor((width - 80) / 58))),
    categoryAxisWidth: Math.max(84, Math.min(180, Math.round(width * 0.28))),
    numericAxisWidth: compact ? 62 : 80,
    labelCharacters: compact ? 11 : 22,
    donutRadius: Math.max(60, Math.min(116, Math.floor((width - 72) / 2))),
  };
}

export function compactChartNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  return new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(value);
}

export function shortenChartLabel(value: unknown, maxCharacters: number): string {
  const text = String(value ?? '');
  return text.length > maxCharacters ? text.slice(0, maxCharacters - 1) + '…' : text;
}

/** Export the underlying values rather than their rounded chart labels. */
export function analystChartCsv(rows: Record<string, unknown>[]): string {
  if (!rows.length) return '';
  const columns = Array.from(new Set(rows.flatMap(row => Object.keys(row))));
  const cell = (value: unknown) => {
    let text = value == null ? '' : String(value);
    if (typeof value === 'string' && /^[\s]*[=+@-]/.test(text) && !/^[+-]?\d+(?:\.\d+)?$/.test(text)) text = "'" + text;
    return /[",\r\n]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
  };
  return '\uFEFF' + [columns.map(cell).join(','), ...rows.map(row => columns.map(key => cell(row[key])).join(','))].join('\r\n');
}
