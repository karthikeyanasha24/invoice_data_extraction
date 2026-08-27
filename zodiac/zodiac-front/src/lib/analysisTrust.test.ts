import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { analysisTrustFromResult, DATA_GAP_TRY_INSTEAD } from './analysisTrust.ts';

describe('analysisTrustFromResult', () => {
  it('reads intent and gaps from analytical_context without exposing SQL', () => {
    const trust = analysisTrustFromResult({
      sql: 'SELECT * FROM MBEW',
      query_plan: {
        intent: 'inventory_analysis',
        analytical_context: {
          intent: 'inventory_analysis',
          metric: 'stock_value',
          period_label: 'Current snapshot',
          data_gaps: ['No historical inventory movements'],
        },
      },
    });
    assert.equal(trust.intent, 'inventory_analysis');
    assert.equal(trust.metric, 'stock_value');
    assert.equal(trust.period, 'Current snapshot');
    assert.ok(trust.calculation?.includes('NETWR'));
    assert.equal(trust.limitations[0], 'No historical inventory movements');
    assert.ok(trust.source?.includes('inventory snapshot'));
  });
});

describe('DATA_GAP_TRY_INSTEAD', () => {
  it('does not suggest inventory aging', () => {
    assert.equal(DATA_GAP_TRY_INSTEAD.some((x) => /aging/i.test(x.question)), false);
  });
});
