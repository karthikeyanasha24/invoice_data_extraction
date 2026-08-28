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
    assert.ok(trust.calculation?.includes('SALK3'));
    assert.ok(!trust.calculation?.includes('NETWR'));
    assert.equal(trust.aggregation?.toLowerCase().includes('snapshot'), true);
    assert.equal(trust.period, 'Current snapshot');
    assert.equal(trust.limitations[0], 'No historical inventory movements');
    assert.ok(trust.source?.includes('inventory snapshot'));
    assert.equal(trust.grain?.toLowerCase().includes('snapshot') || trust.grain?.toLowerCase().includes('valuation'), true);
    assert.equal(trust.analysisLabel, 'Current inventory snapshot');
  });

  it('uses business headings and PO provenance for supplier concentration', () => {
    const trust = analysisTrustFromResult({
      rowCount: 3,
      query_plan: {
        intent: 'supplier_concentration',
        analytical_context: {
          intent: 'supplier_concentration',
          fact_grain: 'po_item',
          aggregation_grain: 'supplier',
          period_label: 'All purchase orders in the governed extract',
          data_gaps: ['Share of purchase-order value by supplier (EKPO.NETWR).'],
        },
      },
    });
    assert.equal(trust.analysisLabel, 'Supplier concentration');
    assert.equal(trust.analysisLabel?.includes('_'), false);
    assert.ok(trust.source?.toLowerCase().includes('purchase'));
    assert.ok(trust.calculation?.toLowerCase().includes('percentage'));
    assert.ok(trust.aggregation?.toLowerCase().includes('supplier'));
    assert.ok(trust.grain?.toLowerCase().includes('po') || trust.grain?.toLowerCase().includes('purchas'));
    assert.ok(trust.rowLimit?.startsWith('3 row'));
    assert.ok(!trust.source?.includes('supplier_concentration'));
  });
});

describe('DATA_GAP_TRY_INSTEAD', () => {
  it('does not suggest inventory aging', () => {
    assert.equal(DATA_GAP_TRY_INSTEAD.some((x) => /aging/i.test(x.question)), false);
  });

  it('suggests governed profit questions for net-profit gaps', async () => {
    const { dataGapTryInstead } = await import('./analysisTrust.ts');
    const chips = dataGapTryInstead('Net profit is not in this extract.');
    assert.equal(chips.some((x) => /highest profits/i.test(x.question)), true);
    assert.equal(chips.some((x) => /aging/i.test(x.question)), false);
  });
});
