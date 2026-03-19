'use client';

import { useState, useRef, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import {
  Sparkles, Send, ArrowDownToLine, ArrowUpFromLine, TrendingUp,
  GitBranch, RefreshCw, Mic, MicOff,
  Activity, BarChart3, Clock, Zap, AlertTriangle, CheckCircle2,
  ArrowUpRight, ArrowDownRight, Minus, CalendarRange, Eye,
  FlaskConical, TrendingDown, DollarSign, XCircle, FileCode,
} from 'lucide-react';
import AIChartRenderer from './ai/AIChartRenderer';
import MultiModelComparison from './ai/MultiModelComparison';
import { useVoiceRecording } from '../hooks/useVoiceRecording';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

/* ─── Constants ──────────────────────────────────────────────── */

const DEFAULT_DAYS = 30;

const AI_CONTEXT_KEYS = [
  'stats', 'failed_summary', 'top_customers',
  'inbound_summary', 'business_summary', 'process_flow',
];

const REALTIME_PROMPTS = [
  { label: 'Failed invoices', query: 'Summarize failed invoices and main failure reasons' },
  { label: 'Inbound SAT status', query: 'Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers' },
  { label: 'Top customers', query: 'Show top customers with currency and number of invoices (outbound process)' },
  { label: 'Outbound flow', query: 'Show the outbound process flow and current document counts at each step' },
];

const HISTORICAL_PROMPTS = [
  { label: 'Profit margin', query: 'Show profit margin by product for all products in the database' },
  { label: 'Revenue trend', query: 'Summarize revenue by customer and by country with trend analysis' },
  { label: 'Flow deviation', query: 'How does my current document flow deviate from the standard process?' },
  { label: 'Period forecast', query: 'Based on historical patterns, forecast next period revenue and invoice volume' },
  { label: 'Anomaly detection', query: 'Identify any anomalies or unusual patterns in the historical data' },
];

/* ─── Types ───────────────────────────────────────────────────── */

type AiAnalysisMeta = {
  validation?: SqlValidationMeta;
  proposed_validation?: SqlValidationMeta;
  query_origin?: string;
  suggestion_source?: string;
  action?: string; reason?: string; sql?: string;
  rows_preview?: Record<string, unknown>[];
  compare?: unknown; charts?: any[]; multiModel?: any;
  time_scope?: string;
  date_range?: { min_date: string; max_date: string };
  period_info?: string;
  needs_approval?: boolean;
  proposed_sql?: string;
  performance?: {
    action_decision_ms?: number;
    pattern_matching_ms?: number;
    cache_lookup_ms?: number;
    sql_execution_ms?: number;
    summarization_ms?: number;
    chart_generation_ms?: number;
    total_ms?: number;
    used_pattern?: boolean;
    used_cache?: boolean;
    row_count?: number;
    chart_count?: number;
  };
};

type SqlValidationMeta = {
  errors?: string[];
  warnings?: string[];
  tables?: string[];
  columns?: string[];
  date_normalizations?: string[];
  aggregate_functions?: string[];
};

type SuggestedSqlResult = {
  sql: string;
  source?: string;
  validation?: SqlValidationMeta;
};

type Message = {
  role: 'user' | 'assistant';
  content: string;
  meta?: AiAnalysisMeta;
  section?: 'realtime' | 'historical';
  ts?: number;
};

type OutboundData = {
  summary?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
  top_customers?: { customer_id: string; customer_name: string; currency: string; count: number }[];
  funnel?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
};

type InboundData = {
  summary?: { total_documents: number; merges_total: number; merges_sent_to_sap: number; merges_pending: number };
  top_suppliers?: { supplier_rfc: string; supplier_name: string; count: number; total_amount: number }[];
};

type BusinessData = {
  revenue_by_customer?: { customer_id: string; customer_name: string; invoice_count: number; total_revenue: number }[];
  revenue_by_country?: { country: string; country_name?: string; invoice_count: number; total_revenue: number }[];
  trend?: { current_period_revenue: number; previous_period_revenue: number; revenue_change_pct: number };
};

/* ─── Tiny helpers ────────────────────────────────────────────── */

function fmt(n: number | string | undefined) {
  return Number(n ?? 0).toLocaleString();
}

function TrendBadge({ pct }: { pct: number }) {
  if (pct > 0) return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono font-semibold text-emerald-600">
      <ArrowUpRight className="h-3 w-3" />+{pct}%
    </span>
  );
  if (pct < 0) return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono font-semibold text-red-500">
      <ArrowDownRight className="h-3 w-3" />{pct}%
    </span>
  );
  return (
    <span className="inline-flex items-center gap-0.5 text-xs font-mono text-slate-400">
      <Minus className="h-3 w-3" />0%
    </span>
  );
}

function SkeletonRow() {
  return (
    <div className="flex gap-3 py-2 animate-pulse">
      <div className="h-3 bg-slate-100 rounded flex-1" />
      <div className="h-3 bg-slate-100 rounded w-16" />
      <div className="h-3 bg-slate-100 rounded w-12" />
    </div>
  );
}

function LivePulse() {
  return (
    <span className="relative flex h-2 w-2">
      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75" />
      <span className="relative inline-flex rounded-full h-2 w-2 bg-blue-500" />
    </span>
  );
}

function ValidationNotes({ validation }: { validation?: SqlValidationMeta }) {
  if (!validation) return null;
  const errors = validation.errors ?? [];
  const warnings = validation.warnings ?? [];
  const notes = validation.date_normalizations ?? [];
  if (!errors.length && !warnings.length && !notes.length) return null;

  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] text-amber-900 space-y-1">
      {errors.map((error, idx) => (
        <div key={`error-${idx}`}>Blocked: {error}</div>
      ))}
      {warnings.map((warning, idx) => (
        <div key={`warning-${idx}`}>Warning: {warning}</div>
      ))}
      {notes.map((note, idx) => (
        <div key={`note-${idx}`}>Normalized: {note}</div>
      ))}
    </div>
  );
}

/* ─── Stat Card ──────────────────────────────────────────────── */

function StatCard({
  label, value, sub, accent = false,
}: { label: string; value: string | number; sub?: React.ReactNode; accent?: boolean }) {
  return (
    <div className={`rounded-xl border px-4 py-3.5 flex flex-col gap-1.5 ${accent ? 'bg-gradient-to-br from-blue-600 to-indigo-700 border-blue-600 text-white shadow-lg' : 'bg-white border-slate-200'}`}>
      <span className={`text-[10px] font-mono uppercase tracking-widest ${accent ? 'text-blue-100' : 'text-slate-500'}`}>{label}</span>
      <span className={`text-2xl font-mono font-bold tabular-nums leading-none ${accent ? 'text-white' : 'text-slate-900'}`}>{fmt(value)}</span>
      {sub && <div className="text-xs mt-0.5">{sub}</div>}
    </div>
  );
}

/* ─── Funnel Step ────────────────────────────────────────────── */

