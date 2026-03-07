'use client';

import { useState, useRef, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import {
  Sparkles, Send, ArrowDownToLine, ArrowUpFromLine, TrendingUp,
  GitBranch, RefreshCw, Mic, MicOff,
  Activity, BarChart3, Clock, Zap, AlertTriangle, CheckCircle2,
  ArrowUpRight, ArrowDownRight, Minus, CalendarRange, Eye,
  FlaskConical, TrendingDown,
} from 'lucide-react';
import AIChartRenderer from './ai/AIChartRenderer';
import MultiModelComparison from './ai/MultiModelComparison';
import { useVoiceRecording } from '../hooks/useVoiceRecording';

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
}: {
  section: 'realtime' | 'historical';
  messages: Message[];
  loading: boolean;
  prompts: { label: string; query: string }[];
  onSend: (text: string) => void;
  placeholder: string;
  useContext: boolean;
  setUseContext: (v: boolean) => void;
  useMultiModel: boolean;
  setUseMultiModel: (v: boolean) => void;
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
        <div className={`flex flex-col overflow-hidden ${hasCharts ? 'w-full lg:w-[45%]' : 'w-full'}`}>
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
                  <div className={`max-w-[92%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words ${
                    m.role === 'user'
                      ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white rounded-tr-sm shadow-md'
                      : 'bg-slate-50 border border-slate-200 text-slate-800 rounded-tl-sm'
                  }`}>
                    {m.content}
                  </div>
                  {/* Show SQL and data info for assistant messages */}
                  {m.role === 'assistant' && m.meta && (
                    <div className="max-w-[92%] mt-1 text-[10px] font-mono text-slate-400 px-1">
                      {m.meta.action && <span>Action: {m.meta.action}</span>}
                      {m.meta.sql && <span> • SQL executed</span>}
                      {m.meta.rows_preview && <span> • {m.meta.rows_preview.length} rows</span>}
                      {m.meta.charts && <span> • {m.meta.charts.length} chart(s)</span>}
                    </div>
                  )}
                  {m.meta?.multiModel && <MultiModelComparison result={m.meta.multiModel} />}
                  {/* On mobile, show charts inline below message */}
                  {m.meta?.charts && m.meta.charts.length > 0 && (
                    <div className="lg:hidden w-full mt-2">
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

        {/* Charts panel — desktop only, shows all charts from conversation */}
        {hasCharts && (
          <div className="hidden lg:flex flex-col w-[55%] border-l border-slate-100 bg-gradient-to-br from-slate-50 to-white overflow-hidden">
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

      {/* Input area — no extra padding at bottom */}
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

  const sendMessage = async (section: 'realtime' | 'historical', text: string) => {
    const isRT = section === 'realtime';
    const setLoading = isRT ? setRealtimeLoading : setHistoricalLoading;
    const setMsgs = isRT ? setRealtimeMessages : setHistoricalMessages;
    const currentMsgs = isRT ? realtimeMessages : historicalMessages;
    const d = isRT ? days : historicalDays;

    setError(null);
    setMsgs((prev) => [...prev, { role: 'user', content: text, section, ts: Date.now() }]);
    setLoading(true);

    const contextKeys = useContext ? AI_CONTEXT_KEYS : [];

    try {
      if (useMultiModel) {
        const res = await dashboardApi.postAIAnalysisMultiModel(text, contextKeys, d);
        setMsgs((prev) => [...prev, {
          role: 'assistant', content: res.synthesized_answer,
          meta: { multiModel: res }, section, ts: Date.now(),
        }]);
      } else {
        const history = currentMsgs.map((m) => ({ role: m.role, content: m.content }));
        const res = await dashboardApi.postAIAnalysisChat(text, history, contextKeys, d);
        
        console.log('📊 AI Analysis Response:', res);
        
        const reply = res?.reply ?? 'No response received.';
        const meta: AiAnalysisMeta = {
          action: res?.action,
          reason: res?.reason,
          sql: res?.sql,
          rows_preview: res?.rows_preview,
          compare: res?.compare,
          charts: res?.charts,
        };
        
        console.log('📊 Extracted Charts:', meta.charts);
        console.log('📊 Has Charts:', Boolean(meta.charts && meta.charts.length > 0));
        
        const hasMeta = Boolean(meta.action || meta.sql || (meta.rows_preview?.length) || (meta.charts?.length));
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
        .chat-container { height: calc(100vh - 56px - 2rem); }
        @media (max-width: 768px) { .chat-container { height: auto; min-height: 500px; } }
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
      <main className="flex-1 w-full px-4 md:px-6 lg:px-8 py-4 overflow-hidden">

        {/* ═══════════════════════════
            REAL-TIME SECTION
        ═══════════════════════════ */}
        {activeSection === 'realtime' && (
          <div className="fade-in h-full flex flex-col gap-4">

            {/* Section title + KPIs — compact */}
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

            {/* Lower area: data panels + AI chat in a responsive grid */}
            <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[1fr_1fr_2fr] gap-3 overflow-hidden">

              {/* Inbound SAT */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowUpFromLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Inbound (SAT)</h2>
                  </div>
                  <LivePulse />
                </div>
                <div className="p-3 space-y-3 flex-1 overflow-y-auto">
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
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <ArrowDownToLine className="h-3.5 w-3.5 text-slate-500" />
                    <h2 className="text-xs font-semibold text-slate-900">Outbound Funnel</h2>
                  </div>
                  <GitBranch className="h-3.5 w-3.5 text-slate-400" />
                </div>
                <div className="p-3 space-y-2.5 flex-1 overflow-y-auto">
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

              {/* AI Chat — takes up 2x column on lg */}
              <div className="rounded-2xl border border-slate-200 bg-white overflow-hidden flex flex-col min-h-0 lg:min-h-full">
                <div className="px-4 pt-3 pb-2.5 border-b border-slate-100 flex items-center gap-2 flex-shrink-0">
                  <Sparkles className="h-3.5 w-3.5 text-blue-600" />
                  <h2 className="text-xs font-semibold text-slate-900">AI Analysis</h2>
                  <span className="ml-auto text-[10px] font-mono text-slate-400 bg-slate-100 rounded-full px-2 py-0.5">Real-time</span>
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
      </main>
    </div>
  );
}