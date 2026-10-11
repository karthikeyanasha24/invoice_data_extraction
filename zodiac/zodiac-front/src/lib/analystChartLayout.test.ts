import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { analystChartLayout, analystChartCsv, compactChartNumber, shortenChartLabel } from './analystChartLayout.ts';

test('narrow cards leave plot space for labels and a usable donut', () => {
  const mobile = analystChartLayout(260);
  const wide = analystChartLayout(1100);
  assert.ok(mobile.numericAxisWidth + mobile.categoryAxisWidth < 260);
  assert.ok(mobile.donutRadius * 2 + 72 <= 260);
  assert.ok(mobile.visibleCategories < wide.visibleCategories);
  assert.equal(mobile.compact, true);
  assert.equal(wide.compact, false);
});
test('axis labels abbreviate signed values while full data stays untouched', () => {
  assert.equal(compactChartNumber(269020038.92), '269M');
  assert.equal(compactChartNumber(-1210000), '-1.2M');
  assert.equal(compactChartNumber(0), '0');
  assert.equal(compactChartNumber(NaN), '—');
  assert.equal(shortenChartLabel('Long customer description', 11), 'Long custo…');
});
test('CSV preserves precise values and currencies, quotes text, and includes sparse columns', () => {
  const rows = [{ customer: 'A, "B"', sales: -12345.67, currency: 'USD' }, { customer: '=1+1', note: 'Two\nlines' }];
  const csv = analystChartCsv(rows);
  assert.ok(csv.includes('"A, ""B""",-12345.67,USD,'));
  assert.ok(csv.includes("'=1+1"));
  assert.ok(csv.includes('"Two\nlines"'));
  assert.ok(csv.startsWith('\uFEFFcustomer,sales,currency,note'));
  assert.equal(rows[1].customer, '=1+1');
  assert.equal(analystChartCsv([{ revenue: '-12345.67' }]), '\uFEFFrevenue\r\n-12345.67');
});
