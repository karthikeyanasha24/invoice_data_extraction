import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { loadSavedAnalyses, saveAnalysis, removeSavedAnalysis } from './savedAnalyses.ts';

describe('savedAnalyses', () => {
  beforeEach(() => {
    const store: Record<string, string> = {};
    // @ts-expect-error test stub
    globalThis.localStorage = {
      getItem: (k: string) => store[k] ?? null,
      setItem: (k: string, v: string) => { store[k] = v; },
      removeItem: (k: string) => { delete store[k]; },
    };
    // @ts-expect-error jsdom-less
    globalThis.window = globalThis;
  });

  it('saves and reloads an analysis without dropping the question', () => {
    saveAnalysis({ question: 'Show inventory.', summary: 'Snapshot', intent: 'inventory_analysis', rowCount: 30 });
    const loaded = loadSavedAnalyses();
    assert.equal(loaded.length, 1);
    assert.equal(loaded[0].question, 'Show inventory.');
    assert.equal(loaded[0].intent, 'inventory_analysis');
  });

  it('removes by id', () => {
    const list = saveAnalysis({ question: 'Show inventory.', summary: 'Snapshot' });
    const after = removeSavedAnalysis(list[0].id);
    assert.equal(after.length, 0);
  });
});
