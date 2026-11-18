import assert from 'node:assert/strict';
import test from 'node:test';
import {
  buildRestrictionFilters,
  buildSuggestedRestrictionSql,
  detectRestrictionProfile,
  restrictionQuestionHint,
  selectedHasFactTable,
  validateRestrictionDraft,
} from './queryRestrictionBuilder.ts';

test('detects billing, sales order, and customer profiles from selected tables', () => {
  assert.equal(detectRestrictionProfile(['VBRK', 'VBRP']).id, 'billing');
  assert.equal(detectRestrictionProfile(['vbap']).id, 'sales_order');
  assert.equal(detectRestrictionProfile(['KNA1']).id, 'customer');
  assert.equal(detectRestrictionProfile(['T001']).id, 'generic');
  assert.equal(selectedHasFactTable(['VBRK']), true);
  assert.equal(selectedHasFactTable(['KNA1']), false);
});

test('year restriction for all billing documents builds date and client filters', () => {
  const profile = detectRestrictionProfile(['VBRK']);
  const draft = {
    mode: 'all' as const,
    period: 'year' as const,
    year: '2000',
    yearTo: '2005',
    specificValue: '',
    entityValue: '',
    client: '800',
    allowUnrestricted: false,
  };
  assert.equal(validateRestrictionDraft(profile, draft), null);
  const filters = buildRestrictionFilters(profile, draft);
  assert.deepEqual(
    filters.map(item => [item.column, item.operator, item.value, item.upper]),
    [
      ['mandt', 'include_value', '800', ''],
      ['fkdat', 'include_range', '2000-01-01', '2000-12-31'],
    ],
  );
  const sql = buildSuggestedRestrictionSql(profile, draft, ['vbeln', 'fkdat', 'kunag', 'waerk', 'netwr', 'mandt']);
  assert.match(sql, /FROM VBRK k/i);
  assert.match(sql, /k\.fkdat >= '20000101'/);
  assert.match(sql, /k\.fkdat < '20010101'/);
  assert.match(sql, /k\.mandt = '800'/);
  assert.match(restrictionQuestionHint(profile, draft), /calendar year 2000/i);
});

test('specific invoice mode requires a document value and rejects blank wildcards', () => {
  const profile = detectRestrictionProfile(['VBRK']);
  const blank = {
    mode: 'specific' as const,
    period: 'none' as const,
    year: '',
    yearTo: '',
    specificValue: '',
    entityValue: '',
    client: '',
    allowUnrestricted: false,
  };
  assert.match(String(validateRestrictionDraft(profile, blank)), /Enter the/i);
  const draft = { ...blank, specificValue: '0090000123' };
  assert.equal(validateRestrictionDraft(profile, draft), null);
  const filters = buildRestrictionFilters(profile, draft);
  assert.equal(filters[0]?.column, 'vbeln');
  assert.equal(filters[0]?.value, '0090000123');
});

test('all-years confirmation is required for unrestricted all-document mode', () => {
  const profile = detectRestrictionProfile(['VBAK']);
  const draft = {
    mode: 'all' as const,
    period: 'none' as const,
    year: '',
    yearTo: '',
    specificValue: '',
    entityValue: '',
    client: '',
    allowUnrestricted: false,
  };
  assert.match(String(validateRestrictionDraft(profile, draft)), /Wildcard scans are blocked/i);
  assert.equal(validateRestrictionDraft(profile, { ...draft, allowUnrestricted: true }), null);
});
