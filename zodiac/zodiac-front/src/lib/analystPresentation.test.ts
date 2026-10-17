import test from 'node:test';
import assert from 'node:assert/strict';
import { analystAnswerText, analystDateCell, comparisonColumnLabel, comparisonYears, defaultAnalystChartType, isAnalystDateColumn, isComparisonMeasure, isAnalystChartDimension, isAnalystChartDate, labelComparisonText } from './analystPresentation.ts';

test('detailed answers survive alongside their concise overview', () => {
  const answer = ('# Findings\n\n' + 'Explain evidence and its limitations. '.repeat(200)).trim();
  assert.equal(analystAnswerText({ summary: 'Three rows.', answer }), answer);
  assert.equal(analystAnswerText({ summary: 'Older saved answer.' }), 'Older saved answer.');
});

test('comparison amounts cannot become date axes', () => {
  for (const key of ['period_a', 'period_b', 'comparison_period_amount', 'sales_2015']) {
    assert.equal(isComparisonMeasure(key), true);
  }
  for (const key of ['year', 'billing_date', 'period_label', 'month']) {
    assert.equal(isComparisonMeasure(key), false);
  }
});

test('two-year comparisons identify each returned period without changing its raw key', () => {
  const question = 'compare billed sales in 2001 and 2002 (DEM)';
  assert.deepEqual(comparisonYears(question), ['2001', '2002']);
  assert.equal(comparisonColumnLabel('period_a', question), '2001 (period A)');
  assert.equal(comparisonColumnLabel('period_b', question), '2002 (period B)');
  assert.equal(comparisonColumnLabel('change', question), 'Change (2002 − 2001)');
  assert.equal(labelComparisonText('period a, period b by currency', question),
    '2001 (period A), 2002 (period B) by currency');
  assert.equal(comparisonColumnLabel('period_a', 'billed sales by year'), 'period a');
});

test('SAP date aliases render YYYYMMDD as dates instead of grouped numbers', () => {
  for (const key of ['billing date', 'billing_date', 'FKDAT']) {
    assert.equal(isAnalystDateColumn(key), true);
    assert.equal(analystDateCell(key, '19990226'), '26 Feb 1999');
  }
  assert.equal(analystDateCell('invoice_number', '0099010736'), null);
  assert.equal(analystDateCell('billing date', '19990231'), '19990231');
});

test('client codes label charts while four-digit counts remain measures', () => {
  for (const key of ['client', 'sap_client', 'mandt', 'customer_id']) assert.equal(isAnalystChartDimension(key), true);
  for (const key of ['billing_document_count', 'netwr', 'billed_sales']) {
    assert.equal(isAnalystChartDimension(key), false);
    assert.equal(isAnalystChartDate(key, '5074'), false);
    assert.equal(isAnalystChartDate(key, 2000), false);
  }
  assert.equal(isAnalystChartDate('calendar_year', 2000), true);
  assert.equal(isAnalystChartDate('billing_date', '2000-01-01'), true);
});

test('category comparison respects server chart type even when line toggle is available', () => {
  assert.equal(defaultAnalystChartType('bar', ['bar', 'line', 'area', 'table']), 'bar');
  assert.equal(defaultAnalystChartType('line', ['bar', 'line', 'table']), 'line');
});


import { analystChartCurrency, defaultAnalystCurrency } from './analystPresentation.ts';

test('currency selection keeps historical series separate and defaults to the broadest coverage', () => {
  const charts = [
    { title: 'Monthly revenue (PTE)', data: [{currency:'PTE', month:'199506', total_sales:10}] },
    { title: 'Monthly revenue (EUR)', data: [{currency:'EUR', month:'202401', total_sales:20}, {currency:'EUR', month:'202402', total_sales:30}] },
  ];
  assert.equal(defaultAnalystCurrency(charts), 'EUR');
  assert.equal(analystChartCurrency(charts[0]), 'PTE');
  assert.equal(analystChartCurrency({title:'Sales (USD)', data:[]}), 'USD');
  assert.equal(analystChartCurrency({title:'Customer counts', data:[{customer:'A', count:4}]}), 'Other');
  assert.equal(charts.reduce((n, chart) => n + chart.data.length, 0), 3);
});
