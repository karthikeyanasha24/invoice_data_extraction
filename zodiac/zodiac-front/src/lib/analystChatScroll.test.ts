import { strict as assert } from 'node:assert';
import { test } from 'node:test';
import { analystScrollPosition } from './analystChatScroll.ts';

test('short conversations need no scroll controls', () => {
  assert.deepEqual(analystScrollPosition(0, 200, 500), { canGoUp: false, canGoDown: false, nearBottom: true });
});
test('reading older messages does not follow arriving replies', () => {
  assert.equal(analystScrollPosition(300, 1800, 500).nearBottom, false);
  assert.equal(analystScrollPosition(300, 2200, 500).nearBottom, false);
});
test('a reader near the latest answer follows it and can still jump to the bottom', () => {
  assert.deepEqual(analystScrollPosition(1250, 1800, 500), { canGoUp: true, canGoDown: true, nearBottom: true });
  assert.deepEqual(analystScrollPosition(1300, 1800, 500), { canGoUp: true, canGoDown: false, nearBottom: true });
});
test('overscroll is bounded for touch browsers', () => {
  assert.deepEqual(analystScrollPosition(-20, 1800, 500), { canGoUp: false, canGoDown: true, nearBottom: false });
  assert.equal(analystScrollPosition(1400, 1800, 500).canGoDown, false);
});
