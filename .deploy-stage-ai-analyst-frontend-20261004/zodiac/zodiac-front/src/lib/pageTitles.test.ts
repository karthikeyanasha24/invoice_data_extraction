import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { documentTitleForPath } from './pageTitles.ts';

describe('documentTitleForPath', () => {
  it('uses business titles and does not treat AI Analyst as EDI operations', () => {
    assert.equal(documentTitleForPath('/dashboard/ai'), 'AI Analyst · BridgeEDI');
    assert.equal(documentTitleForPath('/dashboard'), 'EDI operations · BridgeEDI');
    assert.equal(documentTitleForPath('/overview'), 'Overview · BridgeEDI');
    assert.equal(documentTitleForPath('/sat-documents'), 'SAT documents · BridgeEDI');
    assert.equal(documentTitleForPath('/settings'), 'Settings · BridgeEDI');
    assert.equal(documentTitleForPath('/'), 'Login · BridgeEDI');
  });
});
