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
// Preserve the full default Top-N result for follow-ups that refer to its entities.
const MAX_PRIOR_RESULT_ROWS = 200;

export type AdaptiveAnswerStatus = string;

export type AdaptiveQueryResultLike = {
  sql?: string;
  pipeline?: string;
  data?: unknown[];
  query_plan?: unknown;
  queryPlan?: unknown;
  answer_status?: AdaptiveAnswerStatus;
  answerStatus?: AdaptiveAnswerStatus;
  summary?: string;
  answer?: string;
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

function withRetainedAnalyticalContext(
  planValue: unknown,
  messages: AdaptiveChatMessage[],
): unknown {
  const retained = lastSuccessfulAnalyticalContext(messages);
  if (!retained) return planValue;
  const plan = planValue && typeof planValue === 'object'
    ? planValue as Record<string, unknown>
    : {};
  return { ...plan, retained_analytical_context: retained };
}

export function isGeneralChatResult(
  result: AdaptiveQueryResultLike | null | undefined,
): boolean {
  if (!result) return false;
  const status = answerStatusOf(result);
  if (BLOCKED_STATUSES.has(status)) return false;
  const mode = String(result.mode || result.route || '').toLowerCase();
  if (mode === 'general_chat' || mode === 'general') return true;
  if (mode || String(result.pipeline || '').toLowerCase() === 'result_first_followup') return false;
  const sql = String(result.sql || '').trim();
  return status === 'SUCCESS' && !sql && !(Array.isArray(result.data) && result.data.length > 0);
}

function isDerivedAnalyticalResult(
  result: AdaptiveQueryResultLike | null | undefined,
): boolean {
  if (!result || BLOCKED_STATUSES.has(answerStatusOf(result))) return false;
  const mode = String(result.mode || '').toLowerCase();
  const pipeline = String(result.pipeline || '').toLowerCase();
  return answerStatusOf(result) === 'SUCCESS'
    && (mode === 'result_first' || pipeline === 'result_first_followup');
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
      if (message.role !== 'assistant' || !isDerivedAnalyticalResult(message.result)) continue;
      const result = message.result!;
      const source = lastSuccessfulAnalyticalContext(messages.slice(0, i));
      const sourcePlan = source?.previousPlan && typeof source.previousPlan === 'object'
        ? source.previousPlan as Record<string, unknown>
        : {};
      const resultPlan = result.query_plan || result.queryPlan;
      return {
        previousQuestion: precedingUserQuestion(messages, i),
        previousSQL: source?.previousSQL || '',
        previousPlan: resultPlan && typeof resultPlan === 'object'
          ? { ...sourcePlan, ...(resultPlan as Record<string, unknown>) }
          : sourcePlan,
        previousAnswerStatus: answerStatusOf(result) || 'SUCCESS',
        data: Array.isArray(result.data) ? result.data.slice(0, MAX_PRIOR_RESULT_ROWS) : [],
      };
    }
    const result = message.result!;
    const sql = String(result.sql || '').trim();
    return {
      previousQuestion: precedingUserQuestion(messages, i),
      previousSQL: sql,
      previousPlan: result.query_plan || result.queryPlan || null,
      previousAnswerStatus: answerStatusOf(result) || 'SUCCESS',
      data: Array.isArray(result.data) ? result.data.slice(0, MAX_PRIOR_RESULT_ROWS) : [],
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
    data: Array.isArray(result!.data) ? result!.data.slice(0, MAX_PRIOR_RESULT_ROWS) : [],
  };
}

export function lastPendingClarificationContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  const failedStatuses = new Set(['CANNOT_ANSWER', 'ERROR', 'TIMEOUT', 'CANCELLED']);
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant') continue;
    const status = answerStatusOf(message.result);
    const recoveredCurrency = recoverLegacyCurrencyClarification(messages, i);
    if (status === 'CLARIFICATION') {
      const originalPlan = message.result?.query_plan || message.result?.queryPlan || {
        awaiting_sales_choice: /sales order/i.test(message.content || '') && /billed|invoice/i.test(message.content || ''),
      };
      const recoveredPlan = recoveredCurrency?.previousPlan && typeof recoveredCurrency.previousPlan === 'object'
        ? recoveredCurrency.previousPlan as Record<string, unknown>
        : {};
      const clarificationPlan = originalPlan && typeof originalPlan === 'object'
        ? originalPlan as Record<string, unknown>
        : {};
      return {
        previousQuestion: precedingUserQuestion(messages, i),
        previousSQL: '',
        previousPlan: withRetainedAnalyticalContext(
          recoveredCurrency?.previousAnswerStatus === 'CLARIFICATION'
            ? { ...clarificationPlan, pending_clarification: recoveredPlan.pending_clarification }
            : clarificationPlan,
          messages,
        ),
        previousAnswerStatus: 'CLARIFICATION',
        data: [],
      };
    }
    // Older persisted turns may not contain answer_status/query_plan because
    // they were saved before clarification metadata was added. Recover a
    // currency choice only when the assistant wording asks for one AND the
    // preceding verified result actually contains multiple currency values.
    if (recoveredCurrency) return recoveredCurrency;
    // A failed attempt to answer the clarification must not erase the user's
    // pending choice. A later successful assistant turn does close it.
    if (!failedStatuses.has(status)) {
      return null;
    }
  }
  return null;
}

