import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  ADAPTIVE_CONTEXT_POLICY,
  buildFollowupContextData,
  followupContextForSend,
  lastSuccessfulAnalyticalContext,
  latestAssistantContext,
  updateLastSuccessfulAnalyticalContext,
  type AdaptiveChatMessage,
  type LastSuccessfulAnalyticalContext,
} from './adaptiveChatContext.ts';

const SQL_2004 = 'SELECT customer_name, industry, SUM(netwr) AS total_sales FROM "VBRK" WHERE SUBSTRING(fkdat,1,4) IN (\'2004\') GROUP BY 1,2 ORDER BY total_sales DESC LIMIT 10';

const SUCCESS_2004 = {
  sql: SQL_2004,
  data: [{ customer_name: 'Motomarkt Stuttgart GmbH', total_sales: 6099225, currency: 'EUR' }],
  query_plan: { metric: 'sum', filters: { years: ['2004'] }, dimensions: ['customer', 'industry'] },
  answer_status: 'SUCCESS',
};

const GENERAL_CAPABILITY = {
  sql: '',
  data: [],
  mode: 'general_chat',
  query_plan: { last_mode: 'general_chat', investigation_state: { mode: 'general_chat', last_summary: 'I can help with analytics.' } },
  answer_status: 'SUCCESS',
};

const CLARIFICATION = {
  sql: '',
  data: [],
  answer_status: 'CLARIFICATION',
};

describe('continuous chat context policy', () => {
  it('exposes continuous_chat_v1 marker', () => {
    assert.equal(ADAPTIVE_CONTEXT_POLICY, 'continuous_chat_v1');
  });

  it('after capability answer, follow-up uses general chat — not stale analytics', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show highest sales for 2004' },
      { role: 'assistant', content: 'Motomarkt', result: SUCCESS_2004 },
      { role: 'user', content: 'What can you answer?' },
      { role: 'assistant', content: 'I can help with analytics.', result: GENERAL_CAPABILITY },
    ];
    const analytical = lastSuccessfulAnalyticalContext(messages);
    assert.equal(analytical?.previousQuestion, 'Show highest sales for 2004');

    const ctx = followupContextForSend(messages, analytical, false);
    assert.ok(ctx);
    assert.equal(ctx!.previousQuestion, 'What can you answer?');
    assert.equal(String(ctx!.previousAnswerStatus).toUpperCase(), 'SUCCESS');
    assert.equal((ctx!.previousPlan as { last_mode?: string })?.last_mode, 'general_chat');
  });

  it('latest assistant context prefers the most recent turn', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'What can you answer?' },
      { role: 'assistant', content: 'Capabilities…', result: GENERAL_CAPABILITY },
      { role: 'user', content: 'Is everything predefined?' },
      {
        role: 'assistant',
        content: 'No, I interpret each message.',
        result: {
          ...GENERAL_CAPABILITY,
          query_plan: { last_mode: 'general_chat', investigation_state: { mode: 'general_chat', last_summary: 'No, I interpret…' } },
        },
      },
    ];
    const latest = latestAssistantContext(messages);
    assert.equal(latest?.previousQuestion, 'Is everything predefined?');
  });

  it('typed continue never clears context when isNewQuestion is false', () => {
    const state: LastSuccessfulAnalyticalContext = {
      previousQuestion: 'What can you answer?',
      previousSQL: '',
      previousPlan: { last_mode: 'general_chat' },
      previousAnswerStatus: 'SUCCESS',
      data: [],
    };
    assert.ok(buildFollowupContextData(state, false));
    assert.equal(buildFollowupContextData(state, true), null);
  });

  it('new-question flag still clears context for overview deep-links', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'What can you answer?' },
      { role: 'assistant', content: 'Capabilities…', result: GENERAL_CAPABILITY },
    ];
    assert.equal(followupContextForSend(messages, null, true), null);
  });

  it('analytical ref still updates only on SQL success', () => {
    let state: LastSuccessfulAnalyticalContext | null = null;
    state = updateLastSuccessfulAnalyticalContext(state, 'Show highest sales for 2004', SUCCESS_2004);
    assert.match(state!.previousSQL, /2004/);
    state = updateLastSuccessfulAnalyticalContext(state, 'Meaning of life', CLARIFICATION);
    assert.match(state!.previousSQL, /2004/);
  });
});
