import { it } from 'node:test';
import assert from 'node:assert/strict';
import { analystSqlEvidence, analystSqlFields } from './analystSql.ts';

const sql = 'SELECT COUNT(*) FROM billing_documents';

it('preserves actual SQL from failed and timed out responses', () => {
  for (const answer_status of ['CANNOT_ANSWER', 'TIMEOUT']) {
    const fields = analystSqlFields({ attempted_sql: sql, sql_status: 'execution_failed' });
    const evidence = analystSqlEvidence({ ...fields, answer_status });
    assert.equal(evidence?.sql, sql);
    assert.equal(evidence?.label, 'SQL execution failed');
  }
});

it('distinguishes successful execution, validation failure, and unverified attempts', () => {
  assert.equal(analystSqlEvidence({ sql, answer_status: 'SUCCESS_EMPTY' })?.label, 'Executed SQL');
  assert.equal(analystSqlEvidence({ sql, sql_status: 'validation_failed' })?.label, 'SQL did not pass validation');
  assert.equal(analystSqlEvidence({ attempted_sql: sql, answer_status: 'CANNOT_ANSWER' })?.label, 'SQL · execution unverified');
});

it('does not mark generated SQL as executed when explicit status says otherwise', () => {
  assert.equal(analystSqlEvidence({ sql, sql_status: 'generated', answer_status: 'SUCCESS' })?.label, 'Generated SQL · not executed');
});

it('does not turn a rejected result into an executed and verified answer', () => {
  assert.equal(analystSqlEvidence({ sql, failure_class: 'RESULT_VALIDATION_FAILED', sql_status: 'executed' })?.label, 'Executed SQL · result not verified');
});

it('never fabricates SQL when the service did not return a query', () => {
  assert.equal(analystSqlEvidence({ answer_status: 'CANNOT_ANSWER' }), null);
  assert.equal(analystSqlFields({ generatedSql: { query: sql } }).sql, undefined);
});
