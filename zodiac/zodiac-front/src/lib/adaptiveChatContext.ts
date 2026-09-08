/**
 * Full Chat follow-up context is the last successful analytical state,
 * not the latest chat message.
 *
 * Clarification / non-business / empty-SQL turns must not replace that state.
 * Production bundle marker: last_successful_analytical_v1
 */
export const ADAPTIVE_CONTEXT_POLICY = 'last_successful_analytical_v1';

export type AdaptiveAnswerStatus = string;

export type AdaptiveQueryResultLike = {
  sql?: string;
  data?: unknown[];
  query_plan?: unknown;
  queryPlan?: unknown;
  answer_status?: AdaptiveAnswerStatus;
  answerStatus?: AdaptiveAnswerStatus;
};

export type AdaptiveChatMessage = {
  role: 'user' | 'assistant';
  content: string;
  result?: AdaptiveQueryResultLike;
};

export type LastSuccessfulAnalyticalContext = {
  previousQuestion: string;
  previousSQL: string;
  previousPlan: unknown;
  previousAnswerStatus: string;
  data: unknown[];
};

const BLOCKED_STATUSES = new Set(['CLARIFICATION', 'CANNOT_ANSWER', 'ERROR']);

function answerStatusOf(result: AdaptiveQueryResultLike | undefined): string {
  return String(result?.answer_status || result?.answerStatus || '').toUpperCase();
}

export function isGeneralChatResult(
  result: AdaptiveQueryResultLike | null | undefined,
): boolean {
  if (!result) return false;
  const status = answerStatusOf(result);
  if (BLOCKED_STATUSES.has(status)) return false;
  const mode = String((result as { mode?: string }).mode || '').toLowerCase();
  if (mode === 'general_chat' || mode === 'general') return true;
  const sql = String(result.sql || '').trim();
  return status === 'SUCCESS' && !sql;
}

export function lastGeneralChatContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant' || !isGeneralChatResult(message.result)) {
      continue;
    }
    const result = message.result!;
    let previousQuestion = '';
    for (let j = i - 1; j >= 0; j--) {
      if (messages[j].role === 'user') {
        previousQuestion = messages[j].content;
        break;
      }
    }
    return {
      previousQuestion,
      previousSQL: '',
      previousPlan: result.query_plan || result.queryPlan || { last_mode: 'general_chat' },
      previousAnswerStatus: answerStatusOf(result) || 'SUCCESS',
      data: [],
    };
  }
  return null;
}

export function isSuccessfulAnalyticalResult(
  result: AdaptiveQueryResultLike | null | undefined,
): boolean {
  if (!result) return false;
  const status = answerStatusOf(result);
  if (BLOCKED_STATUSES.has(status)) return false;
  const sql = String(result.sql || '').trim();
  if (!sql) return false;
  if (!/\bselect\b/i.test(sql)) return false;
  return true;
}

export function lastSuccessfulAnalyticalContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant' || !isSuccessfulAnalyticalResult(message.result)) {
      continue;
    }
    const result = message.result!;
    const sql = String(result.sql || '').trim();
    let previousQuestion = '';
    for (let j = i - 1; j >= 0; j--) {
      if (messages[j].role === 'user') {
        previousQuestion = messages[j].content;
        break;
      }
    }
    return {
      previousQuestion,
      previousSQL: sql,
      previousPlan: result.query_plan || result.queryPlan || null,
      previousAnswerStatus: answerStatusOf(result) || 'SUCCESS',
      data: Array.isArray(result.data) ? result.data.slice(0, 20) : [],
    };
  }
  return null;
}

export function updateLastSuccessfulAnalyticalContext(
  previous: LastSuccessfulAnalyticalContext | null,
  question: string,
  result: AdaptiveQueryResultLike | null | undefined,
): LastSuccessfulAnalyticalContext | null {
  if (!isSuccessfulAnalyticalResult(result)) {
    return previous;
  }
  const sql = String(result!.sql || '').trim();
  return {
    previousQuestion: question,
    previousSQL: sql,
    previousPlan: result!.query_plan || result!.queryPlan || null,
    previousAnswerStatus: answerStatusOf(result!) || 'SUCCESS',
    data: Array.isArray(result!.data) ? result!.data.slice(0, 20) : [],
  };
}

export function lastPendingClarificationContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant') continue;
    if (answerStatusOf(message.result) !== 'CLARIFICATION') {
      return null;
    }
    let previousQuestion = '';
    for (let j = i - 1; j >= 0; j--) {
      if (messages[j].role === 'user') {
        previousQuestion = messages[j].content;
        break;
      }
    }
    return {
      previousQuestion,
      previousSQL: '',
      previousPlan: message.result?.query_plan || message.result?.queryPlan || {
        awaiting_sales_choice: /sales order/i.test(message.content || '') && /billed|invoice/i.test(message.content || ''),
      },
      previousAnswerStatus: 'CLARIFICATION',
      data: [],
    };
  }
  return null;
}

export function followupContextForSend(
  messages: AdaptiveChatMessage[],
  analytical: LastSuccessfulAnalyticalContext | null,
  isNewQuestion: boolean,
): LastSuccessfulAnalyticalContext | null {
  if (isNewQuestion) return null;
  return (
    lastPendingClarificationContext(messages)
    || buildFollowupContextData(analytical, false)
    || lastGeneralChatContext(messages)
  );
}

export function buildFollowupContextData(
  state: LastSuccessfulAnalyticalContext | null,
  isNewQuestion: boolean,
): LastSuccessfulAnalyticalContext | null {
  if (isNewQuestion || !state) return null;
  return state;
}
