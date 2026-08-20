import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  ADAPTIVE_CONTEXT_POLICY,
  buildFollowupContextData,
  lastSuccessfulAnalyticalContext,
  updateLastSuccessfulAnalyticalContext,
  type AdaptiveChatMessage,
  type LastSuccessfulAnalyticalContext,
} from './adaptiveChatContext.ts';

const SQL_2004 = 'SELECT customer_name, industry, SUM(netwr) AS total_sales FROM "VBRK" WHERE SUBSTRING(fkdat,1,4) IN (\'2004\') GROUP BY 1,2 ORDER BY total_sales DESC LIMIT 10';
const SQL_2005 = 'SELECT TRIM(v."waerk") AS currency, SUM(netwr) AS total_sales FROM "VBRK" v WHERE SUBSTRING(fkdat,1,4) IN (\'2005\') GROUP BY 1';
const SQL_TOP5_2004 = 'SELECT customer_name, industry, SUM(netwr) AS total_sales FROM "VBRK" WHERE SUBSTRING(fkdat,1,4) IN (\'2004\') GROUP BY 1,2 ORDER BY total_sales DESC LIMIT 5';

const SUCCESS_2004 = {
  sql: SQL_2004,
  data: [{ customer_name: 'Motomarkt Stuttgart GmbH', total_sales: 6099225, currency: 'EUR' }],
  query_plan: { metric: 'sum', filters: { years: ['2004'] }, dimensions: ['customer', 'industry'] },
  answer_status: 'SUCCESS',
};

const SUCCESS_2005 = {
  sql: SQL_2005,
  data: [{ currency: 'EUR', total_sales: 50738595.82 }],
  query_plan: { metric: 'sum', filters: { years: ['2005'] } },
  answer_status: 'SUCCESS',
};

const SUCCESS_TOP5 = {
  sql: SQL_TOP5_2004,
  data: [{ customer_name: 'Motomarkt Stuttgart GmbH', total_sales: 6099225 }],
  query_plan: { metric: 'sum', filters: { years: ['2004'] }, limit: 5 },
  answer_status: 'SUCCESS',
};

const CLARIFICATION = {
  sql: '',
  data: [],
  answer_status: 'CLARIFICATION',
};

function requestPayload(question: string, state: LastSuccessfulAnalyticalContext | null, isNewQuestion = false) {
  return {
    question,
    contextData: buildFollowupContextData(state, isNewQuestion),
    policy: ADAPTIVE_CONTEXT_POLICY,
  };
}

function assertNotClarificationContext(payload: ReturnType<typeof requestPayload>) {
  const ctx = payload.contextData;
  assert.ok(ctx, 'follow-up must send last successful analytical context');
  assert.notEqual(ctx!.previousQuestion, 'Meaning of life');
  assert.notEqual(ctx!.previousSQL, '');
  assert.notEqual(String(ctx!.previousAnswerStatus).toUpperCase(), 'CLARIFICATION');
}