function recoverLegacyCurrencyClarification(
  messages: AdaptiveChatMessage[],
  assistantIndex: number,
): LastSuccessfulAnalyticalContext | null {
  const message = messages[assistantIndex];
  if (!message || message.role !== 'assistant') return null;
  const content = [message.content, message.result?.summary, message.result?.answer]
    .filter((part): part is string => typeof part === 'string')
    .join(' ');
  const asksForCurrency =
    /\b(?:choose|select|specify|pick|confirm)\b.{0,100}\bcurrenc(?:y|ies)\b/i.test(content)
    || /\bcurrenc(?:y|ies)\b.{0,100}\b(?:choose|select|specify|pick|confirm)\b/i.test(content)
    || /\b(?:multiple|different|mixed)\s+currenc(?:y|ies)\b.{0,120}\b(?:cannot|can't|need|please)\b/i.test(content);
  if (!asksForCurrency) return null;

  const sourceMessages = messages.slice(0, assistantIndex);
  const source = lastSuccessfulAnalyticalContext(sourceMessages);
  if (!source || source.data.length === 0) return null;
  const firstRow = source.data.find((row) => row && typeof row === 'object') as Record<string, unknown> | undefined;
  if (!firstRow) return null;
  const currencyColumn = Object.keys(firstRow).find((column) =>
    /^(?:currency|currency_code|waerk|waers)$/i.test(column.trim()),
  );
  if (!currencyColumn) return null;
  const currencies = new Set(source.data
    .map((row) => row && typeof row === 'object'
      ? String((row as Record<string, unknown>)[currencyColumn] ?? '').trim().toUpperCase()
      : '')
    .filter(Boolean));
  if (currencies.size < 2) return null;

  const question = precedingUserQuestion(messages, assistantIndex);
  const existingPlan = message.result?.query_plan || message.result?.queryPlan;
  const plan = existingPlan && typeof existingPlan === 'object'
    ? existingPlan as Record<string, unknown>
    : {};
  return {
    previousQuestion: question,
    previousSQL: '',
    previousPlan: withRetainedAnalyticalContext({
      ...plan,
      pending_clarification: {
        kind: 'currency_ambiguity',
        question,
        currency_column: currencyColumn,
      },
    }, sourceMessages),
    previousAnswerStatus: 'CLARIFICATION',
    data: [],
  };
}

/** Context from the most recent assistant turn — continuous chat default. */
export function latestAssistantContext(
  messages: AdaptiveChatMessage[],
): LastSuccessfulAnalyticalContext | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.role !== 'assistant') continue;
    const result = message.result || {
      answer_status: 'SUCCESS', mode: 'general_chat',
      query_plan: { last_mode: 'general_chat', investigation_state: { last_summary: message.content } },
    };
    const status = answerStatusOf(result);
    const previousQuestion = precedingUserQuestion(messages, i);

    if (isGeneralChatResult(result)) {
      const priorPlan = result.query_plan || result.queryPlan || { last_mode: 'general_chat' };
      const retainedAnalysis = lastSuccessfulAnalyticalContext(messages);
      const contextPlan = retainedAnalysis
        ? {
            ...(priorPlan && typeof priorPlan === 'object'
              ? priorPlan as Record<string, unknown>
              : {}),
            retained_analytical_context: retainedAnalysis,
          }
        : priorPlan;
      return {
        previousQuestion,
        previousSQL: '',
        previousPlan: contextPlan,
        previousAnswerStatus: status || 'SUCCESS',
        data: [],
      };
    }
    if (isDerivedAnalyticalResult(result)) {
      return lastSuccessfulAnalyticalContext(messages.slice(0, i + 1));
    }
    if (status === 'CLARIFICATION') {
      const priorPlan = result.query_plan || result.queryPlan || null;
      return {
        previousQuestion,
        previousSQL: '',
        // A clarification about a follow-up must not erase the last verified
        // analysis. The API can restore this saved context on the next turn.
        previousPlan: withRetainedAnalyticalContext(priorPlan, messages),
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
        data: Array.isArray(result.data) ? result.data.slice(0, MAX_PRIOR_RESULT_ROWS) : [],
      };
    }
    // Metadata / other SUCCESS without SQL
    if (status === 'SUCCESS') {
      return {
        previousQuestion,
        previousSQL: String(result.sql || '').trim(),
        previousPlan: result.query_plan || result.queryPlan || { last_mode: String(result.mode || 'general') },
        previousAnswerStatus: 'SUCCESS',
        data: Array.isArray(result.data) ? result.data.slice(0, MAX_PRIOR_RESULT_ROWS) : [],
      };
    }
    // Failed / cancelled turns do not erase a prior successful result. Keep
    // walking back until a usable assistant turn supplies context.
    continue;
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
  const context = (
    lastPendingClarificationContext(messages)
    || latestAssistantContext(messages)
    || lastGeneralChatContext(messages)
    || buildFollowupContextData(analytical, false)
  );
  if (!context) return null;
  const plan = (context.previousPlan && typeof context.previousPlan === 'object')
    ? context.previousPlan as Record<string, unknown> : {};
  const artifact = (plan.result_artifact || {}) as Record<string, unknown>;
  return { ...context, previousPlan: { ...plan, result_artifact: {
    ...artifact, sample_row_count: context.data.length,
    truncated: Boolean(artifact.truncated) || Number(artifact.row_count || 0) > context.data.length,
  } } };
}

export function buildFollowupContextData(
  state: LastSuccessfulAnalyticalContext | null,
  isNewQuestion: boolean,
): LastSuccessfulAnalyticalContext | null {
  if (isNewQuestion || !state) return null;
  return state;
}
