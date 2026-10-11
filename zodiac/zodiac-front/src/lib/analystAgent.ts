export type AgentResultSet = {
  id: string;
  kind: string;
  rows: any[];
  row_count: number;
  purpose?: string;
  sql?: string;
  truncated?: boolean;
};

export type AgentStep = { tool: string; status: string; elapsed_ms?: number; error?: string; error_type?: string; purpose?: string };

export function agentStepFeedback(step: AgentStep): string | null {
  if (step.status !== 'error' || step.error_type !== 'ValueError') return null;
  const message = step.error || '';
  return /^(Query validation:|Result validation:|SQL analytical validation failed:)/.test(message) ? message.slice(0, 800) : null;
}

const TOOL_LABELS: Record<string, string> = {
  list_tables: 'Inspected the database catalog',
  search_schema: 'Found relevant tables and fields',
  describe_tables: 'Checked columns and relationships',
  run_readonly_sql: 'Queried and checked the data',
  calculate: 'Calculated the result',
};

export function agentStepLabel(step: AgentStep): string {
  const label = TOOL_LABELS[step.tool] || 'Used a tool';
  return step.status === 'error' ? `${label} — needed another attempt`
    : step.status === 'stopped' ? `${label} — stopped`
    : step.status === 'cached' ? `${label} — reused this turn's result` : label;
}

export function additionalAgentResults(result: {
  answer_status?: string;
  agent_results?: AgentResultSet[];
  agent_primary_result_id?: string;
  query_plan?: { agent_results?: AgentResultSet[]; agent_primary_result_id?: string };
}): AgentResultSet[] {
  if (!String(result.answer_status || '').startsWith('SUCCESS')) return [];
  const sets = result.agent_results || result.query_plan?.agent_results || [];
  const primary = result.agent_primary_result_id || result.query_plan?.agent_primary_result_id;
  return sets.filter(set => set.id !== primary && set.rows?.length > 0);
}
