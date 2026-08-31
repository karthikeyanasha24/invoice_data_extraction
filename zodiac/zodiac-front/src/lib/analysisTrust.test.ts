import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  analysisTrustFromResult,
  analysisLabelFor,
  humanizePublicSummary,
  humanizeDataGapMessage,
  dataGapTryInstead,
  DATA_GAP_TRY_INSTEAD,
  summaryHasDeveloperHeading,
} from './analysisTrust.ts';

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
    assert.ok(trust.source?.toLowerCase().includes('inventory'));
    assert.equal(trust.grain?.toLowerCase().includes('snapshot') || trust.grain?.toLowerCase().includes('valuation'), true);
    assert.equal(trust.analysisLabel, 'Inventory position');
    assert.ok(!/p&l/i.test(trust.source || ''));
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
    assert.ok(!/billing revenue/i.test(trust.source || '') || /not billing/i.test(trust.source || ''));
    assert.ok(trust.calculation?.toLowerCase().includes('percentage'));
    assert.ok(trust.aggregation?.toLowerCase().includes('supplier'));
    assert.ok(trust.grain?.toLowerCase().includes('po') || trust.grain?.toLowerCase().includes('purchas'));
    assert.ok(trust.rowLimit?.startsWith('3 row'));
    assert.ok(!trust.source?.includes('supplier_concentration'));
  });

  it('does not describe billing as inventory or PO as revenue', () => {
    const revenue = analysisTrustFromResult({
      rowCount: 10,
      query_plan: { intent: 'product_profitability', analytical_context: { intent: 'product_profitability' } },
    });
    assert.equal(revenue.analysisLabel, 'Revenue performance');
    assert.ok(trustIncludesBilling(revenue.calculation));
    assert.ok(!/inventory|SALK3/i.test(revenue.calculation || ''));

    const sales = analysisTrustFromResult({
      query_plan: { intent: 'product_growth_decline', analytical_context: { intent: 'product_growth_decline' } },
    });
    assert.equal(sales.analysisLabel, 'Sales performance');
    assert.ok(trustIncludesBilling(sales.calculation));

    const listing = analysisTrustFromResult({
      query_plan: { intent: 'suppliers_of_selection', analytical_context: { intent: 'suppliers_of_selection' } },
    });
    assert.equal(listing.analysisLabel, 'Suppliers for the selected products');
    assert.ok(/purchase/i.test(listing.source || ''));
    assert.ok(!/share of po|percentage of total/i.test(listing.calculation || ''));
  });

  it('sales-order provenance is not billed invoices', () => {
    const trust = analysisTrustFromResult({
      rowCount: 5,
      query_plan: {
        intent: 'sales_order_analysis',
        domain: 'sales',
        analytical_context: {
          intent: 'sales_order_analysis',
          domain: 'sales',
          metric: 'sales_order_value',
          tables: ['VBAK', 'VBAP'],
          joins: ['VBAK.vbeln = VBAP.vbeln'],
          fact_grain: 'sales document item, then customer',
          aggregation: 'SUM(VBAP.NETWR); N:1 customer master only',
          period_label: '2004',
        },
      },
    });
    assert.equal(trust.analysisLabel, 'Sales orders');
    assert.equal(trust.domain, 'sales');
    assert.ok(trust.tables?.includes('VBAK'));
    assert.ok(/sales order/i.test(trust.source || ''));
    assert.ok(!/billed invoices/i.test(trust.source || '') || /not billed/i.test(trust.source || ''));
    assert.ok(/VBAP\.NETWR/i.test(trust.calculation || ''));
  });

  it('DATA GAP trust does not claim a P&L or invent a metric', () => {
    const trust = analysisTrustFromResult({
      answer_status: 'CANNOT_ANSWER',
      summary: 'Net profit is not in this extract.',
      query_plan: { data_gap: true, intent: 'net_profit_gap' },
      meta: { data_gap: true, reason: 'Operating costs are not linked at product grain.' },
    });
    assert.equal(trust.analysisLabel, 'Data limitation');
    assert.ok(!/p&l/i.test(`${trust.source} ${trust.calculation}`));
    assert.ok(!/Revenue = billing/i.test(trust.calculation || ''));
    assert.ok(/not calculated|not in this extract/i.test(trust.calculation || ''));
    assert.ok(trust.limitations.length > 0);
  });
});

