import test from 'node:test';
import assert from 'node:assert/strict';
import { additionalAgentResults, agentStepLabel, agentStepFeedback } from './analystAgent.ts';

test('multiple tool results remain visible without repeating the primary table', () => {
  const sets = [
    { id: 'result_1', kind: 'analysis', rows: [{ count: 12 }], row_count: 1 },
    { id: 'result_2', kind: 'analysis', rows: [{ count: 5 }], row_count: 1 },
  ];
  assert.deepEqual(additionalAgentResults({answer_status:'SUCCESS', agent_results:sets, agent_primary_result_id:'result_2'}), [sets[0]]);
  assert.deepEqual(additionalAgentResults({answer_status:'SUCCESS', query_plan:{agent_results:sets, agent_primary_result_id:'result_2'}}), [sets[0]]);
  assert.deepEqual(additionalAgentResults({answer_status:'CANNOT_ANSWER', agent_results:sets}), []);
});

test('steps explain actions and recovery without displaying reasoning or arguments', () => {
  assert.equal(agentStepLabel({tool:'run_readonly_sql', status:'error'}), 'Queried and checked the data — needed another attempt');
  assert.equal(agentStepLabel({tool:'describe_tables', status:'completed'}), 'Checked columns and relationships');
  assert.equal(agentStepLabel({tool:'find_relationships', status:'completed'}), 'Verified the relationship path and document keys');
  assert.equal(agentStepLabel({tool:'prepare_analysis', status:'completed'}), 'Checked the requested fields and comparison plan');
  assert.equal(agentStepLabel({tool:'unknown_private_argument', status:'completed'}), 'Used a tool');
});

test('steps disclose bounded validation feedback without exposing database exception details', () => {
  assert.equal(agentStepFeedback({tool:'run_readonly_sql',status:'error',error_type:'ValueError',error:'Query validation: Missing column'}),'Query validation: Missing column');
  assert.equal(agentStepFeedback({tool:'run_readonly_sql',status:'error',error_type:'OperationalError',error:'connection string and private credentials'}),null);
  assert.equal(agentStepFeedback({tool:'run_readonly_sql',status:'completed',error_type:'ValueError',error:'Query validation: old error'}),null);
});