describe('last successful analytical context policy', () => {
  it('exposes a production bundle marker', () => {
    assert.equal(ADAPTIVE_CONTEXT_POLICY, 'last_successful_analytical_v1');
  });

  it('2004 success → Meaning of life → Top 5 uses 2004 state', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    const messages: AdaptiveChatMessage[] = [];

    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    messages.push(
      { role: 'user', content: 'Show highest sales for 2004' },
      { role: 'assistant', content: 'Motomarkt', result: SUCCESS_2004 },
    );
    assert.equal(state?.previousQuestion, 'Show highest sales for 2004');
    assert.equal(state?.previousAnswerStatus, 'SUCCESS');
    assert.match(state!.previousSQL, /2004/);

    state = updateLastSuccessfulAnalyticalContext(state, 'Meaning of life', CLARIFICATION);
    messages.push(
      { role: 'user', content: 'Meaning of life' },
      { role: 'assistant', content: 'Please rephrase', result: CLARIFICATION },
    );
    assert.equal(state?.previousQuestion, 'Show highest sales for 2004');
    assert.equal(lastSuccessfulAnalyticalContext(messages)?.previousQuestion, 'Show highest sales for 2004');

    const top5 = requestPayload('Top 5', state);
    assertNotClarificationContext(top5);
    assert.equal(top5.contextData?.previousQuestion, 'Show highest sales for 2004');
    assert.equal(top5.contextData?.previousSQL, SQL_2004);
    assert.equal(top5.contextData?.previousAnswerStatus, 'SUCCESS');
  });

  it('preserves 2004 state across other nonsense clarifications before Top 5', () => {
    const nonsense = [
      'Tell me a joke',
      "What's your favorite color?",
      "What's the weather?",
    ];
    for (const phrase of nonsense) {
      let state: LastSuccessfulAnalyticalContext | null = null;
      state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
      state = updateLastSuccessfulAnalyticalContext(state, phrase, CLARIFICATION);
      const top5 = requestPayload('Top 5', state);
      assertNotClarificationContext(top5);
      assert.equal(top5.contextData?.previousQuestion, 'Show highest sales for 2004');
      assert.match(top5.contextData!.previousSQL, /2004/);
    }
  });

  it('2004 → Meaning of life → 2005 replaces state, then Top 3 follows 2005', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    state = updateLastSuccessfulAnalyticalContext(state, 'Meaning of life', CLARIFICATION);
    assert.equal(state?.previousQuestion, 'Show highest sales for 2004');

    const sales2005 = requestPayload('Show sales for 2005', state);
    assert.equal(sales2005.contextData?.previousQuestion, 'Show highest sales for 2004');

    state = updateLastSuccessfulAnalyticalContext(state, 'Show sales for 2005', SUCCESS_2005);
    assert.equal(state?.previousQuestion, 'Show sales for 2005');
    assert.match(state!.previousSQL, /2005/);

    const top3 = requestPayload('Top 3', state);
    assert.equal(top3.contextData?.previousQuestion, 'Show sales for 2005');
    assert.equal(top3.contextData?.previousSQL, SQL_2005);
    assert.doesNotMatch(top3.contextData!.previousSQL, /2004/);
  });

  it('does not send context for an explicit new question, and success replaces state', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    const fresh = requestPayload('Show sales for 2005', state, true);
    assert.equal(fresh.contextData, null);

    state = updateLastSuccessfulAnalyticalContext(state, 'Show sales for 2005', SUCCESS_2005);
    const top3 = requestPayload('Top 3', state, false);
    assert.equal(top3.contextData?.previousQuestion, 'Show sales for 2005');
  });

  it('failed or empty SQL does not wipe a valid 2004 state', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    state = updateLastSuccessfulAnalyticalContext(state, 'broken', {
      sql: '',
      data: [],
      answer_status: 'ERROR',
    });
    state = updateLastSuccessfulAnalyticalContext(state, 'cannot', {
      sql: 'SELECT 1',
      data: [],
      answer_status: 'CANNOT_ANSWER',
    });
    assert.equal(state?.previousQuestion, 'Show highest sales for 2004');
    assert.equal(state?.previousSQL, SQL_2004);
  });

  it('follow-up success replaces the analytical state', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    state = updateLastSuccessfulAnalyticalContext(state, 'Top 5', SUCCESS_TOP5);
    assert.equal(state?.previousQuestion, 'Top 5');
    assert.match(state!.previousSQL, /LIMIT 5/);
  });

  it('history scan skips clarification even if it is the latest assistant turn', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show highest sales for 2004' },
      { role: 'assistant', content: 'Motomarkt', result: SUCCESS_2004 },
      { role: 'user', content: 'Meaning of life' },
      { role: 'assistant', content: 'Please rephrase', result: CLARIFICATION },
    ];
    const scanned = lastSuccessfulAnalyticalContext(messages);
    assert.equal(scanned?.previousQuestion, 'Show highest sales for 2004');
    assert.equal(scanned?.previousSQL, SQL_2004);
    assert.notEqual(scanned?.previousQuestion, 'Meaning of life');
  });
});
