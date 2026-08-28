import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { humanizeFollowups } from './followupChips.ts';

describe('humanizeFollowups', () => {
  it('maps semantic labels to canonical questions', () => {
    const chips = humanizeFollowups([
      'Customer contribution for the current product/revenue set',
      'Country / region (LAND1) breakdown',
      'Vendors sourcing the current materials (PO grain, not invoice COGS)',
      'Stock value/qty snapshot (MBEW/MARD) vs sales activity',
    ]);
    assert.deepEqual(chips.map((c) => c.label), [
      'Show customers',
      'Break down by region',
      'Show suppliers',
      'Show inventory',
    ]);
    assert.equal(chips[1].question, 'Show their regions.');
  });

  it('does not remap concentration suggestions to supplier listing', () => {
    const chips = humanizeFollowups(['Supplier concentration by PO share']);
    assert.equal(chips[0].question, 'Show supplier concentration.');
  });

  it('keeps concentration follow-ups distinct from R3 supplier listing', () => {
    const chips = humanizeFollowups([
      'Show the highest supplier.',
      'Show the percentage.',
      'Show top 3.',
      'Which supplier is highest?',
    ]);
    assert.equal(chips.some((c) => c.question === 'Show their suppliers.'), false);
    assert.equal(chips[0].question, 'Show the highest supplier.');
    assert.equal(chips.some((c) => c.question === 'Show the percentage.'), true);
  });

  it('strips leftover SAP parentheticals', () => {
    const chips = humanizeFollowups(['Something custom (VBRK.FKDAT)']);
    assert.equal(chips[0].label, 'Something custom');
  });
});
