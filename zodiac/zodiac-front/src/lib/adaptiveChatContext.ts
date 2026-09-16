/**
 * Continuous chat context — prefer the latest assistant turn (ChatGPT-style).
 *
 * Analytical SQL state is still carried when the latest turn was analytical,
 * so "top 5" / year follow-ups keep working. General chat / capability /
 * clarification turns take priority when they are the most recent reply.
 *
 * Production bundle marker: continuous_chat_v1
 */
export const ADAPTIVE_CONTEXT_POLICY = 'continuous_chat_v1';

export type AdaptiveAnswerStatus = string;

export type AdaptiveQueryResultLike = {
  sql?: string;
  data?: unknown[];
  query_plan?: unknown;
  queryPlan?: unknown;
  answer_status?: AdaptiveAnswerStatus;
  answerStatus?: AdaptiveAnswerStatus;
  mode?: string;
  route?: string;
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

const BLOCKED_STATUSES = new Set(['CANNOT_ANSWER', 'ERROR', 'TIMEOUT']);

function answerStatusOf(result: AdaptiveQueryResultLike | undefined): string {
  return String(result?.answer_status || result?.answerStatus || '').toUpperCase();
}

function precedingUserQuestion(messages: AdaptiveChatMessage[], assistantIndex: number): string {
  for (let j = assistantIndex - 1; j >= 0; j--) {
    if (messages[j].role === 'user') {
      return messages[j].content;
    }
  }
  return '';
}

export function isGeneralChatResult(
  result: AdaptiveQueryResultLike | null | undefined,
): boolean {
  if (!result) return false;
  const status = answerStatusOf(result);
  if (BLOCKED_STATUSES.has(status)) return false;
  const mode = String(result.mode || result.route || '').toLowerCase();
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
    return {
      previousQuestion: precedingUserQuestion(messages, i),
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
  if (BLOCKED_STATUSES.has(status) || status === 'CLARIFICATION') return false;
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
    return {
      previousQuestion: precedingUserQuestion(messages, i),
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
    return {
      previousQuestion: precedingUserQuestion(messages, i),
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

/** Context from the most recent assistant turn — continuous chat default. */
export function latestAssistantContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant' || !message.result) continue;
    const result = message.result;
    const status = answerStatusOf(result);
    const previousQuestion = precedingUserQuestion(messages, i);

    if (isGeneralChatResult(result)) {
      return {
        previousQuestion,
        previousSQL: '',
        previousPlan: result.query_plan || result.queryPlan || { last_mode: 'general_chat' },
        previousAnswerStatus: status || 'SUCCESS',
        data: [],
      };
    }
    if (status === 'CLARIFICATION') {
      return {
        previousQuestion,
        previousSQL: '',
        previousPlan: result.query_plan || result.queryPlan || null,
        previousAnswerStatus: 'CLARIFICATION',
        data: [],
      };
    }
    if (isSuccessfulAnalyticalResult(result)) {
      const sql = String(result.sql || '').trim();
      return {
        previousQuestion,
        previousSQL: sql,
        previousPlan: result.query_plan || result.queryPlan || null,
        previousAnswerStatus: status || 'SUCCESS',
        data: Array.isArray(result.data) ? result.data.slice(0, 20) : [],
      };
    }
    // Metadata / other SUCCESS without SQL
    if (status === 'SUCCESS') {
      return {
        previousQuestion,
        previousSQL: String(result.sql || '').trim(),
        previousPlan: result.query_plan || result.queryPlan || { last_mode: String(result.mode || 'general') },
        previousAnswerStatus: 'SUCCESS',
        data: Array.isArray(result.data) ? result.data.slice(0, 20) : [],
      };
    }
    return null;
  }
  return null;
}

export function followupContextForSend(
  messages: AdaptiveChatMessage[],
  analytical: LastSuccessfulAnalyticalContext | null,
  isNewQuestion: boolean,
): LastSuccessfulAnalyticalContext | null {
  if (isNewQuestion) return null;
  // ChatGPT-style: always prefer the latest assistant turn.
  return (
    latestAssistantContext(messages)
    || lastPendingClarificationContext(messages)
    || lastGeneralChatContext(messages)
    || buildFollowupContextData(analytical, false)
  );
}

export function buildFollowupContextData(
  state: LastSuccessfulAnalyticalContext | null,
  isNewQuestion: boolean,
): LastSuccessfulAnalyticalContext | null {
  if (isNewQuestion || !state) return null;
  return state;
}
