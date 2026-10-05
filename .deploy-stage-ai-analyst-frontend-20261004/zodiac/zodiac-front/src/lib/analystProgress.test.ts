import { it } from 'node:test';
import assert from 'node:assert/strict';
import { mergeAnalystProgress } from './analystProgress.ts';

it('temporary polling errors do not reset the displayed stage', () => {
  const previous = { pipeline_stage: 'EXECUTING', elapsed_s: 32 };
  assert.equal(mergeAnalystProgress(previous, { status: 'unknown', pipeline_stage: 'UNDERSTANDING' }), previous);
});

it('older responses cannot overwrite more recent progress', () => {
  const previous = { pipeline_stage: 'PREPARING_ANSWER', elapsed_s: 40 };
  assert.equal(mergeAnalystProgress(previous, { pipeline_stage: 'EXECUTING', elapsed_s: 32 }), previous);
});

it('real repair transitions and stage history remain visible', () => {
  const progress = mergeAnalystProgress({ pipeline_stage: 'EXECUTING', elapsed_s: 32 }, {
    pipeline_stage: 'REPAIRING', elapsed_s: 34, stages: [{ pipeline_stage: 'EXECUTING', elapsed_s: 32 }],
  });
  assert.equal(progress.pipeline_stage, 'REPAIRING');
  assert.equal(progress.stages?.length, 1);
});