function trustIncludesBilling(calc?: string) {
  return /NETWR/.test(calc || '') && /WAVWR/.test(calc || '');
}

describe('humanizePublicSummary', () => {
  it('replaces backtick restored headings used by stored chat history', () => {
    const restored = '**Deep analysis** — intent `inventory_analysis`\n\nMetrics use governed definitions.';
    const out = humanizePublicSummary(restored, 'inventory_analysis');
    assert.equal(summaryHasDeveloperHeading(out), false);
    assert.match(out, /Inventory position/);
    assert.doesNotMatch(out, /inventory_analysis/);
    assert.doesNotMatch(out, /Deep analysis/i);
  });

  it('replaces restored Deep analysis headings with business titles', () => {
    const restored = '**Deep analysis — intent product_profitability**\n\nMetrics use governed definitions.';
    const out = humanizePublicSummary(restored, 'product_profitability');
    assert.equal(summaryHasDeveloperHeading(out), false);
    assert.match(out, /Revenue performance/);
    assert.doesNotMatch(out, /product_profitability/);
    assert.doesNotMatch(out, /Deep analysis/i);
  });

  it('humanizes follow-up, concentration, inventory, and yoy restored headings', () => {
    const cases: [string, string, string][] = [
      ['Deep analysis — intent inventory_analysis', 'inventory_analysis', 'Inventory position'],
      ['Deep analysis – intent inventory_analysis', 'inventory_analysis', 'Inventory position'],
      ['Deep analysis - intent inventory_analysis', 'inventory_analysis', 'Inventory position'],
      ['Deep analysis — intent inventory_risk_analysis', 'inventory_risk_analysis', 'High inventory with low sales'],
      ['Deep analysis — intent supplier_concentration', 'supplier_concentration', 'Supplier concentration'],
      ['Deep analysis — intent customers_of_selection', 'customers_of_selection', 'Customer analysis'],
      ['Deep analysis — intent country_breakdown', 'country_breakdown', 'Regional performance'],
      ['Deep analysis — intent period_compare_selection', 'period_compare_selection', 'Year-over-year comparison'],
      ['### suppliers_of_selection', 'suppliers_of_selection', 'Suppliers for the selected products'],
    ];
    for (const [text, intent, label] of cases) {
      const out = humanizePublicSummary(text, intent);
      assert.equal(out.includes(label), true, `${intent} → ${out}`);
      assert.equal(summaryHasDeveloperHeading(out), false, out);
    }
  });

  it('maps every common intent slug to a heading without underscores', () => {
    for (const slug of [
      'product_profitability',
      'inventory_analysis',
      'product_growth_decline',
      'supplier_concentration',
      'suppliers_of_selection',
      'customers_of_selection',
      'country_breakdown',
      'inventory_by_plant',
      'period_compare_selection',
    ]) {
      const label = analysisLabelFor(slug);
      assert.ok(label);
      assert.equal(label!.includes('_'), false);
    }
  });
});

describe('humanizeDataGapMessage', () => {
  it('removes linked-dataset jargon', () => {
    const raw = 'I cannot accurately answer «Show inventory aging.» with the currently linked datasets.\n\n**Why:** True inventory aging requires MSEG.';
    const out = humanizeDataGapMessage(raw);
    assert.match(out, /does not support/);
    assert.doesNotMatch(out, /linked datasets/i);
    assert.doesNotMatch(out, /\bMSEG\b/);
  });
});

describe('DATA_GAP_TRY_INSTEAD', () => {
  it('does not suggest inventory aging', () => {
    assert.equal(DATA_GAP_TRY_INSTEAD.some((x) => /aging/i.test(x.question)), false);
  });

  it('suggests governed profit questions for net-profit gaps', () => {
    const chips = dataGapTryInstead('Net profit is not in this extract.');
    assert.equal(chips.some((x) => /highest profits|monthly revenue/i.test(x.question)), true);
    assert.equal(chips.some((x) => /aging/i.test(x.question)), false);
  });

  it('suggests inventory alternatives for aging gaps, not net profit', () => {
    const chips = dataGapTryInstead('Inventory aging requires inventory movement history.');
    assert.equal(chips.some((x) => /inventory/i.test(x.question)), true);
    assert.equal(chips.some((x) => /net profit/i.test(x.question)), false);
  });
});
