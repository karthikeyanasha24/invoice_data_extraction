export type AnalystProgress = {
  request_id?: string;
  pipeline_stage?: string;
  elapsed_s?: number;
  stage_elapsed_s?: number;
  remaining_s?: number;
  cancelled?: boolean;
  timeout?: boolean;
  status?: string;
  stages?: { pipeline_stage: string; elapsed_s: number }[];
};

export const ANALYST_STAGE_LABELS: Record<string, string> = {
  UNDERSTANDING: 'Understanding your question',
  RETRIEVING_SCHEMA: 'Finding relevant data',
  SELECTING_TABLES: 'Finding the right tables',
  SELECTING_COLUMNS: 'Checking available fields and joins',
  BUILDING_PLAN: 'Building the analysis plan',
  VALIDATING_PLAN: 'Checking the plan',
  GENERATING_SQL: 'Preparing the database query',
  VALIDATING_SQL: 'Checking the query',
  EXECUTING: 'Reading the database',
  REPAIRING: 'Adjusting the query',
  VALIDATING_RESULT: 'Verifying the results',
  PREPARING_ANSWER: 'Writing your answer',
  COMPLETED: 'Finishing your answer',
  TIMEOUT: 'Time limit reached',
  FAILED: 'Analysis could not be completed',
  CANCELLING: 'Stopping the analysis',
  CANCELLED: 'Cancelled',
};

export function mergeAnalystProgress(previous: AnalystProgress, incoming: AnalystProgress): AnalystProgress {
  // Missing registrations or a temporary polling failure must not erase progress.
  if (incoming.status === 'unknown' || !incoming.pipeline_stage) return previous;
  if ((incoming.elapsed_s ?? 0) < (previous.elapsed_s ?? 0)) return previous;
  return { ...previous, ...incoming };
}
