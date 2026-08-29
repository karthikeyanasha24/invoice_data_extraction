import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { publicApiError } from './apiErrors.ts';

describe('publicApiError', () => {
  it('maps 404 away from Axios wording', () => {
    const msg = publicApiError({ message: 'Request failed with status code 404', response: { status: 404 } });
    assert.match(msg, /temporarily unavailable/i);
    assert.doesNotMatch(msg, /axios|404/i);
  });

  it('maps 401 to session copy', () => {
    assert.match(publicApiError({ response: { status: 401 } }), /session expired/i);
  });

  it('never surfaces JWT or AxiosError wording', () => {
    assert.doesNotMatch(publicApiError({ message: 'JWT expired' }), /jwt/i);
    assert.doesNotMatch(publicApiError({ message: 'AxiosError: Request failed with status code 500', response: { status: 500 } }), /axios|500/i);
  });

  it('maps network failure', () => {
    assert.match(publicApiError({ code: 'ERR_NETWORK', message: 'Network Error' }), /could not reach/i);
  });
});
