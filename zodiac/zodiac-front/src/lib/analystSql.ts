export type AnalystSqlFields = {
  sql?: string;
  attempted_sql?: string;
  source_sql?: string;
  sql_status?: string;
};

type SqlResponse = AnalystSqlFields & {
  generatedSql?: unknown;
  attemptedSql?: unknown;
  sourceSql?: unknown;
  sqlStatus?: unknown;
};

/** Preserve only SQL actually returned by the service, including failed attempts. */
export function analystSqlFields(response: SqlResponse): AnalystSqlFields {
  const text = (value: unknown): string | undefined =>
    typeof value === 'string' && value.trim() ? value.trim() : undefined;
  return {
    sql: text(response.sql) || text(response.generatedSql),
    attempted_sql: text(response.attempted_sql) || text(response.attemptedSql),
    source_sql: text(response.source_sql) || text(response.sourceSql),
    sql_status: text(response.sql_status) || text(response.sqlStatus),
  };
}

export function analystSqlEvidence(result: AnalystSqlFields & {
  answer_status?: string;
  failure_class?: string;
}): { sql: string; label: string; explanation: string } | null {
  const sql = result.sql?.trim() || result.attempted_sql?.trim();
  const status = String(result.sql_status || '').toLowerCase();
  const outcome = String(result.answer_status || '').toUpperCase();
  const failure = String(result.failure_class || '').toUpperCase();
  if (!sql) {
    const sourceSql = result.source_sql?.trim();
    if (sourceSql && outcome === 'SUCCESS') {
      return {
        sql: sourceSql,
        label: 'Source SQL · reused result',
        explanation: 'This query produced the prior validated rows. The follow-up was calculated from those rows; no new database query ran.',
      };
    }
    return null;
  }
  if (status === 'result_validation_failed' || failure === 'RESULT_VALIDATION_FAILED') {
    return { sql, label: 'Executed SQL · result not verified', explanation: 'The query ran, but its result did not pass verification. No verified answer was produced.' };
  }
  if (status === 'executed' || (!status && result.sql && ['SUCCESS', 'SUCCESS_EMPTY', 'NO_DATA'].includes(outcome))) {
    return { sql, label: 'Executed SQL', explanation: 'This query was used to read the database.' };
  }
  if (['execution_failed', 'failed'].includes(status)) {
    return { sql, label: 'SQL execution failed', explanation: 'This query was attempted, but it did not complete successfully.' };
  }
  if (['validation_failed', 'sql_validation_failed'].includes(status) || failure === 'SQL_VALIDATION_FAILED') {
    return { sql, label: 'SQL did not pass validation', explanation: 'This query did not pass validation and must not be treated as verified SQL.' };
  }
  if (['generated', 'not_executed'].includes(status)) {
    return { sql, label: 'Generated SQL · not executed', explanation: 'The service prepared this query but did not report executing it.' };
  }
  return { sql, label: 'SQL · execution unverified', explanation: 'The service returned this query without confirming successful execution.' };
}
