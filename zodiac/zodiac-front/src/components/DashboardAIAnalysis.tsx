'use client';

import { useState, useRef, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import {
  Sparkles, Send, ArrowDownToLine, ArrowUpFromLine, TrendingUp,
  GitBranch, RefreshCw, Mic, MicOff,
  Activity, BarChart3, Clock, Zap, AlertTriangle, CheckCircle2,
  ArrowUpRight, ArrowDownRight, Minus, CalendarRange, Eye,
  FlaskConical, TrendingDown, ChevronDown, ChevronUp,
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
  { label: 'Revenue trend', query: 'Summarize revenue by customer and by country with trend analysis' },
  { label: 'Flow deviation', query: 'How does my current document flow deviate from the standard process?' },
  { label: 'Period forecast', query: 'Based on historical patterns, forecast next period revenue and invoice volume' },
  { label: 'Anomaly detection', query: 'Identify any anomalies or unusual patterns in the historical data' },
];

/* ─── Types ───────────────────────────────────────────────────── */

type AiAnalysisMeta = {
  action?: string; reason?: string; sql?: string;
  rows_preview?: Record<string, unknown>[];
  compare?: unknown; charts?: any[]; multiModel?: any;
  time_scope?: string;
  date_range?: { min_date: string; max_date: string };
  period_info?: string;
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

type Message = {
  role: 'user' | 'assistant';
  content: string;
  meta?: AiAnalysisMeta;
  section?: 'realtime' | 'historical' | 'both';
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

type SAPHistoricalData = {
  period: { start_date: string; end_date: string };
  revenue_trend: {
    year: number;
    quarter?: string;
    total_revenue: number;
    invoice_count: number;
  }[];
  revenue_by_customer: {
    customer_id: string;
    customer_name: string;
    country: string;
    total_revenue: number;
    invoice_count: number;
  }[];
  revenue_by_product: {
    product_id: string;
    product_name: string;
    total_revenue: number;
    quantity: number;
  }[];
  revenue_by_country: {
    country: string;
    total_revenue: number;
    invoice_count: number;
  }[];
  revenue_by_industry: {
    industry: string;
    total_revenue: number;
    invoice_count: number;
  }[];
  summary: {
    total_revenue: number;
    total_invoices: number;
    unique_customers: number;
    unique_products: number;
    date_range: { min: string; max: string };
  };
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
  placeholder,
  useContext,
  setUseContext,
  useMultiModel,
  setUseMultiModel,
  fullWidth = false,
}: {
  section: 'realtime' | 'historical' | 'both';
  messages: Message[];
  loading: boolean;
  prompts: { label: string; query: string }[];
  onSend: (text: string) => void;
  placeholder: string;
  useContext: boolean;
  setUseContext: (v: boolean) => void;
  useMultiModel: boolean;
  setUseMultiModel: (v: boolean) => void;
  fullWidth?: boolean;
}) {
  const [input, setInput] = useState('');
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
                        {m.meta.sql && <span> • SQL executed</span>}
                        {m.meta.rows_preview && <span> • {m.meta.rows_preview.length} rows</span>}
                        {m.meta.charts && <span> • {m.meta.charts.length} chart(s)</span>}
                      </div>
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

/* ─── Collapsible Dashboard ─────────────────────────────────── */

function CollapsibleDashboard({
  outboundData,
  inboundData,
  dataLoading,
  days,
  onRefresh,
}: {
  outboundData: OutboundData | null;
  inboundData: InboundData | null;
  dataLoading: boolean;
  days: number;
  onRefresh: () => void;
}) {
  const [isExpanded, setIsExpanded] = useState(true);

  const f = outboundData?.funnel;
  const successRate = f && f.documents_received > 0
    ? Math.round((f.converted_success / f.documents_received) * 100) : null;
  const failRate = f && f.documents_received > 0
    ? Math.round(((f.validated_failed + f.converted_failed) / f.documents_received) * 100) : null;

  return (
    <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden">
      <div className="w-full px-4 py-3 flex items-center justify-between bg-slate-50 border-b border-slate-200">
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="flex items-center gap-2 hover:opacity-80 transition-opacity flex-1"
        >
          <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center">
            <Activity className="h-3.5 w-3.5 text-white" />
          </div>
          <h3 className="text-sm font-semibold text-slate-900">Dashboard Overview</h3>
          <span className="text-xs font-mono text-slate-400">Last {days} days</span>
          {isExpanded ? (
            <ChevronUp className="h-4 w-4 text-slate-400 ml-auto" />
          ) : (
            <ChevronDown className="h-4 w-4 text-slate-400 ml-auto" />
          )}
        </button>
        <button
          onClick={onRefresh}
          disabled={dataLoading}
          className="w-8 h-8 rounded-lg bg-white hover:bg-slate-100 border border-slate-200 flex items-center justify-center text-slate-500 transition-colors disabled:opacity-50 ml-2"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${dataLoading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {isExpanded && (
        <div className="px-4 pb-4 space-y-4 border-t border-slate-100">
          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2.5 pt-4">
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

          {/* Data panels row: Inbound + Outbound side by side */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* Inbound SAT */}
            <div className="rounded-xl border border-slate-200 bg-slate-50 overflow-hidden flex flex-col">
              <div className="px-3 pt-2.5 pb-2 border-b border-slate-200 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-2">
                  <ArrowUpFromLine className="h-3.5 w-3.5 text-slate-500" />
                  <h4 className="text-xs font-semibold text-slate-900">Inbound (SAT)</h4>
                </div>
                <LivePulse />
              </div>
              <div className="p-3 space-y-2 overflow-y-auto max-h-60">
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
                        <div key={l} className="rounded-lg bg-white py-2">
                          <div className="font-mono font-bold text-sm text-slate-900 leading-none">{fmt(v)}</div>
                          <div className="text-[9px] text-slate-500 font-mono uppercase tracking-wide mt-0.5">{l}</div>
                        </div>
                      ))}
                    </div>
                    {inboundData.top_suppliers?.slice(0, 5).map((s, i) => (
                      <div key={i} className="flex items-center justify-between py-1.5 border-b border-slate-200 last:border-0">
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
            <div className="rounded-xl border border-slate-200 bg-slate-50 overflow-hidden flex flex-col">
              <div className="px-3 pt-2.5 pb-2 border-b border-slate-200 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-2">
                  <ArrowDownToLine className="h-3.5 w-3.5 text-slate-500" />
                  <h4 className="text-xs font-semibold text-slate-900">Outbound Funnel</h4>
                </div>
                <GitBranch className="h-3.5 w-3.5 text-slate-400" />
              </div>
              <div className="p-3 space-y-2 overflow-y-auto max-h-60">
                {dataLoading ? (
                  <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                ) : f ? (
                  <>
                    <div className="space-y-1.5">
                      <FunnelStep step={1} label="Received" count={f.documents_received} total={f.documents_received} />
                      <FunnelStep step={2} label="Validated ✓" count={f.validated_success} total={f.documents_received} />
                      <FunnelStep step={3} label="Validation ✗" count={f.validated_failed} total={f.documents_received} warn />
                      <FunnelStep step={4} label="Converted ✓" count={f.converted_success} total={f.documents_received} />
                      <FunnelStep step={5} label="Converted ✗" count={f.converted_failed} total={f.documents_received} warn />
                      <FunnelStep step={6} label="Pending" count={f.converted_pending} total={f.documents_received} />
                    </div>
                    {outboundData?.top_customers?.length ? (
                      <div className="pt-2 border-t border-slate-200">
                        <div className="text-[9px] font-mono uppercase tracking-widest text-slate-400 mb-1.5">Top customers</div>
                        {outboundData.top_customers.slice(0, 4).map((c, i) => (
                          <div key={i} className="flex items-center justify-between py-1 border-b border-slate-200 last:border-0">
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
        </div>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════════════════════════════ */

export default function DashboardAIAnalysis() {
  const [viewMode, setViewMode] = useState<'realtime' | 'historical' | 'both'>('realtime');
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [historicalDays, setHistoricalDays] = useState(90);

  const [realtimeMessages, setRealtimeMessages] = useState<Message[]>([]);
  const [historicalMessages, setHistoricalMessages] = useState<Message[]>([]);
  const [bothMessages, setBothMessages] = useState<Message[]>([]);

  const [realtimeLoading, setRealtimeLoading] = useState(false);
  const [historicalLoading, setHistoricalLoading] = useState(false);
  const [bothLoading, setBothLoading] = useState(false);

  const [useContext, setUseContext] = useState(true);
  const [useMultiModel, setUseMultiModel] = useState(false);

  const [outboundData, setOutboundData] = useState<OutboundData | null>(null);
  const [inboundData, setInboundData] = useState<InboundData | null>(null);
  const [businessData, setBusinessData] = useState<BusinessData | null>(null);
  const [sapHistoricalData, setSAPHistoricalData] = useState<SAPHistoricalData | null>(null);
  const [dataLoading, setDataLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);

  /* ── Data fetch ─────────────────────────────────────────── */

  const fetchRealtimeData = async (d: number) => {
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

  const fetchHistoricalData = async () => {
    setDataLoading(true);
    try {
      const sapData = await dashboardApi.getSAPHistorical();
      setSAPHistoricalData(sapData || null);
    } catch { /* silently fail */ }
    finally { setDataLoading(false); }
  };

  const fetchBothData = async (d: number) => {
    setDataLoading(true);
    try {
      const [outbound, inbound, business, sapData] = await Promise.all([
        dashboardApi.getV2Outbound(d),
        dashboardApi.getV2Inbound(d),
        dashboardApi.getV2Business(d),
        dashboardApi.getSAPHistorical(),
      ]);
      setOutboundData(outbound || null);
      setInboundData(inbound || null);
      setBusinessData(business || null);
      setSAPHistoricalData(sapData || null);
    } catch { /* silently fail */ }
    finally { setDataLoading(false); }
  };

  useEffect(() => {
    if (viewMode === 'realtime') {
      fetchRealtimeData(days);
    } else if (viewMode === 'historical') {
      fetchHistoricalData();
    } else {
      fetchBothData(days);
    }
  }, [viewMode, days]);

  /* ── Context key filter based on mode ───────────────────── */

  const getContextKeys = (mode: 'realtime' | 'historical' | 'both', section: 'realtime' | 'historical' | 'both'): string[] => {
    if (!useContext) return [];
    
    if (mode === 'realtime' || (mode === 'both' && section === 'realtime')) {
      return ['stats', 'failed_summary', 'top_customers', 'inbound_summary', 'process_flow'];
    }
    if (mode === 'historical' || (mode === 'both' && section === 'historical')) {
      return ['business_summary'];
    }
    // For 'both' section (unified chat), return all keys
    return AI_CONTEXT_KEYS;
  };

  /* ── Send helpers ───────────────────────────────────────── */

  const sendMessage = async (section: 'realtime' | 'historical' | 'both', text: string) => {
    const isRT = section === 'realtime';
    const isBoth = section === 'both';
    const setLoading = isBoth ? setBothLoading : (isRT ? setRealtimeLoading : setHistoricalLoading);
    const setMsgs = isBoth ? setBothMessages : (isRT ? setRealtimeMessages : setHistoricalMessages);
    const currentMsgs = isBoth ? bothMessages : (isRT ? realtimeMessages : historicalMessages);
    const d = isBoth ? days : (isRT ? days : historicalDays);

    setError(null);
    setMsgs((prev) => [...prev, { role: 'user', content: text, section, ts: Date.now() }]);
    setLoading(true);

    // Auto-determine time scope from view mode
    const scopeMap: Record<typeof viewMode, 'current' | 'historical' | 'both'> = {
      realtime: 'current',
      historical: 'historical',
      both: 'both'
    };
    const timeScope = scopeMap[viewMode];
    
    const contextKeys = getContextKeys(viewMode, section);

    try {
      if (useMultiModel) {
        const res = await dashboardApi.postAIAnalysisMultiModel(text, contextKeys, d, timeScope);
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
        const res = await dashboardApi.postAIAnalysisChat(text, history, contextKeys, d, timeScope);

        console.log('📊 AI Analysis Response:', res);

        const reply = res?.reply ?? 'No response received.';
        const meta: AiAnalysisMeta = {
          action: res?.action,
          reason: res?.reason,
          sql: res?.sql,
          rows_preview: res?.rows_preview,
          compare: res?.compare,
          charts: res?.charts,
          time_scope: res?.time_scope,
          date_range: res?.date_range,
          period_info: res?.period_info,
        };

        console.log('📊 AI Analysis Response:', res);
        console.log('📊 Period Info:', meta.period_info, meta.date_range);
        console.log('📊 Extracted Charts:', meta.charts);
        console.log('📊 Has Charts:', Boolean(meta.charts && meta.charts.length > 0));

        const hasMeta = Boolean(meta.action || meta.sql || (meta.rows_preview?.length) || (meta.charts?.length) || meta.period_info);
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

  /* ══════════════════════════════════════════════════════════
     RENDER
  ════════════════════════════════════════════════════════════ */

  return (
    <div className="w-full -m-4 sm:-m-6 min-h-screen bg-gray-50 font-sans flex flex-col">
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
            <div className="flex items-center gap-1 bg-slate-100 rounded-xl p-1">
              {[
                { value: 'realtime', label: 'Realtime', icon: Activity },
                { value: 'historical', label: 'Historical', icon: BarChart3 },
                { value: 'both', label: 'Both', icon: GitBranch },
              ].map(({ value, label, icon: Icon }) => (
                <label
                  key={value}
                  className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition-all ${
                    viewMode === value
                      ? 'bg-gradient-to-r from-blue-600 to-indigo-700 text-white shadow-md'
                      : 'text-slate-600 hover:bg-slate-200'
                  }`}
                >
                  <input
                    type="radio"
                    name="viewMode"
                    value={value}
                    checked={viewMode === value}
                    onChange={(e) => setViewMode(e.target.value as typeof viewMode)}
                    className="sr-only"
                  />
                  <Icon className="h-3 w-3" />
                  <span className="hidden sm:inline">{label}</span>
                </label>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-2">
            {viewMode === 'both' ? (
              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <Activity className="h-3 w-3 text-blue-600" />
                  <select
                    value={days}
                    onChange={(e) => setDays(Number(e.target.value))}
                    className="bg-transparent font-mono text-xs text-slate-700 focus:outline-none cursor-pointer"
                  >
                    {[7, 30, 90].map((d) => <option key={d} value={d}>{d}d</option>)}
                  </select>
                </div>
                <div className="flex items-center gap-1 text-xs text-slate-500">
                  <BarChart3 className="h-3 w-3 text-indigo-600" />
                  <select
                    value={historicalDays}
                    onChange={(e) => setHistoricalDays(Number(e.target.value))}
                    className="bg-transparent font-mono text-xs text-slate-700 focus:outline-none cursor-pointer"
                  >
                    {[90, 180, 365].map((d) => <option key={d} value={d}>{d}d</option>)}
                  </select>
                </div>
              </div>
            ) : (
              <div className="flex items-center gap-1 text-xs text-slate-500">
                <Clock className="h-3 w-3" />
                <select
                  value={viewMode === 'realtime' ? days : historicalDays}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    viewMode === 'realtime' ? setDays(v) : setHistoricalDays(v);
                  }}
                  className="bg-transparent font-mono text-xs text-slate-700 focus:outline-none cursor-pointer"
                >
                  {viewMode === 'realtime'
                    ? [7, 30, 90].map((d) => <option key={d} value={d}>{d}d</option>)
                    : [90, 180, 365].map((d) => <option key={d} value={d}>{d}d</option>)}
                </select>
              </div>
            )}
            <button
              type="button"
              onClick={() => {
                if (viewMode === 'realtime') fetchRealtimeData(days);
                else if (viewMode === 'historical') fetchHistoricalData();
                else fetchBothData(days);
              }}
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
            REALTIME MODE
        ═══════════════════════════ */}
        {viewMode === 'realtime' && (
          <div className="fade-in flex flex-col gap-4">
            {/* Visual indicator */}
            <div className="flex items-center gap-2 px-3 py-2 bg-blue-50 border-l-4 border-blue-500 rounded-r-lg">
              <Activity className="h-4 w-4 text-blue-600" />
              <span className="text-xs font-semibold text-blue-900">Realtime Data</span>
              <span className="text-xs text-blue-600">Current Operations</span>
              <LivePulse />
            </div>

            {/* Collapsible Dashboard */}
            <CollapsibleDashboard
              outboundData={outboundData}
              inboundData={inboundData}
              dataLoading={dataLoading}
              days={days}
              onRefresh={() => fetchRealtimeData(days)}
            />

            {/* AI Chat — full width below dashboard */}
            <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col" style={{ minHeight: '420px' }}>
              <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                <Sparkles className="h-3.5 w-3.5 text-blue-600" />
                <h2 className="text-xs font-semibold text-slate-900">AI Analysis</h2>
                <LivePulse />
                <span className="ml-auto text-[10px] font-mono text-slate-400 bg-blue-100 text-blue-700 rounded-full px-2 py-0.5">Realtime</span>
              </div>
              <div className="flex-1 min-h-0 overflow-hidden flex flex-col">
                <ChatPanel
                  section="realtime"
                  messages={realtimeMessages}
                  loading={realtimeLoading}
                  prompts={REALTIME_PROMPTS}
                  onSend={(t) => sendMessage('realtime', t)}
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
            HISTORICAL MODE
        ═══════════════════════════ */}
        {viewMode === 'historical' && (
          <div className="fade-in h-full flex flex-col gap-4">
            {/* Visual indicator */}
            <div className="flex items-center gap-2 px-3 py-2 bg-indigo-50 border-l-4 border-indigo-500 rounded-r-lg">
              <BarChart3 className="h-4 w-4 text-indigo-600" />
              <span className="text-xs font-semibold text-indigo-900">Historical Data</span>
              <span className="text-xs text-indigo-600">1994-2010 Migrated Data</span>
            </div>

            {/* Title + Summary cards */}
            <div className="flex-shrink-0 space-y-3">
              <div className="flex items-center gap-3">
                <h1 className="text-sm font-semibold text-slate-900">Historical Analysis &amp; Forecasting</h1>
                <span className="text-xs font-mono text-slate-400">SAP Data (1994-2010)</span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-4 gap-2.5">
                {dataLoading ? (
                  Array(4).fill(0).map((_, i) => (
                    <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                  ))
                ) : sapHistoricalData ? (
                  <>
                    <StatCard accent label="Total Revenue (1994-2010)"
                      value={sapHistoricalData.summary?.total_revenue ?? 0}
                    />
                    <StatCard label="Total Invoices"
                      value={sapHistoricalData.summary?.total_invoices ?? 0}
                    />
                    <StatCard label="Unique Customers"
                      value={sapHistoricalData.summary?.unique_customers ?? 0}
                    />
                    <StatCard label="Unique Products"
                      value={sapHistoricalData.summary?.unique_products ?? 0}
                    />
                  </>
                ) : (
                  <div className="col-span-4 rounded-xl border border-slate-200 bg-white p-4 text-center text-sm text-slate-500">
                    No SAP historical data available
                  </div>
                )}
              </div>
            </div>

            {/* 3-col layout: revenue by customer | revenue by country | AI chat (2x) */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_1fr_2fr] gap-3 overflow-hidden">

              {/* Revenue by customer (SAP) */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <TrendingUp className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Customer (SAP)</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(6).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : sapHistoricalData?.revenue_by_customer?.length ? (
                    <div className="space-y-2">
                      {sapHistoricalData.revenue_by_customer.slice(0, 10).map((c, i) => {
                        const max = sapHistoricalData.revenue_by_customer![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-3">{c.customer_name || c.customer_id}</span>
                              <span className="font-mono text-xs font-semibold text-slate-900 flex-shrink-0">{fmt(c.total_revenue)}</span>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-indigo-600 to-purple-700 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No SAP customer data</p>
                  )}
                </div>
              </div>

              {/* Revenue by country (SAP) */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <Eye className="h-3.5 w-3.5 text-slate-500" />
                  <h2 className="text-xs font-semibold text-slate-900">By Country (SAP)</h2>
                </div>
                <div className="p-3 flex-1 overflow-y-auto">
                  {dataLoading ? (
                    <>{Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                  ) : sapHistoricalData?.revenue_by_country?.length ? (
                    <div className="space-y-2">
                      {sapHistoricalData.revenue_by_country.slice(0, 10).map((c, i) => {
                        const max = sapHistoricalData.revenue_by_country![0].total_revenue;
                        const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                        return (
                          <div key={i}>
                            <div className="flex items-center justify-between mb-0.5">
                              <span className="text-xs text-slate-700 truncate flex-1 mr-2">{c.country}</span>
                              <div className="flex items-center gap-2 flex-shrink-0">
                                <span className="font-mono text-[10px] text-slate-400">{c.invoice_count}</span>
                                <span className="font-mono text-xs font-semibold text-slate-900">{fmt(c.total_revenue)}</span>
                              </div>
                            </div>
                            <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                              <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full transition-all duration-700"
                                style={{ width: `${pct}%` }} />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="text-xs text-slate-400 py-6 text-center">No SAP country data</p>
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
                <div className="px-3 pt-2.5 pb-0 grid grid-cols-2 md:grid-cols-4 gap-2 flex-shrink-0">
                  {[
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
                      className="rounded-xl border border-slate-200 bg-slate-50 hover:bg-gradient-to-br hover:from-indigo-600 hover:to-purple-700 hover:border-indigo-600 hover:text-white text-slate-700 px-2 py-2 text-left transition-all group disabled:opacity-50 hover:shadow-md flex items-center gap-1.5"
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
                    onSend={(t) => sendMessage('historical', t)}
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

        {/* ═══════════════════════════
            BOTH MODE - UNIFIED VIEW
        ═══════════════════════════ */}
        {viewMode === 'both' && (
          <div className="fade-in space-y-4">
            {/* Header */}
            <div className="flex items-center gap-2 px-3 py-2 bg-gradient-to-r from-blue-50 to-indigo-50 border-l-4 border-purple-500 rounded-r-lg">
              <Activity className="h-4 w-4 text-purple-600" />
              <h2 className="text-sm font-semibold text-purple-900">Unified Analysis</h2>
              <span className="text-xs text-purple-600">Realtime + Historical</span>
              <LivePulse />
            </div>

            {/* Data panels grid - side by side on large screens */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 lg:gap-6">
              {/* Left: Realtime Dashboard */}
              <div className="space-y-4">
                <div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border-l-4 border-blue-500 rounded-r-lg">
                  <Activity className="h-3.5 w-3.5 text-blue-600" />
                  <span className="text-xs font-semibold text-blue-900">Realtime Data</span>
                  <span className="text-[10px] text-blue-600 ml-auto">Current Operations</span>
                </div>

                <CollapsibleDashboard
                  outboundData={outboundData}
                  inboundData={inboundData}
                  dataLoading={dataLoading}
                  days={days}
                  onRefresh={() => fetchRealtimeData(days)}
                />
              </div>

              {/* Right: Historical Dashboard */}
              <div className="space-y-4">
                <div className="flex items-center gap-2 px-3 py-1.5 bg-indigo-50 border-l-4 border-indigo-500 rounded-r-lg">
                  <BarChart3 className="h-3.5 w-3.5 text-indigo-600" />
                  <span className="text-xs font-semibold text-indigo-900">Historical Data</span>
                  <span className="text-[10px] text-indigo-600 ml-auto">1994-2010</span>
                </div>

                {/* SAP summary cards */}
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                  {dataLoading ? (
                    Array(3).fill(0).map((_, i) => (
                      <div key={i} className="rounded-xl border border-slate-200 bg-white p-4 animate-pulse h-16" />
                    ))
                  ) : sapHistoricalData ? (
                    <>
                      <StatCard accent label="Total Revenue (SAP)"
                        value={sapHistoricalData.summary?.total_revenue ?? 0}
                      />
                      <StatCard label="Total Invoices"
                        value={sapHistoricalData.summary?.total_invoices ?? 0}
                      />
                      <StatCard label="Unique Customers"
                        value={sapHistoricalData.summary?.unique_customers ?? 0}
                      />
                    </>
                  ) : (
                    <div className="col-span-3 rounded-xl border border-slate-200 bg-white p-4 text-center text-xs text-slate-500">
                      No SAP data
                    </div>
                  )}
                </div>

                {/* SAP: Revenue by customer & country */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* Revenue by customer (SAP) */}
                  <div className="rounded-xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                    <div className="px-3 pt-2.5 pb-2 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                      <TrendingUp className="h-3 w-3 text-slate-500" />
                      <h4 className="text-xs font-semibold text-slate-900">By Customer (SAP)</h4>
                    </div>
                    <div className="p-2.5 flex-1 overflow-y-auto max-h-48">
                      {dataLoading ? (
                        <>{Array(4).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                      ) : sapHistoricalData?.revenue_by_customer?.length ? (
                        <div className="space-y-1.5">
                          {sapHistoricalData.revenue_by_customer.slice(0, 6).map((c, i) => {
                            const max = sapHistoricalData.revenue_by_customer![0].total_revenue;
                            const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                            return (
                              <div key={i}>
                                <div className="flex items-center justify-between mb-0.5">
                                  <span className="text-[10px] text-slate-700 truncate flex-1 mr-2">{c.customer_name || c.customer_id}</span>
                                  <span className="font-mono text-[10px] font-semibold text-slate-900 flex-shrink-0">{fmt(c.total_revenue)}</span>
                                </div>
                                <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                                  <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-600 rounded-full transition-all duration-500"
                                    style={{ width: `${pct}%` }} />
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 py-4 text-center">No SAP data</p>
                      )}
                    </div>
                  </div>

                  {/* Revenue by country (SAP) */}
                  <div className="rounded-xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                    <div className="px-3 pt-2.5 pb-2 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                      <Eye className="h-3 w-3 text-slate-500" />
                      <h4 className="text-xs font-semibold text-slate-900">By Country (SAP)</h4>
                    </div>
                    <div className="p-2.5 flex-1 overflow-y-auto max-h-48">
                      {dataLoading ? (
                        <>{Array(4).fill(0).map((_, i) => <SkeletonRow key={i} />)}</>
                      ) : sapHistoricalData?.revenue_by_country?.length ? (
                        <div className="space-y-1.5">
                          {sapHistoricalData.revenue_by_country.slice(0, 6).map((c, i) => {
                            const max = sapHistoricalData.revenue_by_country![0].total_revenue;
                            const pct = max > 0 ? Math.round((c.total_revenue / max) * 100) : 0;
                            return (
                              <div key={i}>
                                <div className="flex items-center justify-between mb-0.5">
                                  <span className="text-[10px] text-slate-700 truncate flex-1 mr-2">{c.country}</span>
                                  <span className="font-mono text-[10px] font-semibold text-slate-900 flex-shrink-0">{fmt(c.total_revenue)}</span>
                                </div>
                                <div className="h-1 bg-slate-100 rounded-full overflow-hidden">
                                  <div className="h-full bg-gradient-to-r from-indigo-400 to-purple-500 rounded-full transition-all duration-500"
                                    style={{ width: `${pct}%` }} />
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      ) : (
                        <p className="text-xs text-slate-400 py-4 text-center">No SAP data</p>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Unified AI Chat - Full width */}
            <div className="rounded-2xl border border-purple-200 bg-white overflow-hidden flex flex-col shadow-lg" style={{ minHeight: '480px' }}>
              <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0 bg-gradient-to-r from-blue-50 to-indigo-50">
                <Sparkles className="h-4 w-4 text-purple-600" />
                <h3 className="text-sm font-semibold text-slate-900">Unified AI Analysis</h3>
                <span className="ml-auto text-[10px] font-mono text-purple-700 bg-purple-100 rounded-full px-2.5 py-0.5">Realtime + Historical</span>
              </div>

              {/* Quick action tiles for both contexts */}
              <div className="px-3 pt-3 pb-0 grid grid-cols-2 md:grid-cols-4 gap-2 flex-shrink-0">
                {[
                  { label: 'Compare All', query: 'Compare realtime operations with historical trends - what insights can we gain?', icon: BarChart3, color: 'purple' },
                  { label: 'Forecast', query: 'Based on historical data and current operations, forecast next period performance', icon: TrendingUp, color: 'blue' },
                  { label: 'Full Overview', query: 'Give me a comprehensive overview of both realtime and historical data', icon: Eye, color: 'indigo' },
                  { label: 'Anomalies', query: 'Identify any anomalies or unusual patterns across both realtime and historical data', icon: AlertTriangle, color: 'amber' },
                ].map(({ label, query, icon: Icon, color }) => (
                  <button
                    key={label}
                    type="button"
                    onClick={() => sendMessage('both', query)}
                    disabled={bothLoading}
                    className={`rounded-xl border border-${color}-200 bg-${color}-50 hover:bg-gradient-to-br hover:from-${color}-600 hover:to-purple-700 hover:border-${color}-600 hover:text-white text-slate-700 px-2 py-2 text-left transition-all group disabled:opacity-50 hover:shadow-md flex items-center gap-1.5`}
                  >
                    <Icon className="h-3 w-3 flex-shrink-0 group-hover:text-white transition-colors" />
                    <span className="text-[11px] font-medium leading-tight">{label}</span>
                  </button>
                ))}
              </div>

              <div className="flex-1 min-h-0 overflow-hidden flex flex-col mt-1">
                <ChatPanel
                  section="both"
                  messages={bothMessages}
                  loading={bothLoading}
                  prompts={[...REALTIME_PROMPTS, ...HISTORICAL_PROMPTS]}
                  onSend={(t) => sendMessage('both', t)}
                  placeholder="Ask about both realtime and historical data…"
                  useContext={useContext}
                  setUseContext={setUseContext}
                  useMultiModel={useMultiModel}
                  setUseMultiModel={setUseMultiModel}
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
      </main>
    </div>
  );
}