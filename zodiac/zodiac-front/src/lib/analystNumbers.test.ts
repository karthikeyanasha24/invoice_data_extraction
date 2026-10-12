import test from 'node:test';
import assert from 'node:assert/strict';
import {analystNumeric, analystDecimal, matchingResultRow} from './analystNumbers.ts';
test('money strings keep exact digits and round without binary floating point', () => {
  assert.equal(analystDecimal('9007199254740993.015',2),'9,007,199,254,740,993.02');
  assert.equal(analystDecimal('-0.015',2),'-0.02');
  assert.equal(analystDecimal('4630639.01'),'4,630,639.01');
});
test('ambiguous locale inputs cannot produce conflicting chart/table amounts', () => {
  for (const value of ['1.234,56','1,234.56','1,234']) assert.ok(Number.isNaN(analystNumeric(value)));
  assert.equal(analystNumeric('1234.56'),1234.56);
});
test('chart selection cannot select a row by amount alone when duplicated', () => {
  const rows=[{year:'2001',currency:'USD',sales:'100'},{year:'2001',currency:'EUR',sales:'100'}];
  assert.equal(matchingResultRow(rows,{sales:'100'}),null);
  assert.equal(matchingResultRow(rows,{...rows[1]}),1);
});
