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
  it('a narrative-only reply retains its own context', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show sales for 2004' },
      { role: 'assistant', content: 'Sales results', result: SUCCESS_2004 },
      { role: 'user', content: 'Call me Mira' },
      { role: 'assistant', content: 'Of course, Mira.' },
    ];
    const context = followupContextForSend(messages, lastSuccessfulAnalyticalContext(messages), false);
    assert.equal(context?.previousQuestion, 'Call me Mira');
    assert.equal(context?.previousSQL, '');
  });
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

  it('a clarification keeps the last verified analytical result available for the next turn', () => {
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show sales for 2004' },
      { role: 'assistant', content: 'Sales results', result: SUCCESS_2004 },
      { role: 'user', content: 'Show monthly sales for the selected customer.' },
      {
        role: 'assistant',
        content: 'Please specify the customer.',
        result: { ...CLARIFICATION, query_plan: { awaiting: 'customer' } },
      },
    ];
    const context = followupContextForSend(
      messages,
      lastSuccessfulAnalyticalContext(messages),
      false,
    );
    const plan = context?.previousPlan as {
      retained_analytical_context?: LastSuccessfulAnalyticalContext;
    };
    assert.equal(plan.retained_analytical_context?.previousSQL, SQL_2004);
    assert.equal(
      (plan.retained_analytical_context?.data[0] as { customer_name?: string } | undefined)?.customer_name,
      'Motomarkt Stuttgart GmbH',
    );
  });

  it('a failed reply attempt preserves an unanswered clarification and its source rows', () => {
    const clarification = {
      ...CLARIFICATION,
      query_plan: {
        pending_clarification: {
          kind: 'currency_ambiguity',
          question: 'For the higher-sales country, show monthly billed sales in the same year and currency.',
          currency_column: 'currency',
        },
      },
    };
    const failed = {
      sql: '',
      data: [],
      answer_status: 'CANNOT_ANSWER',
      mode: 'data_limitation',
      query_plan: { failure: 'unsupported_followup' },
    };
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show top countries by billed sales in 2017 by currency.' },
      { role: 'assistant', content: 'Country sales', result: SUCCESS_2004 },
      { role: 'user', content: 'For the higher-sales country, show monthly billed sales in the same year and currency.' },
      { role: 'assistant', content: 'Which currency should I use?', result: clarification },
      { role: 'user', content: 'USD' },
      { role: 'assistant', content: 'No matching tables were found.', result: failed },
    ];

    const context = followupContextForSend(
      messages,
      lastSuccessfulAnalyticalContext(messages),
      false,
    );
    const plan = context?.previousPlan as {
      pending_clarification?: { kind?: string };
      retained_analytical_context?: LastSuccessfulAnalyticalContext;
    };
    assert.equal(context?.previousAnswerStatus, 'CLARIFICATION');
    assert.equal(plan.pending_clarification?.kind, 'currency_ambiguity');
    assert.equal(plan.retained_analytical_context?.previousSQL, SQL_2004);
    assert.equal(plan.retained_analytical_context?.data.length, 1);
  });

  it('recovers a legacy currency clarification from its wording and verified multi-currency rows', () => {
    const sourceRows = [
      { country: 'US', currency: 'USD', total_sales: 1200, rank: 1 },
      { country: 'DE', currency: 'USD', total_sales: 900, rank: 2 },
      { country: 'DE', currency: 'EUR', total_sales: 300, rank: 1 },
    ];
    const legacyClarification = {
      sql: '',
      data: [],
      // Some stored turns have clarification status but no pending plan marker.
      answer_status: 'SUCCESS',
      mode: 'clarification',
    };
    const failed = {
      sql: '',
      data: [],
      answer_status: 'CANNOT_ANSWER',
      mode: 'data_limitation',
    };
    const makeMessages = (answerStatus: string): AdaptiveChatMessage[] => [
      { role: 'user', content: 'Show top countries by billed sales in 2017 by currency.' },
      {
        role: 'assistant',
        content: 'The query completed and returned 3 rows.',
        result: { ...SUCCESS_2004, data: sourceRows },
      },
      { role: 'user', content: 'For the higher-sales country, show monthly billed sales in the same year and currency.' },
      {
        role: 'assistant',
        content: 'The prior ranking contains multiple currencies, so amounts cannot be compared directly. Choose a currency to continue.',
        result: { ...legacyClarification, answer_status: answerStatus },
      },
      { role: 'user', content: 'USD' },
      { role: 'assistant', content: 'No matching tables were found.', result: failed },
    ];

    for (const answerStatus of ['CLARIFICATION', 'SUCCESS']) {
      const messages = makeMessages(answerStatus);
      const context = followupContextForSend(
        messages,
        lastSuccessfulAnalyticalContext(messages),
        false,
      );
      const plan = context?.previousPlan as {
        pending_clarification?: { kind?: string; currency_column?: string };
        retained_analytical_context?: LastSuccessfulAnalyticalContext;
      };
      assert.equal(context?.previousAnswerStatus, 'CLARIFICATION');
      assert.equal(plan.pending_clarification?.kind, 'currency_ambiguity');
      assert.equal(plan.pending_clarification?.currency_column, 'currency');
      assert.equal(plan.retained_analytical_context?.data.length, 3);
    }
  });

  it('a failed drill-down keeps the last successful result for a retry', () => {
    const comparison = {
      sql: '',
      source_sql: SQL_2004,
      data: [
        { country: 'US', total_billed_sales: 1_227_978, currency: 'USD' },
        { country: 'DE', total_billed_sales: 10_000, currency: 'USD' },
      ],
      answer_status: 'SUCCESS',
      mode: 'result_first',
      query_plan: SUCCESS_2004.query_plan,
    };
    const failed = {
      sql: 'SELECT SUBSTRING(fkdat, 5, 2) AS month FROM VBRK',
      data: [],
      answer_status: 'CANNOT_ANSWER',
      sql_status: 'validation_failed',
      query_plan: { error: 'sql_validation_failed' },
    };
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show sales by country' },
      { role: 'assistant', content: 'Sales results', result: SUCCESS_2004 },
      { role: 'user', content: 'Which country had higher sales?' },
      { role: 'assistant', content: 'US had higher sales.', result: comparison },
      { role: 'user', content: 'Show monthly sales for that country.' },
      { role: 'assistant', content: 'The analysis could not be completed.', result: failed },
    ];

    const context = followupContextForSend(
      messages,
      lastSuccessfulAnalyticalContext(messages),
      false,
    );
    assert.equal(context?.previousQuestion, 'Which country had higher sales?');
    assert.equal(context?.previousSQL, SQL_2004);
    assert.equal((context?.data[0] as { country?: string })?.country, 'US');
    assert.equal((context?.data[0] as { total_billed_sales?: number })?.total_billed_sales, 1_227_978);
  });

  it('carries source SQL and derived rows from a successful result-first follow-up', () => {
    const derived = {
      sql: '',
      source_sql: SQL_2004,
      pipeline: 'result_first_followup',
      data: [{ country: 'US', total_billed_sales: 1_227_978, currency: 'USD' }],
      answer_status: 'SUCCESS',
    };
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show billed sales by country.' },
      { role: 'assistant', content: 'Sales results', result: SUCCESS_2004 },
      { role: 'user', content: 'Which country had the highest sales?' },
      { role: 'assistant', content: 'US had the highest sales.', result: derived },
    ];

    const context = latestAssistantContext(messages);
    assert.equal(context?.previousSQL, SQL_2004);
    assert.deepEqual(context?.data, derived.data);
    assert.equal(context?.previousQuestion, 'Which country had the highest sales?');
  });

  it('keeps every row from a result set when a follow-up refers to the same entities', () => {
    const rows = Array.from({ length: 32 }, (_, index) => ({
      customer_id: `C${index + 1}`,
      total_sales: 100 - index,
    }));
    const messages: AdaptiveChatMessage[] = [
      { role: 'user', content: 'Show the top 32 customers by billed sales.' },
      {
        role: 'assistant',
        content: '32 customers',
        result: { ...SUCCESS_2004, data: rows },
      },
    ];

    const context = lastSuccessfulAnalyticalContext(messages);
    assert.equal(context?.data.length, 32);
    assert.equal((context?.data[31] as { customer_id?: string })?.customer_id, 'C32');
  });
});