function FunnelStep({ step, label, count, total, warn = false }: {
  step: number; label: string; count: number; total: number; warn?: boolean;
}) {
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  return (
    <div className="flex items-center gap-2.5">
      <span className="w-4 h-4 rounded-full bg-slate-100 flex items-center justify-center text-[9px] font-mono font-bold text-slate-600 flex-shrink-0">
        {step}
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between mb-0.5">
          <span className="text-xs text-slate-600 truncate">{label}</span>
          <span className={`text-xs font-mono font-bold ml-2 ${warn ? 'text-red-500' : 'text-slate-800'}`}>{fmt(count)}</span>
        </div>
        <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-700 ${warn ? 'bg-red-400' : 'bg-gradient-to-r from-blue-600 to-indigo-700'}`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
      <span className="text-[10px] font-mono text-slate-400 w-7 text-right flex-shrink-0">{pct}%</span>
    </div>
  );
}

/* ─── Chat Panel ─────────────────────────────────────────────── */

function ChatPanel({
  section,
  messages,
  loading,
  prompts,
  onSend,
  onApproveQuery,
  onRejectQuery,
  onStoreQuery,
  onSuggestSql,
  placeholder,
  useContext,
  setUseContext,
  useMultiModel,
  setUseMultiModel,
  fullWidth = false,
}: {
  section: 'realtime' | 'historical';
  messages: Message[];
  loading: boolean;
  prompts: { label: string; query: string }[];
  onSend: (text: string) => void;
  onApproveQuery?: (question: string, proposedSql: string, approvalSource?: 'chatgpt' | 'manual' | 'assistant_sql') => Promise<boolean>;
  onRejectQuery?: (question: string, rejectedSql: string, attemptSource?: 'chatgpt' | 'manual' | 'assistant_sql') => Promise<void>;
  onStoreQuery?: (question: string, sql: string) => Promise<void>;
  onSuggestSql?: (question: string) => Promise<SuggestedSqlResult>;
  placeholder: string;
  useContext: boolean;
  setUseContext: (v: boolean) => void;
  useMultiModel: boolean;
  setUseMultiModel: (v: boolean) => void;
  fullWidth?: boolean;
}) {
  const [input, setInput] = useState('');
  const [confirmedIndices, setConfirmedIndices] = useState<Set<number>>(new Set());
  const [rejectingIndex, setRejectingIndex] = useState<number | null>(null);
  const [suggestedSql, setSuggestedSql] = useState<SuggestedSqlResult | null>(null);
  const [manualSql, setManualSql] = useState('');
  const [suggestLoading, setSuggestLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const {
    isListening, transcript, isSupported: isVoiceSupported,
    error: voiceError, startListening, stopListening, resetTranscript,
  } = useVoiceRecording();

  useEffect(() => { if (transcript) setInput(transcript); }, [transcript]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  const toggleVoice = () => {
    if (isListening) { stopListening(); } else { resetTranscript(); startListening(); }
  };

  const submit = (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;
    if (!text) setInput('');
    onSend(msg);
  };

  // Check if any message has charts
  const messagesWithCharts = messages.filter(
    m => m.role === 'assistant' && m.meta?.charts && m.meta.charts.length > 0
  );
  const hasCharts = messagesWithCharts.length > 0;

  // In full-width mode, charts appear in a side panel at md+ breakpoint
  const chartPanelBreakpoint = fullWidth ? 'md' : 'lg';

  const recordRejection = async (
    question: string | undefined,
    rejectedSql: string | undefined,
    attemptSource: 'chatgpt' | 'manual' | 'assistant_sql',
  ) => {
    if (!question || !rejectedSql || !onRejectQuery) return;
    try {
      await onRejectQuery(question, rejectedSql, attemptSource);
    } catch (err) {
      console.error('Reject feedback failed:', err);
    }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Suggested prompts */}
      <div className="px-3 py-2 border-b border-slate-100 flex flex-wrap gap-1.5">
        {prompts.map((p) => (
          <button
            key={p.label}
            type="button"
            onClick={() => submit(p.query)}
            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-slate-200 bg-white text-[11px] font-medium text-slate-600 hover:border-slate-400 hover:text-slate-900 transition-all"
          >
            <Sparkles className="h-3 w-3 text-slate-400" />
            {p.label}
          </button>
        ))}
      </div>

      {/* Main content area: messages + optional chart panel */}
      <div className="flex-1 overflow-hidden min-h-0 flex gap-0">

        {/* Messages column */}
        <div className={`flex flex-col overflow-hidden ${hasCharts ? `w-full ${chartPanelBreakpoint === 'md' ? 'md:w-[45%]' : 'lg:w-[45%]'}` : 'w-full'}`}>
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center py-10 select-none">
                <div className="w-10 h-10 rounded-2xl bg-slate-100 flex items-center justify-center mb-3">
                  {section === 'realtime'
                    ? <Activity className="h-4 w-4 text-slate-400" />
                    : <BarChart3 className="h-4 w-4 text-slate-400" />}
                </div>
                <p className="text-sm font-medium text-slate-500 mb-1">
                  {section === 'realtime' ? 'Real-time Intelligence' : 'Historical Analysis'}
                </p>
                <p className="text-xs text-slate-400 max-w-xs">
                  {section === 'realtime'
                    ? 'Ask about live SAT documents, invoice status, and current process flows.'
                    : 'Explore trends, compare periods, and generate forward-looking forecasts.'}
                </p>
              </div>
            ) : (
              messages.map((m, i) => (
                <div key={i} className={`flex flex-col gap-0.5 ${m.role === 'user' ? 'items-end' : 'items-start'}`}>
                  <span className="text-[10px] font-mono text-slate-400 px-1">
                    {m.role === 'user' ? 'YOU' : 'AI'}{m.ts ? ` · ${new Date(m.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
                  </span>
                  <div className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed break-words ${
                    m.role === 'user'
                      ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-tr-sm shadow-md'
                      : 'bg-slate-50 border border-slate-200 text-slate-800 rounded-tl-sm'
                  }`}>
                    {m.role === 'user' ? (
                      <div className="whitespace-pre-wrap">{m.content}</div>
                    ) : (
                      <div className="prose prose-sm max-w-none
                        prose-headings:mt-3 prose-headings:mb-2 prose-headings:font-semibold prose-headings:text-slate-900
                        prose-h3:text-base prose-h4:text-sm
                        prose-p:my-1.5 prose-p:text-slate-700
                        prose-strong:text-slate-900 prose-strong:font-bold prose-strong:bg-yellow-100 prose-strong:px-1 prose-strong:rounded
                        prose-ul:my-2 prose-ul:ml-4 prose-li:my-0.5 prose-li:text-slate-700
                        prose-ol:my-2 prose-ol:ml-4
                        prose-code:text-xs prose-code:bg-slate-100 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-code:text-blue-700
                        prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-pre:rounded-lg prose-pre:p-3
                        prose-blockquote:border-l-4 prose-blockquote:border-blue-500 prose-blockquote:pl-4 prose-blockquote:italic prose-blockquote:text-slate-600
                        prose-table:text-xs
                      ">
                        <ReactMarkdown>{m.content}</ReactMarkdown>
                      </div>
                    )}
                  </div>
                  {/* ChatGPT proposes SQL (AI failed): show SQL + Yes/No + Ask ChatGPT + Enter SQL always */}
                  {m.role === 'assistant' && m.meta?.needs_approval && (onApproveQuery || onSuggestSql) && (
                    <div className="max-w-[92%] mt-2">
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-3">
                        <p className="text-xs font-medium text-slate-700">ChatGPT suggested SQL:</p>
                        {m.meta?.proposed_sql ? (
                          <pre className="text-[10px] bg-slate-900 text-slate-50 rounded p-2 overflow-auto max-h-40 whitespace-pre-wrap font-mono">{m.meta.proposed_sql}</pre>
                        ) : (
                          <p className="text-[10px] text-slate-500 italic">(SQL not available — use Ask ChatGPT or enter manually below)</p>
                        )}
                        <ValidationNotes validation={m.meta?.proposed_validation} />
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs text-slate-600">Is this SQL correct?</span>
                          {m.meta?.proposed_sql && onApproveQuery && (
                            <button
                              type="button"
                              onClick={async () => {
                                const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                if (prevUser && m.meta?.proposed_sql) {
                                  try {
                                    const stored = await onApproveQuery(prevUser.content, m.meta.proposed_sql, 'chatgpt');
                                    if (stored) {
                                      setConfirmedIndices((s) => new Set(s).add(i));
                                    }
                                  } catch (err) {
                                    console.error('Approve failed:', err);
                                  }
                                }
                              }}
                              disabled={loading}
                              className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium disabled:opacity-50"
                            >
                              <CheckCircle2 className="h-3.5 w-3.5" />
                              Yes, approve &amp; run
                            </button>
                          )}
                          <button
                            type="button"
                            onClick={async () => {
                              const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                              await recordRejection(prevUser?.content, m.meta?.proposed_sql, 'chatgpt');
                              setRejectingIndex(rejectingIndex === i ? null : i);
                              setSuggestedSql(null);
                              // Keep manualSql - user may have typed their own SQL
                            }}
                            disabled={loading}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-red-100 hover:bg-red-200 text-red-700 text-xs font-medium disabled:opacity-50"
                          >
                            <XCircle className="h-3 w-3" />
                            No
                          </button>
                        </div>
                        <div className="pt-2 border-t border-slate-200 space-y-2">
                          <p className="text-xs font-medium text-slate-700">
                            {rejectingIndex === i ? 'Rejected — enter your own SQL or ask for a new suggestion:' : 'Or get a new suggestion / enter SQL manually:'}
                          </p>
                            <div className="flex flex-wrap gap-2">
                              {onSuggestSql && (
                                <button
                                  type="button"
                                  onClick={async () => {
                                    const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                    if (!prevUser) return;
                                    setSuggestLoading(true);
                                    try {
                                      const sql = await onSuggestSql(prevUser.content);
                                      setSuggestedSql(sql);
                                    } catch (err) {
                                      console.error('Suggest failed:', err);
                                    } finally {
                                      setSuggestLoading(false);
                                    }
                                  }}
                                  disabled={suggestLoading || loading}
                                  className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium disabled:opacity-50"
                                >
                                  <Sparkles className="h-3 w-3" />
                                  {suggestLoading ? 'Asking ChatGPT…' : 'Ask ChatGPT'}
                                </button>
                              )}
                            </div>
                            {suggestedSql && (
                              <div className="space-y-2">
                                <pre className="text-[10px] bg-slate-900 text-slate-50 rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{suggestedSql.sql}</pre>
                                <ValidationNotes validation={suggestedSql.validation} />
                                {onApproveQuery && (
                                  <button
                                    type="button"
                                    onClick={async () => {
                                      const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                      if (prevUser) {
                                        const stored = await onApproveQuery(prevUser.content, suggestedSql.sql, suggestedSql.source === 'chatgpt' ? 'chatgpt' : 'assistant_sql');
                                        if (stored) {
                                          setSuggestedSql(null);
                                          setRejectingIndex(null);
                                        }
                                      }
                                    }}
                                    disabled={loading}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium"
                                  >
                                    <CheckCircle2 className="h-3 w-3" />
                                    Use this SQL
                                  </button>
                                )}
                              </div>
                            )}
                            <div className="pt-2 border-t border-slate-200">
                              <label className="text-xs font-medium text-slate-700 block mb-1">Enter SQL manually:</label>
                              <textarea
                                value={manualSql}
                                onChange={(e) => setManualSql(e.target.value)}
                                placeholder="SELECT ... FROM ..."
                                className="w-full text-[11px] font-mono !text-gray-900 bg-white border border-slate-300 rounded p-2 min-h-[80px] resize-y"
                                rows={4}
                              />
                              {onApproveQuery && (
                                <button
                                  type="button"
                                  onClick={async () => {
                                    const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                    if (prevUser && manualSql.trim()) {
                                      const stored = await onApproveQuery(prevUser.content, manualSql.trim(), 'manual');
                                      if (stored) {
                                        setManualSql('');
                                        setRejectingIndex(null);
                                      }
                                    }
                                  }}
                                  disabled={loading || !manualSql.trim()}
                                  className="mt-1 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium disabled:opacity-50"
                                >
                                  <FileCode className="h-3 w-3" />
                                  Submit &amp; store
                                </button>
                              )}
                            </div>
                          </div>
                        {confirmedIndices.has(i) && (
                          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 text-xs font-medium">
                            <CheckCircle2 className="h-3.5 w-3.5" />
                            Stored for future use
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {/* When AI fails (no SQL executed): show Ask ChatGPT / Enter SQL directly */}
                  {m.role === 'assistant' && !m.meta?.sql && !m.meta?.needs_approval && !m.meta?.proposed_sql && (onSuggestSql || onApproveQuery) && messages[i - 1]?.role === 'user' && (
                    <div className="max-w-[92%] mt-2">
                      <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 space-y-3">
                        <p className="text-xs font-medium text-slate-700">AI couldn&apos;t find data. Train it:</p>
                        <div className="flex flex-wrap gap-2">
                          {onSuggestSql && (
                            <button
                              type="button"
                              onClick={async () => {
                                const prevUser = messages[i - 1];
                                if (!prevUser?.content) return;
                                setRejectingIndex(i);
                                setSuggestLoading(true);
                                try {
                                  const sql = await onSuggestSql(prevUser.content);
                                  setSuggestedSql(sql);
                                } catch (err) {
                                  console.error('Suggest failed:', err);
                                } finally {
                                  setSuggestLoading(false);
                                }
                              }}
                              disabled={suggestLoading || loading}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium disabled:opacity-50"
                            >
                              <Sparkles className="h-3 w-3" />
                              {suggestLoading ? 'Asking ChatGPT…' : 'Ask ChatGPT'}
                            </button>
                          )}
                        </div>
                        {rejectingIndex === i && suggestedSql && (
                          <div className="space-y-2 pt-2 border-t border-slate-200">
                            <pre className="text-[10px] bg-slate-900 text-slate-50 rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{suggestedSql.sql}</pre>
                            <ValidationNotes validation={suggestedSql.validation} />
                            {onApproveQuery && (
                              <button
                                type="button"
                                onClick={async () => {
                                  const prevUser = messages[i - 1];
                                  if (prevUser?.content) {
                                    const stored = await onApproveQuery(prevUser.content, suggestedSql.sql, suggestedSql.source === 'chatgpt' ? 'chatgpt' : 'assistant_sql');
                                    if (stored) {
                                      setSuggestedSql(null);
                                      setRejectingIndex(null);
                                    }
                                  }
                                }}
                                disabled={loading}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium"
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                Use this SQL
                              </button>
                            )}
                          </div>
                        )}
                        <div className="pt-2 border-t border-slate-200">
                          <label className="text-xs font-medium text-slate-700 block mb-1">Or enter SQL manually:</label>
                          <textarea
                            value={manualSql}
                            onChange={(e) => setManualSql(e.target.value)}
                            placeholder="SELECT ... FROM ..."
                            className="w-full text-[11px] font-mono !text-gray-900 bg-white border border-slate-300 rounded p-2 min-h-[80px] resize-y"
                            rows={4}
                          />
                          {onApproveQuery && (
                            <button
                              type="button"
                              onClick={async () => {
                                const prevUser = messages[i - 1];
                                if (prevUser?.content && manualSql.trim()) {
                                  const stored = await onApproveQuery(prevUser.content, manualSql.trim(), 'manual');
                                  if (stored) {
                                    setManualSql('');
                                    setRejectingIndex(null);
                                  }
                                }
                              }}
                              disabled={loading || !manualSql.trim()}
                              className="mt-1 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium disabled:opacity-50"
                            >
                              <FileCode className="h-3 w-3" />
                              Submit &amp; store
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  )}
                  {/* SQL confirmation for every successful query */}
                  {m.role === 'assistant' && m.meta?.sql && !m.meta?.needs_approval && (m.meta?.rows_preview?.length || m.meta?.sql) && (
                    <div className="max-w-[92%] mt-2 space-y-2">
                      {confirmedIndices.has(i) ? (
                        <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 text-xs font-medium">
                          <CheckCircle2 className="h-3.5 w-3.5" />
                          Stored for future use
                        </div>
                      ) : rejectingIndex === i ? (
                        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-3">
                          <div className="flex items-center justify-between">
                            <p className="text-xs font-medium text-amber-800">SQL incorrect. How would you like to fix it?</p>
                            <button
                              type="button"
                              onClick={() => { setRejectingIndex(null); setSuggestedSql(null); setManualSql(''); }}
                              className="text-[10px] text-amber-600 hover:text-amber-800 underline"
                            >
                              Cancel
                            </button>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={async () => {
                                const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                if (!prevUser || !onSuggestSql) return;
                                setSuggestLoading(true);
                                try {
                                  const sql = await onSuggestSql(prevUser.content);
                                  setSuggestedSql(sql);
                                } catch (err) {
                                  console.error('Suggest failed:', err);
                                } finally {
                                  setSuggestLoading(false);
                                }
                              }}
                              disabled={suggestLoading || loading}
                              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium disabled:opacity-50"
                            >
                              <Sparkles className="h-3 w-3" />
                              {suggestLoading ? 'Asking ChatGPT…' : 'Ask ChatGPT'}
                            </button>
                          </div>
                          {suggestedSql && (
                            <div className="space-y-2">
                              <pre className="text-[10px] bg-slate-900 text-slate-50 rounded p-2 overflow-auto max-h-32 whitespace-pre-wrap">{suggestedSql.sql}</pre>
                              <ValidationNotes validation={suggestedSql.validation} />
                              <button
                                type="button"
                                onClick={async () => {
                                  const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                  if (prevUser && onApproveQuery) {
                                    const stored = await onApproveQuery(prevUser.content, suggestedSql.sql, suggestedSql.source === 'chatgpt' ? 'chatgpt' : 'assistant_sql');
                                    if (stored) {
                                      setSuggestedSql(null);
                                      setRejectingIndex(null);
                                    }
                                  }
                                }}
                                disabled={loading}
                                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-emerald-600 text-white text-xs font-medium"
                              >
                                <CheckCircle2 className="h-3 w-3" />
                                Use this SQL
                              </button>
                            </div>
                          )}
                          <div className="pt-2 border-t border-amber-200">
                            <label className="text-xs font-medium text-amber-800 block mb-1">Or enter SQL manually:</label>
                            <textarea
                              value={manualSql}
                              onChange={(e) => setManualSql(e.target.value)}
                              placeholder="SELECT ... FROM ..."
                              className="w-full text-[11px] font-mono !text-gray-900 bg-white border border-amber-300 rounded p-2 min-h-[80px] resize-y"
                              rows={4}
                            />
                            <button
                              type="button"
                              onClick={async () => {
                                const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                                if (prevUser && manualSql.trim() && onApproveQuery) {
                                  const stored = await onApproveQuery(prevUser.content, manualSql.trim(), 'manual');
                                  if (stored) {
                                    setManualSql('');
                                    setRejectingIndex(null);
                                  }
                                }
                              }}
                              disabled={loading || !manualSql.trim()}
                              className="mt-1 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-slate-700 hover:bg-slate-800 text-white text-xs font-medium disabled:opacity-50"
                            >
                              <FileCode className="h-3 w-3" />
                              Submit &amp; store
                            </button>
                          </div>
                        </div>
                      ) : onStoreQuery ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-600">Is this SQL correct?</span>
                          <button
                            type="button"
                            onClick={async () => {
                              const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                              if (prevUser && m.meta?.sql) {
                                try {
                                  await onStoreQuery(prevUser.content, m.meta.sql);
                                  setConfirmedIndices((s) => new Set(s).add(i));
                                } catch (err) {
                                  console.error('Store failed:', err);
                                }
                              }
                            }}
                            disabled={loading}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-medium disabled:opacity-50"
                          >
                            <CheckCircle2 className="h-3 w-3" />
                            Yes
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const prevUser = messages.slice(0, i).reverse().find(x => x.role === 'user');
                              void recordRejection(prevUser?.content, m.meta?.sql, 'assistant_sql');
                              setRejectingIndex(i);
                              setSuggestedSql(null);
                              setManualSql('');
                            }}
                            disabled={loading}
                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-red-100 hover:bg-red-200 text-red-700 text-xs font-medium disabled:opacity-50"
                          >
                            <XCircle className="h-3 w-3" />
                            No
                          </button>
                        </div>
                      ) : null}
                    </div>
                  )}
                  {/* Show SQL and data info for assistant messages */}
                  {m.role === 'assistant' && m.meta && (
                    <div className="max-w-[92%] mt-1 text-[10px] font-mono text-slate-400 px-1 space-y-0.5">
                      {/* Period Information */}
                      {m.meta.period_info && (
                        <div className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 text-blue-700 px-2 py-1 rounded-md mb-1">
                          <CalendarRange className="h-3 w-3" />
                          <span className="font-semibold">{m.meta.period_info}</span>
                          {m.meta.date_range && (
                            <span className="text-blue-600">
                              ({m.meta.date_range.min_date} to {m.meta.date_range.max_date})
                            </span>
                          )}
                        </div>
                      )}
                      <div>
                        {m.meta.action && <span>Action: {m.meta.action}</span>}
                        {m.meta.reason && <span> • Reason: {m.meta.reason}</span>}
                        {m.meta.sql && <span> • SQL executed</span>}
                        {m.meta.rows_preview && <span> • {m.meta.rows_preview.length} rows</span>}
                        {m.meta.charts && <span> • {m.meta.charts.length} chart(s)</span>}
                      </div>
                      {m.meta.sql && (
                        <details className="mt-0.5">
                          <summary className="cursor-pointer text-[10px] text-blue-600 underline">
                            View SQL query
                          </summary>
                          <pre className="mt-1 max-h-40 overflow-auto text-[10px] bg-slate-900 text-slate-50 rounded p-2 whitespace-pre-wrap">
                            {m.meta.sql}
                          </pre>
                        </details>
                      )}
                      <ValidationNotes validation={m.meta.validation} />
                      {m.meta.performance && (
                        <div className="text-slate-500">
                          ⏱ {(m.meta.performance.total_ms || 0) / 1000}s
                          {m.meta.performance.used_pattern && <span className="text-green-600"> • pattern-matched</span>}
                          {m.meta.performance.used_cache && <span className="text-blue-600"> • cached</span>}
                          {m.meta.performance.sql_execution_ms && (
                            <span> • sql: {m.meta.performance.sql_execution_ms}ms</span>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                  {m.meta?.multiModel && <MultiModelComparison result={m.meta.multiModel} />}
                  {/* On small screens, show charts inline below message */}
                  {m.meta?.charts && m.meta.charts.length > 0 && (
                    <div className={`${chartPanelBreakpoint === 'md' ? 'md:hidden' : 'lg:hidden'} w-full mt-2`}>
                      <AIChartRenderer charts={m.meta.charts} />
                    </div>
                  )}
                </div>
              ))
            )}
            {loading && (
              <div className="flex items-center gap-2 text-xs text-slate-400 font-mono">
                <div className="flex gap-0.5">
                  {[0, 1, 2].map((i) => (
                    <span key={i} className="w-1 h-1 rounded-full bg-slate-400 animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }} />
                  ))}
                </div>
                Generating...
              </div>
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {/* Charts panel — shows at md+ for fullWidth, lg+ otherwise */}
        {hasCharts && (
          <div className={`${chartPanelBreakpoint === 'md' ? 'hidden md:flex' : 'hidden lg:flex'} flex-col w-[55%] border-l border-slate-100 bg-gradient-to-br from-slate-50 to-white overflow-hidden`}>
            <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0 bg-white/90 backdrop-blur-sm sticky top-0 z-10">
              <BarChart3 className="h-4 w-4 text-blue-600" />
              <h3 className="text-sm font-semibold text-slate-900">Visualizations</h3>
              <span className="ml-auto text-[10px] font-mono text-slate-400">{messagesWithCharts.length} chart{messagesWithCharts.length > 1 ? 's' : ''}</span>
            </div>
            <div className="flex-1 overflow-y-auto p-4 space-y-6">
              {messagesWithCharts.map((m, idx) => (
                <div key={idx} className="space-y-2">
                  {messagesWithCharts.length > 1 && (
                    <div className="text-[10px] font-mono text-slate-400 uppercase tracking-widest px-1">
                      Query {messages.indexOf(m)} {m.ts ? `· ${new Date(m.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}
                    </div>
                  )}
                  {m.meta?.charts && <AIChartRenderer charts={m.meta.charts} />}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Voice / error notices */}
      {voiceError && (
        <div className="mx-3 mb-1 rounded-lg bg-amber-50 border border-amber-200 px-3 py-1.5 text-xs text-amber-700">
          {voiceError}
        </div>
      )}
      {isListening && (
        <div className="mx-3 mb-1 rounded-lg bg-blue-50 border border-blue-100 px-3 py-1.5 text-xs text-blue-700 flex items-center gap-2">
          <div className="flex gap-0.5">
            {[0, 1, 2].map((i) => (
              <span key={i} className="w-0.5 h-3 bg-blue-500 rounded-full animate-pulse"
                style={{ animationDelay: `${i * 120}ms` }} />
            ))}
          </div>
          Listening…
        </div>
      )}

      {/* Input area */}
      <div className="px-3 pt-2 pb-2 border-t border-slate-100">
        {/* Toggles row */}
        <div className="flex items-center gap-3 mb-1.5">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" checked={useContext} onChange={(e) => setUseContext(e.target.checked)}
              className="rounded border-slate-300 text-slate-800 focus:ring-slate-500 w-3 h-3" />
            <span className="text-[11px] text-slate-500 font-medium">Context</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input type="checkbox" checked={useMultiModel} onChange={(e) => setUseMultiModel(e.target.checked)}
              className="rounded border-slate-300 text-slate-800 focus:ring-slate-500 w-3 h-3" />
            <span className="text-[11px] text-slate-500 font-medium">Multi-model</span>
          </label>
        </div>
        {/* Input row */}
        <div className="flex gap-1.5">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder={placeholder}
            className="flex-1 min-w-0 rounded-xl border border-slate-200 text-sm py-2 px-3 text-slate-900 placeholder:text-slate-400 bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-60 transition-shadow"
            disabled={loading}
          />
          {isVoiceSupported && (
            <button
              type="button"
              onClick={toggleVoice}
              disabled={loading}
              className={`flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center transition-all ${
                isListening ? 'bg-red-500 text-white animate-pulse' : 'bg-slate-100 hover:bg-slate-200 text-slate-600'
              }`}
            >
              {isListening ? <MicOff className="h-3.5 w-3.5" /> : <Mic className="h-3.5 w-3.5" />}
            </button>
          )}
          <button
            type="button"
            onClick={() => submit()}
            disabled={loading || !input.trim()}
            className="flex-shrink-0 h-9 px-3.5 bg-gradient-to-r from-blue-600 to-indigo-700 text-white rounded-xl hover:from-blue-700 hover:to-indigo-800 disabled:opacity-40 disabled:cursor-not-allowed transition-all flex items-center gap-1.5 text-sm font-medium shadow-sm"
          >
            {loading
              ? <div className="h-3.5 w-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
              : <Send className="h-3.5 w-3.5" />}
            <span className="hidden sm:inline text-xs">Send</span>
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════════════════════════════ */

export default function DashboardAIAnalysis() {
  const [activeSection, setActiveSection] = useState<'realtime' | 'historical'>('realtime');
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [historicalDays, setHistoricalDays] = useState(90);

  const [realtimeMessages, setRealtimeMessages] = useState<Message[]>([]);
  const [historicalMessages, setHistoricalMessages] = useState<Message[]>([]);

  const [realtimeLoading, setRealtimeLoading] = useState(false);
  const [historicalLoading, setHistoricalLoading] = useState(false);

  const [useContext, setUseContext] = useState(true);
  const [useMultiModel, setUseMultiModel] = useState(false);

  const [outboundData, setOutboundData] = useState<OutboundData | null>(null);
  const [inboundData, setInboundData] = useState<InboundData | null>(null);
  const [businessData, setBusinessData] = useState<BusinessData | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);
  
  // Time scope modal state
  const [showTimeScopeModal, setShowTimeScopeModal] = useState(false);
  const [pendingQuery, setPendingQuery] = useState<{ section: 'realtime' | 'historical'; text: string } | null>(null);
  const [timeScope, setTimeScope] = useState<'current' | 'historical' | 'both'>('current');

  /* ── Data fetch ─────────────────────────────────────────── */

  const fetchData = async (d: number) => {
    setDataLoading(true);
    try {
      const [outbound, inbound, business] = await Promise.all([
        dashboardApi.getV2Outbound(d),
        dashboardApi.getV2Inbound(d),
        dashboardApi.getV2Business(d),
      ]);
      setOutboundData(outbound || null);
      setInboundData(inbound || null);
      setBusinessData(business || null);
    } catch { /* silently fail */ }
    finally { setDataLoading(false); }
  };

  useEffect(() => { fetchData(days); }, [days]);

  /* ── Send helpers ───────────────────────────────────────── */

  const sendMessage = async (section: 'realtime' | 'historical', text: string, selectedTimeScope?: 'current' | 'historical' | 'both') => {
    const isRT = section === 'realtime';
    const setLoading = isRT ? setRealtimeLoading : setHistoricalLoading;
    const setMsgs = isRT ? setRealtimeMessages : setHistoricalMessages;
    const currentMsgs = isRT ? realtimeMessages : historicalMessages;
    const d = isRT ? days : historicalDays;

    setError(null);
    setMsgs((prev) => [...prev, { role: 'user', content: text, section, ts: Date.now() }]);
    setLoading(true);

    const contextKeys = useContext ? AI_CONTEXT_KEYS : [];
    const scopeToUse = selectedTimeScope || timeScope;

    try {
      if (useMultiModel) {
        const res = await dashboardApi.postAIAnalysisMultiModel(text, contextKeys, d, scopeToUse);
        setMsgs((prev) => [...prev, {
          role: 'assistant', content: res.synthesized_answer,
          meta: { 
            multiModel: res,
            time_scope: res.time_scope,
            date_range: res.date_range,
            period_info: res.period_info,
          }, 
          section, 
          ts: Date.now(),
        }]);
      } else {
        const history = currentMsgs.map((m) => ({ role: m.role, content: m.content }));
        const res = await dashboardApi.postAIAnalysisChat(text, history, contextKeys, d, scopeToUse);

        console.log('📊 AI Analysis Response:', res);
        if (res?.sql) {
          console.log('🧠 Generated SQL:', res.sql);
        }

        const reply = res?.reply ?? 'No response received.';
        const meta: AiAnalysisMeta = {
          action: res?.action,
          reason: res?.reason,
          sql: res?.sql,
          validation: res?.validation,
          proposed_validation: res?.proposed_validation,
          query_origin: res?.query_origin,
          suggestion_source: res?.suggestion_source,
          rows_preview: res?.rows_preview,
          compare: res?.compare,
          charts: res?.charts,
          time_scope: res?.time_scope,
          date_range: res?.date_range,
          period_info: res?.period_info,
          needs_approval: res?.needs_approval,
          proposed_sql: res?.proposed_sql,
        };

        console.log('📊 Period Info:', meta.period_info, meta.date_range);
        console.log('📊 Extracted Charts:', meta.charts);
        console.log('📊 Has Charts:', Boolean(meta.charts && meta.charts.length > 0));

        const hasMeta = Boolean(meta.action || meta.sql || meta.validation || (meta.rows_preview?.length) || (meta.charts?.length) || meta.period_info || meta.needs_approval);
        setMsgs((prev) => [...prev, {
          role: 'assistant', content: reply,
          meta: hasMeta ? meta : undefined, section, ts: Date.now(),
        }]);
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to get AI response.';
      setError(msg);
      setMsgs((prev) => [...prev, { role: 'assistant', content: `Error: ${msg}`, section, ts: Date.now() }]);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveQuery = async (
    section: 'realtime' | 'historical',
    question: string,
    proposedSql: string,
    approvalSource: 'chatgpt' | 'manual' | 'assistant_sql' = 'chatgpt',
  ): Promise<boolean> => {
    const setMsgs = section === 'realtime' ? setRealtimeMessages : setHistoricalMessages;
    const setLoading = section === 'realtime' ? setRealtimeLoading : setHistoricalLoading;
    setLoading(true);
    setError(null);
    try {
      const res = await dashboardApi.postAIAnalysisApproveQuery(question, proposedSql, timeScope, approvalSource);
      const meta: AiAnalysisMeta = {
        action: res?.action,
        reason: res?.reason,
        sql: res?.sql,
        validation: res?.validation,
        proposed_validation: res?.proposed_validation,
        query_origin: res?.query_origin,
        suggestion_source: res?.suggestion_source,
        rows_preview: res?.rows_preview,
        charts: res?.charts,
        time_scope: res?.time_scope,
        date_range: res?.date_range,
        period_info: res?.period_info,
        needs_approval: res?.needs_approval,
        proposed_sql: res?.proposed_sql,
      };
      setMsgs((prev) => [...prev, {
        role: 'assistant',
        content: res?.reply ?? 'Query executed and stored for future use.',
        meta: (meta.sql || meta.validation || meta.rows_preview?.length || meta.needs_approval) ? meta : undefined,
        section,
        ts: Date.now(),
      }]);
      return !Boolean(res?.needs_approval);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to approve query.';
      setError(msg);
      setMsgs((prev) => [...prev, { role: 'assistant', content: `Error: ${msg}`, section, ts: Date.now() }]);
      return false;
    } finally {
      setLoading(false);
    }
  };

  const handleStoreQuery = async (section: 'realtime' | 'historical', question: string, sql: string) => {
    setError(null);
    try {
      await dashboardApi.postAIAnalysisStoreQuery(question, sql, timeScope, 'assistant_sql');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to store query.';
      setError(msg);
      throw err;
    }
  };

  const handleSuggestSql = async (section: 'realtime' | 'historical', question: string): Promise<SuggestedSqlResult> => {
    const res = await dashboardApi.postAIAnalysisSuggestSql(question, timeScope);
    return {
      sql: res?.proposed_sql ?? '',
      source: res?.suggestion_source,
      validation: res?.validation,
    };
  };

  const handleRejectQuery = async (
    section: 'realtime' | 'historical',
    question: string,
    rejectedSql: string,
    attemptSource: 'chatgpt' | 'manual' | 'assistant_sql' = 'assistant_sql',
  ) => {
    await dashboardApi.postAIAnalysisRejectQuery(question, rejectedSql, timeScope, attemptSource);
  };

  /* ── Derived stats ───────────────────────────────────────── */

  const f = outboundData?.funnel;
  const successRate = f && f.documents_received > 0
    ? Math.round((f.converted_success / f.documents_received) * 100) : null;
  const failRate = f && f.documents_received > 0
    ? Math.round(((f.validated_failed + f.converted_failed) / f.documents_received) * 100) : null;

  /* ══════════════════════════════════════════════════════════
     RENDER
  ════════════════════════════════════════════════════════════ */

  return (
    <div className="w-full -m-4 sm:-m-6 min-h-screen bg-gray-50 font-sans flex flex-col">
      {/* Time Scope Selection Modal */}
      {showTimeScopeModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4" onClick={() => setShowTimeScopeModal(false)}>
          <div className="bg-white rounded-2xl shadow-2xl max-w-md w-full p-6" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-3 mb-4">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center">
                <CalendarRange className="h-5 w-5 text-white" />
              </div>
              <div>
                <h3 className="text-lg font-bold text-slate-900">Select Data Scope</h3>
                <p className="text-xs text-slate-500">Choose which period to analyze</p>
              </div>
            </div>

            <div className="space-y-3 mb-6">
              {/* Current Period Option */}
              <label className="flex items-start gap-3 p-4 border-2 border-slate-200 rounded-xl cursor-pointer hover:border-blue-500 hover:bg-blue-50/50 transition-all group">
                <input
                  type="radio"
                  name="timeScope"
                  value="current"
                  checked={timeScope === 'current'}
                  onChange={(e) => setTimeScope(e.target.value as any)}
                  className="mt-0.5 w-4 h-4 text-blue-600 border-slate-300 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <Clock className="h-4 w-4 text-blue-600" />
                    <span className="font-semibold text-slate-900">Current Period</span>
                  </div>
                  <p className="text-xs text-slate-600">Analyze recent data (default: last 30 days)</p>
                </div>
              </label>

              {/* Historical Period Option */}
              <label className="flex items-start gap-3 p-4 border-2 border-slate-200 rounded-xl cursor-pointer hover:border-blue-500 hover:bg-blue-50/50 transition-all group">
                <input
                  type="radio"
                  name="timeScope"
                  value="historical"
                  checked={timeScope === 'historical'}
                  onChange={(e) => setTimeScope(e.target.value as any)}
                  className="mt-0.5 w-4 h-4 text-blue-600 border-slate-300 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <BarChart3 className="h-4 w-4 text-indigo-600" />
                    <span className="font-semibold text-slate-900">Historical Data</span>
                  </div>
                  <p className="text-xs text-slate-600">Long-term trends and patterns (1994-2010)</p>
                </div>
              </label>

              {/* Both Option */}
              <label className="flex items-start gap-3 p-4 border-2 border-slate-200 rounded-xl cursor-pointer hover:border-blue-500 hover:bg-blue-50/50 transition-all group">
                <input
                  type="radio"
                  name="timeScope"
                  value="both"
                  checked={timeScope === 'both'}
                  onChange={(e) => setTimeScope(e.target.value as any)}
                  className="mt-0.5 w-4 h-4 text-blue-600 border-slate-300 focus:ring-blue-500"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <GitBranch className="h-4 w-4 text-purple-600" />
                    <span className="font-semibold text-slate-900">Both Periods</span>
                  </div>
                  <p className="text-xs text-slate-600">Compare historical and current data</p>
                </div>
              </label>
            </div>

            <div className="flex gap-2">
              <button
                onClick={() => setShowTimeScopeModal(false)}
                className="flex-1 px-4 py-2.5 rounded-xl border border-slate-300 text-slate-700 font-medium hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  if (pendingQuery) {
                    sendMessage(pendingQuery.section, pendingQuery.text, timeScope);
                    setShowTimeScopeModal(false);
                    setPendingQuery(null);
                  }
                }}
                className="flex-1 px-4 py-2.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-700 text-white font-semibold hover:shadow-lg transition-all flex items-center justify-center gap-2"
              >
                <Sparkles className="h-4 w-4" />
                Analyze
              </button>
            </div>
          </div>
        </div>
      )}

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        body { font-family: 'DM Sans', sans-serif; }
        .font-mono, [class*="font-mono"] { font-family: 'IBM Plex Mono', monospace !important; }
        .tab-pill { transition: background 0.2s, color 0.2s, box-shadow 0.2s; }
        .tab-pill.active {
          background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
          color: #ffffff;
          box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
        }
        .tab-pill:not(.active):hover { background: rgba(241, 245, 249, 0.8); }
        .fade-in { animation: fadeUp 0.3s ease both; }
        @keyframes fadeUp { from { opacity:0; transform: translateY(6px); } to { opacity:1; transform: none; } }
      `}</style>

      {/* ── Header ── */}
      <header className="sticky top-0 z-20 bg-white border-b border-slate-200 shadow-sm flex-shrink-0">
        <div className="w-full px-4 md:px-6 lg:px-8 h-14 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-md">
                <Zap className="h-3.5 w-3.5 text-white" />
              </div>
              <span className="font-mono text-sm font-bold text-slate-900 hidden sm:inline">Intelligence</span>
            </div>
            <div className="flex items-center gap-0.5 bg-slate-200 rounded-full p-0.5">
              {[
                { key: 'realtime', label: 'Real-time', icon: Activity },
                { key: 'historical', label: 'Historical', icon: BarChart3 },
              ].map(({ key, label, icon: Icon }) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setActiveSection(key as 'realtime' | 'historical')}
                  className={`tab-pill flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium ${activeSection === key ? 'active' : 'text-slate-600'}`}
                >
                  <Icon className="h-3 w-3" />
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 text-xs text-slate-500">
              <Clock className="h-3 w-3" />
              <select
                value={activeSection === 'realtime' ? days : historicalDays}
                onChange={(e) => {
                  const v = Number(e.target.value);
                  activeSection === 'realtime' ? setDays(v) : setHistoricalDays(v);
                }}
                className="bg-transparent font-mono text-xs text-slate-700 focus:outline-none cursor-pointer"
              >
                {activeSection === 'realtime'
                  ? [7, 30, 90].map((d) => <option key={d} value={d}>{d}d</option>)
                  : [90, 180, 365].map((d) => <option key={d} value={d}>{d}d</option>)}
              </select>
            </div>
            <button
              type="button"
              onClick={() => fetchData(days)}
              disabled={dataLoading}
              className="w-8 h-8 rounded-lg bg-white border border-slate-200 flex items-center justify-center text-slate-500 hover:text-slate-800 hover:border-slate-400 transition-all disabled:opacity-50"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${dataLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>
      </header>

      {/* ── Main content ── */}
      <main className="flex-1 w-full px-4 md:px-6 lg:px-8 py-4 overflow-y-auto">

        {/* ═══════════════════════════
            REAL-TIME SECTION
        ═══════════════════════════ */}
        {activeSection === 'realtime' && (
          <div className="fade-in flex flex-col gap-4">

            {/* Section title + KPIs */}
            <div className="flex-shrink-0 space-y-3">
              <div className="flex items-center gap-3">
                <LivePulse />
                <h1 className="text-sm font-semibold text-slate-900">Real-time Monitor</h1>
                <span className="text-xs font-mono text-slate-400">Last {days} days</span>
              </div>

              {/* KPI row */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5">
                {dataLoading ? (
                  Array(4).fill(0).map((_, i) => (
                    <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                  ))
                ) : (
                  <>
                    <StatCard accent label="Docs received" value={f?.documents_received ?? 0} />
                    <StatCard label="Validated OK" value={f?.validated_success ?? 0}
                      sub={f?.validated_failed ? <span className="text-red-500 font-mono font-semibold">{f.validated_failed} failed</span> : <CheckCircle2 className="h-3 w-3 text-emerald-500" />} />
                    <StatCard label="Converted OK" value={f?.converted_success ?? 0}
                      sub={f?.converted_pending ? <span className="text-amber-500 font-mono font-semibold">{f.converted_pending} pending</span> : undefined} />
                    <StatCard label="Success rate" value={successRate !== null ? `${successRate}%` : '—'}
                      sub={failRate !== null && failRate > 0 ? <span className="text-red-500 font-mono font-semibold">{failRate}% fail</span> : undefined} />
                  </>
                )}
              </div>
            </div>

            {/* Data panels row: Inbound + Outbound side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">

              {/* Inbound SAT */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowUpFromLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Inbound (SAT)</h2>
                  </div>
                  <LivePulse />
                </div>
                <div className="p-3 space-y-3 overflow-y-auto max-h-72 md:max-h-80">
                  {dataLoading ? (
                    <>{Array(3).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : inboundData?.summary ? (
                    <>
                      <div className="grid grid-cols-3 gap-1.5 text-center">
                        {[
                          { v: inboundData.summary.total_documents, l: 'Total' },
                          { v: inboundData.summary.merges_sent_to_sap, l: 'In SAP' },
                          { v: inboundData.summary.merges_pending, l: 'Pending' },
                        ].map(({ v, l }) => (
                          <div key={l} className="rounded-lg bg-slate-50 py-2">
                            <div className="font-mono font-bold text-base text-slate-900 leading-none">{fmt(v)}</div>
                            <div className="text-[9px] text-slate-500 font-mono uppercase tracking-wide mt-0.5">{l}</div>
                          </div>
                        ))}
                      </div>
                      {inboundData.top_suppliers?.slice(0, 8).map((s, i) => (
                        <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
                          <span className="text-xs text-slate-700 truncate flex-1 mr-3">{s.supplier_name || s.supplier_rfc}</span>
                          <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{fmt(s.count)}</span>
                        </div>
                      ))}
                    </>
                  ) : (
                    <p className="text-xs text-slate-400 py-4 text-center">No inbound data</p>
                  )}
                </div>
              </div>

              {/* Outbound funnel */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowDownToLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Outbound Funnel</h2>
                  </div>
                  <GitBranch className="h-3.5 w-3.5 text-slate-400" />
                </div>
                <div className="p-3 space-y-2.5 overflow-y-auto max-h-72 md:max-h-80">
                  {dataLoading ? (
                    <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : f ? (
                    <>
                      <div className="space-y-2">
                        <FunnelStep step={1} label="Received" count={f.documents_received} total={f.documents_received} />
                        <FunnelStep step={2} label="Validated ✓" count={f.validated_success} total={f.documents_received} />
                        <FunnelStep step={3} label="Validation ✗" count={f.validated_failed} total={f.documents_received} warn />
                        <FunnelStep step={4} label="Converted ✓" count={f.converted_success} total={f.documents_received} />
                        <FunnelStep step={5} label="Converted ✗" count={f.converted_failed} total={f.documents_received} warn />
                        <FunnelStep step={6} label="Pending" count={f.converted_pending} total={f.documents_received} />
                      </div>
                      {outboundData?.top_customers?.length ? (
                        <div className="pt-2 border-t border-slate-100">
                          <div className="text-[9px] font-mono uppercase tracking-widest text-slate-400 mb-1.5">Top customers</div>
                          {outboundData.top_customers.slice(0, 5).map((c, i) => (
                            <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-50 last:border-0">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-2">{c.customer_name || c.customer_id}</span>
                              <span className="font-mono text-[10px] text-slate-400 mr-2 flex-shrink-0">{c.currency}</span>
                              <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{c.count}</span>
                            </div>
                          ))}
                        </div>
                      ) : null}
                    </>
                  ) : (
                    <p className="text-xs text-slate-400 py-4 text-center">No outbound data</p>
                  )}
                </div>
              </div>
            </div>

            {/* AI Chat — full width below data panels */}
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col" style={{ minHeight: '420px' }}>
              <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                <Sparkles className="h-3.5 w-3.5 text-blue-600" />
                <h2 className="text-xs font-semibold text-slate-900">AI Analysis</h2>
                <LivePulse />
                <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Real-time</span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                <ChatPanel
                  section="realtime"
                  messages={realtimeMessages}
                  loading={realtimeLoading}
                  prompts={REALTIME_PROMPTS}
                  onSend={(t) => {
                    setPendingQuery({ section: 'realtime', text: t });
                    setShowTimeScopeModal(true);
                  }}
                  onApproveQuery={(q, s, source) => handleApproveQuery('realtime', q, s, source)}
                  onRejectQuery={(q, s, source) => handleRejectQuery('realtime', q, s, source)}
                  onStoreQuery={(q, s) => handleStoreQuery('realtime', q, s)}
                  onSuggestSql={(q) => handleSuggestSql('realtime', q)}
                  placeholder="Ask about live invoices, SAT docs, failures…"
                  useContext={useContext}
                  setUseContext={setUseContext}
                  useMultiModel={useMultiModel}
                  setUseMultiModel={setUseMultiModel}
                  fullWidth
                />
              </div>
            </div>

            {error && (
              <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>
        )}

        {/* ═══════════════════════════
            HISTORICAL SECTION
        ═══════════════════════════ */}
        {activeSection === 'historical' && (
          <div className="fade-in h-full flex flex-col gap-4">

            {/* Title + Revenue cards */}
            <div className="flex-shrink-0 space-y-3">
              <div className="flex items-center gap-3">
                <CalendarRange className="h-4 w-4 text-slate-600" />
                <h1 className="text-sm font-semibold text-slate-900">Historical Analysis &amp; Forecasting</h1>
                <span className="text-xs font-mono text-slate-400">Last {historicalDays} days</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                {dataLoading ? (
                  Array(3).fill(0).map((_, i) => (
                    <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                  ))
                ) : (
                  <>
                    <StatCard accent label="Current period revenue"
                      value={businessData?.trend?.current_period_revenue ?? 0}
                      sub={businessData?.trend && <TrendBadge pct={businessData.trend.revenue_change_pct} />}
                    />
                    <StatCard label="Previous period"
                      value={businessData?.trend?.previous_period_revenue ?? 0}
                    />
                    <StatCard label="Revenue change"
                      value={businessData?.trend ? `${businessData.trend.revenue_change_pct >= 0 ? '+' : ''}${businessData.trend.revenue_change_pct}%` : '—'}
                      sub={
                        businessData?.trend
                          ? businessData.trend.revenue_change_pct >= 0
                            ? <span className="text-emerald-600 font-mono">↑ Positive trend</span>
                            : <span className="text-red-500 font-mono">↓ Declining</span>
                          : undefined
                      }
                    />
                  </>
                )}
              </div>
            </div>

            {/* 3-col layout: revenue by customer | revenue by country | AI chat (2x) */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_1fr_2fr] gap-3 overflow-hidden">

              {/* Revenue by customer */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <TrendingUp className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Customer</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(6).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : businessData?.revenue_by_customer?.length ? (
                    <div className="space-y-2">
                      {businessData.revenue_by_customer.slice(0, 10).map((c, i) => {
                        const max = businessData.revenue_by_customer![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-3">{c.customer_name || c.customer_id}</span>
                              <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{fmt(c.total_revenue)}</span>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-blue-600 to-indigo-700 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No revenue data</p>
                  )}
                </div>
              </div>

              {/* Revenue by country */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <Eye className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Country</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : businessData?.revenue_by_country?.length ? (
                    <div className="space-y-2">
                      {businessData.revenue_by_country.slice(0, 10).map((c, i) => {
                        const max = businessData.revenue_by_country![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-2">{c.country_name || c.country}</span>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                <span className="font-mono text-[10px] text-slate-400">{c.invoice_count}</span>
                                <span className="font-mono text-xs font-semibold text-slate-900">{fmt(c.total_revenue)}</span>
                              </div>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-blue-500 to-indigo-600 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No country data</p>
                  )}
                </div>
              </div>

              {/* AI Trend Analysis */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <FlaskConical className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">AI Trend Analysis &amp; Forecasting</h2>
                  <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Historical</span>
                </div>

                {/* Quick action tiles */}
                <div className="px-3 pt-2.5 pb-0 grid grid-cols-2 md:grid-cols-5 gap-2 flex-shrink-0">
                  {[
                    { label: 'Profit margin', query: 'Show profit margin by product for all products in the database', icon: DollarSign },
                    { label: 'Forecast', query: 'Based on historical patterns, forecast next period revenue and invoice volume', icon: TrendingUp },
                    { label: 'Compare periods', query: 'Compare current period performance to the previous period with key insights', icon: BarChart3 },
                    { label: 'Anomalies', query: 'Identify any anomalies or unusual patterns in the historical data', icon: AlertTriangle },
                    { label: 'Growth drivers', query: 'What are the main drivers of revenue growth or decline in the historical data?', icon: TrendingDown },
                  ].map(({ label, query, icon: Icon }) => (
                    <button
                      key={label}
                      type="button"
                      onClick={() => sendMessage('historical', query)}
                      disabled={historicalLoading}
                      className="rounded-xl border border-slate-200 bg-slate-50 hover:bg-gradient-to-br hover:from-blue-600 hover:to-indigo-700 hover:border-blue-600 hover:text-white text-slate-700 px-2 py-2 text-left transition-all group disabled:opacity-50 hover:shadow-md flex items-center gap-1.5"
                    >
                      <Icon className="h-3 w-3 flex-shrink-0 group-hover:text-white transition-colors" />
                      <span className="text-[11px] font-medium leading-tight">{label}</span>
                    </button>
                  ))}
                </div>

                <div className="flex-1 min-h-0 overflow-hidden flex flex-col mt-1">
                  <ChatPanel
                    section="historical"
                    messages={historicalMessages}
                    loading={historicalLoading}
                    prompts={HISTORICAL_PROMPTS}
                    onSend={(t) => {
                      setPendingQuery({ section: 'historical', text: t });
                      setShowTimeScopeModal(true);
                    }}
                    onApproveQuery={(q, s, source) => handleApproveQuery('historical', q, s, source)}
                    onRejectQuery={(q, s, source) => handleRejectQuery('historical', q, s, source)}
                    onStoreQuery={(q, s) => handleStoreQuery('historical', q, s)}
                    onSuggestSql={(q) => handleSuggestSql('historical', q)}
                    placeholder="Ask about trends, forecasts, period comparisons…"
                    useContext={useContext}
                    setUseContext={setUseContext}
                    useMultiModel={useMultiModel}
                    setUseMultiModel={setUseMultiModel}
                  />
                </div>
              </div>
            </div>

            {error && (
              <div className="flex-shrink-0 rounded-xl bg-red-50 border border-red-200 px-4 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
