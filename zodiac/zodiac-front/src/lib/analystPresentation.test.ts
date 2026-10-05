import test from 'node:test';
import assert from 'node:assert/strict';
import { analystAnswerText, defaultAnalystChartType, isComparisonMeasure } from './analystPresentation.ts';

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

test('category comparison respects server chart type even when line toggle is available', () => {
  assert.equal(defaultAnalystChartType('bar', ['bar', 'line', 'area', 'table']), 'bar');
  assert.equal(defaultAnalystChartType('line', ['bar', 'line', 'table']), 'line');
});
