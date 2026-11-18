import test from 'node:test';
import assert from 'node:assert/strict';
import { analystAnswerText, analystDateCell, businessColumnLabel, businessPresentationColumns, comparisonColumnLabel, comparisonYears, defaultAnalystChartType, isAnalystDateColumn, isComparisonMeasure, isAnalystChartDimension, isAnalystChartDate, isTechnicalProofColumn, labelComparisonText, projectBusinessRows } from './analystPresentation.ts';

test('business presentation hides proof columns and keeps Industry | Customer | Total Sales', () => {
  const question = 'show the lowest sales for the year 1999 by industry and customer';
  const columns = ['mandt', 'brtxt', 'name1', 'vbeln', 'total_sales', 'kunag'];
  assert.equal(isTechnicalProofColumn('mandt', question), true);
  assert.equal(isTechnicalProofColumn('vbeln', question), true);
  assert.deepEqual(businessPresentationColumns(question, columns), ['brtxt', 'name1', 'total_sales']);
  assert.equal(businessColumnLabel('brtxt', question), 'Industry');
  assert.equal(businessColumnLabel('name1', question), 'Customer');
  assert.equal(businessColumnLabel('total_sales', question), 'Total Sales');
  const projected = projectBusinessRows([
    { mandt: '800', brtxt: 'Retail', name1: 'Acme', vbeln: '0090001', total_sales: 12, kunag: '1000' },
  ], question, columns);
  assert.deepEqual(projected.columns, ['brtxt', 'name1', 'total_sales']);
  assert.deepEqual(projected.rows[0], { brtxt: 'Retail', name1: 'Acme', total_sales: 12 });
});

test('invoice listings still show document numbers while hiding client proof keys', () => {
  const question = 'list the invoices for customer 1000 in 2000';
  assert.equal(isTechnicalProofColumn('vbeln', question), false);
  assert.equal(isTechnicalProofColumn('mandt', question), true);
  assert.deepEqual(
    businessPresentationColumns(question, ['mandt', 'vbeln', 'fkdat', 'netwr']),
    ['vbeln', 'fkdat', 'netwr'],
  );
});

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
  for (const key of ['client', 'sap_client', 'mandt', 'customer_id', 'invoice_client', 'sales_order_client', 'order_item_client']) assert.equal(isAnalystChartDimension(key), true);
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
