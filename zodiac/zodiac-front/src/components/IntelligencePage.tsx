'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { dashboardApi } from '@/lib/api';
import DashboardAIAnalysis from './DashboardAIAnalysis';
import AIChartRenderer from './ai/AIChartRenderer';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Sparkles, RefreshCw, Send, Loader2,
  ArrowDownCircle, ArrowUpCircle, Activity, TrendingUp,
} from 'lucide-react';

// ─── Domain categories ────────────────────────────────────────────────────────
const DOMAIN_CATEGORIES = [
  {
    id: 'billing', label: 'Invoices & Billing', icon: '🧾', color: 'blue',
    examples: [
      'Top 10 customers by billing amount this month',
      'Total billed revenue year to date',
      'Billing documents with open items',
      'Billing volume by month last year',
      'Billing types by highest net value',
    ],
  },
  {
    id: 'delivery', label: 'Deliveries & Logistics', icon: '🚚', color: 'teal',
    examples: [
      'Open delivery orders pending dispatch',
      'Customers with most delayed deliveries',
      'Delivery document count by month',
      'Planned vs actual delivery dates',
    ],
  },
  {
    id: 'sales', label: 'Sales Orders', icon: '📋', color: 'indigo',
    examples: [
      'Top 10 customers by sales order value',
      'Open sales orders not yet delivered',
      'Sales order trend by month',
      'Products with highest order quantity',
    ],
  },
  {
    id: 'purchasing', label: 'Purchasing', icon: '🛒', color: 'orange',
    examples: [
      'Open purchase orders by vendor',
      'Total PO value this quarter',
      'Purchase orders pending goods receipt',
      'Top 10 vendors by purchase order value',
    ],
  },
  {
    id: 'material', label: 'Master Data', icon: '📦', color: 'slate',
    examples: [
      'Materials with low stock levels',
      'All materials by material group',
      'Stock valuation by plant',
      'Materials with highest inventory value',
    ],
  },
  {
    id: 'finance', label: 'Finance / GL', icon: '💰', color: 'green',
    examples: [
      'Accounting documents posted this month',
      'Open AR items by customer',
      'Profit center performance this quarter',
      'GL account balance summary by cost center',
    ],
  },
  {
    id: 'sat', label: 'SAT / CFDI Inbound', icon: '📨', color: 'violet',
    examples: [
      'Suppliers that sent the most SAT documents',
      'SAT document count by type this week',
      'SAT documents received this week',
      'Inbound SAT volume by supplier last 30 days',
    ],
  },
  {
    id: 'edi', label: 'EDI / Outbound', icon: '📤', color: 'rose',
    examples: [
      'Failed EDI invoices and error reasons',
      'Customer with most EDI failures',
      'EDI success rate by customer',
      'V2 invoice funnel stages this month',
    ],
  },
];

const COLOR_MAP: Record<string, { bg: string; border: string; pill: string; text: string; hover: string }> = {
  blue:   { bg: 'bg-blue-50',   border: 'border-blue-200',   pill: 'bg-blue-100 text-blue-700',   text: 'text-blue-700',   hover: 'hover:bg-blue-50 hover:text-blue-800' },
  teal:   { bg: 'bg-teal-50',   border: 'border-teal-200',   pill: 'bg-teal-100 text-teal-700',   text: 'text-teal-700',   hover: 'hover:bg-teal-50 hover:text-teal-800' },
  indigo: { bg: 'bg-indigo-50', border: 'border-indigo-200', pill: 'bg-indigo-100 text-indigo-700', text: 'text-indigo-700', hover: 'hover:bg-indigo-50 hover:text-indigo-800' },
  orange: { bg: 'bg-orange-50', border: 'border-orange-200', pill: 'bg-orange-100 text-orange-700', text: 'text-orange-700', hover: 'hover:bg-orange-50 hover:text-orange-800' },
  slate:  { bg: 'bg-slate-50',  border: 'border-slate-200',  pill: 'bg-slate-100 text-slate-700',  text: 'text-slate-700',  hover: 'hover:bg-slate-100 hover:text-slate-800' },
  green:  { bg: 'bg-green-50',  border: 'border-green-200',  pill: 'bg-green-100 text-green-700',  text: 'text-green-700',  hover: 'hover:bg-green-50 hover:text-green-800' },
  violet: { bg: 'bg-violet-50', border: 'border-violet-200', pill: 'bg-violet-100 text-violet-700', text: 'text-violet-700', hover: 'hover:bg-violet-50 hover:text-violet-800' },
  rose:   { bg: 'bg-rose-50',   border: 'border-rose-200',   pill: 'bg-rose-100 text-rose-700',   text: 'text-rose-700',   hover: 'hover:bg-rose-50 hover:text-rose-800' },
};

const QUICK_CHIPS = [
  { label: '🔴 Failed invoices',  query: 'Summarize failed invoices and main failure reasons in the last 30 days' },
  { label: '📨 Inbound SAT',      query: 'Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers' },
  { label: '🏆 Top customers',    query: 'Show top 10 customers by revenue with currency and invoice counts' },
  { label: '📤 Outbound flow',    query: 'Show outbound process flow with document counts per funnel stage' },
  { label: '⚡ EDI status',      query: 'Show EDI submission success vs failed count by account for the last 30 days' },
  { label: '📋 Open orders',      query: 'Show open sales orders not yet delivered with total order value' },
  { label: '🚚 Delivery status',  query: 'Show delivery document status summary for the last 30 days' },
  { label: '🔄 By supplier',      query: 'Compare inbound SAT vs outbound invoices by supplier name last 30 days' },
];

type Tab = 'realtime' | 'historical' | 'chat';

function fmt(n: number | null | undefined) {
  if (n == null || isNaN(n as number)) return '—';
  return (n as number).toLocaleString();
}
function pct(num: number | null | undefined, den: number | null | undefined) {
  if (!num || !den || den === 0) return 'N/A';
  return ((num / den) * 100).toFixed(1) + '%';
}

// ─── KPI Card ─────────────────────────────────────────────────────────────────
function KPICard({ label, value, sub, primary, accent }: {
  label: string; value: string | number; sub?: string;
  primary?: boolean; accent?: 'green' | 'amber' | 'red';
}) {
  const base = primary
    ? 'bg-gradient-to-br from-blue-600 to-indigo-700 text-white'
    : 'bg-white border border-slate-200';
  const val = primary ? 'text-white' : accent === 'green' ? 'text-emerald-600' : accent === 'amber' ? 'text-amber-600' : accent === 'red' ? 'text-red-600' : 'text-slate-900';
  const lbl = primary ? 'text-blue-200' : 'text-slate-500';
  return (
    <div className={`rounded-2xl p-4 shadow-sm hover:shadow-md transition-shadow ${base}`}>
      <p className={`text-[10px] font-bold uppercase tracking-widest mb-1.5 ${lbl}`}>{label}</p>
      <p className={`text-2xl font-extrabold tracking-tight ${val}`}>{value}</p>
      {sub && <p className={`text-[11px] mt-0.5 ${primary ? 'text-blue-200' : 'text-slate-400'}`}>{sub}</p>}
    </div>
  );
}

// ─── Funnel Row ───────────────────────────────────────────────────────────────
function FunnelRow({ step, label, value, isRed }: {
  step: number; label: string; value: number; isRed?: boolean;
}) {
  return (
    <div className="flex items-center gap-2.5 py-1.5 border-b border-slate-50 last:border-0">
      <span className="w-5 h-5 rounded-full bg-slate-100 text-slate-500 text-[10px] font-bold flex items-center justify-center flex-shrink-0">{step}</span>
      <span className={`flex-1 text-xs ${isRed ? 'text-red-500 font-medium' : 'text-slate-600'}`}>{label}</span>
      <span className={`text-sm font-bold tabular-nums ${isRed ? 'text-red-600' : 'text-slate-900'}`}>{fmt(value)}</span>
    </div>
  );
}

// ─── What Can You Ask ─────────────────────────────────────────────────────────
function WhatCanYouAsk({ onAsk }: { onAsk: (q: string) => void }) {
  const [activeId, setActiveId] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-slate-100 bg-white">
        <p className="text-sm font-semibold text-slate-800">What can you ask?</p>
        <p className="text-[10px] text-slate-400 mt-0.5">Click any question to run it instantly</p>
      </div>

      {/* Category list */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-50">
        {DOMAIN_CATEGORIES.map((cat) => {
          const c = COLOR_MAP[cat.color] ?? COLOR_MAP.slate;
          const isOpen = activeId === cat.id;
          return (
            <div key={cat.id}>
              {/* Category row */}
              <button
                onClick={() => setActiveId(isOpen ? null : cat.id)}
                className={`w-full flex items-center gap-2.5 px-4 py-2.5 transition-colors text-left
                  ${isOpen ? `${c.bg} ${c.border} border-l-[3px]` : 'hover:bg-slate-50 border-l-[3px] border-transparent'}`}>
                <span className="text-sm leading-none">{cat.icon}</span>
                <span className={`flex-1 text-xs font-semibold ${isOpen ? c.text : 'text-slate-700'}`}>{cat.label}</span>
                <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${isOpen ? c.pill : 'bg-slate-100 text-slate-400'}`}>
                  {cat.examples.length}
                </span>
              </button>

              {/* Examples — expand inline */}
              {isOpen && (
                <div className={`px-4 pb-3 pt-1 ${c.bg}`}>
                  <div className="space-y-1">
                    {cat.examples.map((ex) => (
                      <button key={ex} onClick={() => onAsk(ex)}
                        className={`w-full text-left text-[11px] ${c.text} ${c.hover} py-1.5 px-2.5 rounded-lg transition-colors leading-snug font-medium`}>
                        → {ex}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ─── AI Chat Panel ────────────────────────────────────────────────────────────
function AIChatPanel() {
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const sendQuery = useCallback(async (q: string) => {
    if (!q.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await dashboardApi.postAdaptiveQuery({ question: q.trim() });
      const rows = res.data || res.rows || res.rows_preview || [];
      const rowCount = res.rowCount ?? res.row_count ?? rows.length;
      setResult({
        reply: res.summary || res.reply || res.executive_summary
          || (rowCount === 0 ? 'No rows matched. Try rephrasing or broadening the question.' : `Query returned ${rowCount} row(s).`),
        sql: res.sql,
        data: rows,
        charts: res.charts || [],
        kpis: res.kpis || [],
        insights: res.insights || [],
      });
    } catch (err: any) {
      setError(err?.message || 'Query failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }, [loading]);

  const submit = () => {
    const q = input.trim();
    if (q) { setInput(''); sendQuery(q); }
  };

  return (
    <div className="flex flex-col h-full">
      {/* Quick chips */}
      <div className="flex-shrink-0 px-4 py-2.5 border-b border-slate-100 bg-white">
        <p className="text-[10px] font-semibold text-slate-500 uppercase tracking-wide mb-2">Quick queries</p>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_CHIPS.map((c) => (
            <button key={c.label}
              onClick={() => { setInput(c.query); sendQuery(c.query); }}
              disabled={loading}
              className="text-[10px] px-2 py-1 rounded-full border border-slate-200 bg-white text-slate-600 hover:border-indigo-300 hover:bg-indigo-50 hover:text-indigo-700 transition-colors disabled:opacity-40 font-medium whitespace-nowrap">
              {c.label}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="flex-shrink-0 px-4 py-3 bg-white border-b border-slate-100">
        <div className="flex gap-2 items-end">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }}
            placeholder="Ask anything about your data…"
            rows={2}
            className="flex-1 text-sm text-slate-800 border border-slate-200 rounded-xl px-3 py-2 resize-none focus:outline-none focus:ring-2 focus:ring-indigo-400 bg-slate-50 placeholder:text-slate-400"
          />
          <button onClick={submit} disabled={!input.trim() || loading}
            className="px-4 py-2 rounded-xl bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 disabled:opacity-40 transition-colors flex items-center gap-1.5 self-end h-9">
            {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
            Ask
          </button>
        </div>
      </div>

      {/* Result area */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-slate-50/50">
        {loading && (
          <div className="flex items-center gap-2.5 text-sm text-slate-500 py-4 justify-center">
            <Loader2 className="h-4 w-4 animate-spin text-indigo-500" />
            Analysing your data…
          </div>
        )}
        {error && !loading && (
          <div className="rounded-xl bg-red-50 border border-red-200 px-4 py-3 text-xs text-red-700">
            {error}
          </div>
        )}
        {result && !loading && (
          <div className="space-y-3">
            {/* KPIs */}
            {result.kpis?.length > 0 && (
              <div className="grid grid-cols-2 gap-2">
                {result.kpis.slice(0, 4).map((k: any, i: number) => (
                  <div key={i} className="bg-white rounded-xl border border-slate-200 px-3 py-2.5 shadow-sm">
                    <p className="text-[10px] text-slate-500 font-semibold uppercase tracking-wide truncate">{k.label}</p>
                    <p className="text-lg font-extrabold text-slate-900 mt-0.5 tabular-nums">{k.value}</p>
                    {k.unit && <p className="text-[10px] text-slate-400">{k.unit}</p>}
                  </div>
                ))}
              </div>
            )}

            {/* Summary */}
            <div className="rounded-xl bg-white border border-slate-200 px-4 py-3 shadow-sm text-sm text-slate-800 leading-relaxed prose prose-sm max-w-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{result.reply}</ReactMarkdown>
            </div>

            {/* Charts */}
            {result.charts?.length > 0 && (
              <div className="rounded-xl overflow-hidden border border-slate-200 bg-white shadow-sm">
                <AIChartRenderer charts={result.charts} />
              </div>
            )}

            {/* Table fallback */}
            {result.data?.length > 0 && !result.charts?.length && (
              <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                <table className="w-full text-xs">
                  <thead className="bg-slate-50 border-b border-slate-200">
                    <tr>{Object.keys(result.data[0]).map((k) => (
                      <th key={k} className="px-3 py-2 text-left font-semibold text-slate-600 whitespace-nowrap">{k}</th>
                    ))}</tr>
                  </thead>
                  <tbody>
                    {result.data.slice(0, 15).map((row: any, i: number) => (
                      <tr key={i} className="border-b border-slate-100 hover:bg-slate-50">
                        {Object.values(row).map((v: any, j) => (
                          <td key={j} className="px-3 py-1.5 text-slate-700 whitespace-nowrap">{String(v ?? '—')}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
                {result.data.length > 15 && (
                  <p className="text-[10px] text-slate-400 px-3 py-1.5 border-t border-slate-100">
                    +{result.data.length - 15} more rows — go to Chat tab for full view
                  </p>
                )}
              </div>
            )}

            {/* Insights */}
            {result.insights?.length > 0 && (
              <div className="rounded-xl bg-amber-50 border border-amber-200 px-4 py-3 space-y-1">
                <p className="text-[10px] font-bold uppercase tracking-wide text-amber-700 mb-1.5">💡 Insights</p>
                {result.insights.slice(0, 3).map((ins: string, i: number) => (
                  <p key={i} className="text-xs text-amber-800">• {ins}</p>
                ))}
              </div>
            )}
          </div>
        )}

        {!loading && !result && !error && (
          <div className="flex flex-col items-center justify-center py-10 text-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-md">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <p className="text-sm font-semibold text-slate-700">Ask a data question</p>
            <p className="text-xs text-slate-400 max-w-[220px]">Use the quick queries above or type your own question. Select a category on the right to explore.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function IntelligencePage() {
  const [tab, setTab] = useState<Tab>('realtime');
  const [pendingChatQuestion, setPendingChatQuestion] = useState<string | undefined>(undefined);
  const [days, setDays] = useState(30);
  const [inbound, setInbound] = useState<any>(null);
  const [outbound, setOutbound] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [inbRes, outRes] = await Promise.all([
        dashboardApi.getV2Inbound(days),
        dashboardApi.getV2Outbound(days),
      ]);
      setInbound(inbRes);
      setOutbound(outRes);
      setLastRefresh(new Date());
    } catch { /* silent */ }
    finally { setLoading(false); }
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);
  useEffect(() => {
    if (tab !== 'realtime') return;
    const id = setInterval(fetchData, 60_000);
    return () => clearInterval(id);
  }, [tab, fetchData]);

  const inbSum = inbound?.summary ?? {};
  const outFunnel = outbound?.funnel ?? {};
  const totalDocs = inbSum.total_documents ?? 0;
  const sentToSAP = inbSum.merges_sent_to_sap ?? 0;
  const converted = outFunnel.converted_ok ?? outFunnel.documents_converted ?? 0;
  const received  = outFunnel.documents_received ?? outFunnel.received ?? 0;
  const successRate = received > 0 ? pct(converted, received) : 'N/A';

  const handleAsk = (q: string) => { setPendingChatQuestion(q); setTab('chat'); };

  const TABS = [
    { id: 'realtime' as Tab,   label: 'Real-time',  icon: <Activity className="h-3.5 w-3.5" /> },
    { id: 'historical' as Tab, label: 'Historical', icon: <TrendingUp className="h-3.5 w-3.5" /> },
    { id: 'chat' as Tab,       label: 'Full Chat',  icon: <Sparkles className="h-3.5 w-3.5" /> },
  ];

  return (
    <div className="flex flex-col h-full bg-slate-50 overflow-hidden">

      {/* ── Header bar ── */}
      <div className="flex-shrink-0 flex items-center gap-4 px-5 py-2.5 bg-white border-b border-slate-200 shadow-sm">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center shadow-sm">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <span className="text-sm font-bold text-slate-800">Intelligence</span>
        </div>

        <nav className="flex items-center gap-0.5 border border-slate-200 rounded-lg p-0.5 bg-slate-50">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                tab === t.id ? 'bg-white shadow-sm text-slate-800' : 'text-slate-500 hover:text-slate-700'
              }`}>
              {t.icon}{t.label}
            </button>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          {tab !== 'chat' && (
            <>
              <select value={days} onChange={(e) => setDays(+e.target.value)}
                className="text-xs border border-slate-200 rounded-lg px-2.5 py-1.5 bg-white text-slate-600 focus:outline-none focus:ring-2 focus:ring-indigo-400">
                {[7, 14, 30, 60, 90].map((d) => <option key={d} value={d}>{d}d</option>)}
              </select>
              <button onClick={fetchData} disabled={loading}
                className="p-1.5 rounded-lg border border-slate-200 hover:bg-slate-100 text-slate-500 disabled:opacity-40 transition-colors">
                <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              </button>
              {/* suppressHydrationWarning: server and client render different times/locales */}
              <span className="text-[10px] text-slate-400 hidden sm:block" suppressHydrationWarning>
                {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            </>
          )}
          {tab !== 'chat' && (
            <span className="flex items-center gap-1.5 text-[10px] font-medium text-emerald-600">
              <span className="relative flex h-1.5 w-1.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
              </span>
              Live
            </span>
          )}
        </div>
      </div>

      {/* ── Full Chat tab ── */}
      {tab === 'chat' && (
        <div className="flex-1 overflow-hidden">
          <DashboardAIAnalysis initialQuestion={pendingChatQuestion} />
        </div>
      )}

      {/* ── Realtime / Historical tabs ── */}
      {tab !== 'chat' && (
        <div className="flex-1 overflow-hidden flex flex-col">

          {/* KPI Cards — always at top */}
          <div className="flex-shrink-0 px-5 pt-4 pb-3">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <KPICard primary label="Docs Received" value={fmt(totalDocs)} sub="SAT / CFDI inbound" />
              <KPICard label="Validated OK" value={fmt(sentToSAP)} accent="green" sub="Sent to SAP" />
              <KPICard label="Converted OK" value={fmt(converted)} accent="green" sub="EDI outbound" />
              <KPICard label="Success Rate" value={successRate}
                accent={received > 0 && converted / received > 0.8 ? 'green' : 'amber'}
                sub="Converted / Received" />
            </div>
          </div>

          {/* ── 3-column body ── */}
          <div className="flex-1 overflow-hidden flex gap-0 px-5 pb-5">

            {/* Left: Inbound + Outbound panels */}
            <div className="w-[220px] flex-shrink-0 flex flex-col gap-3 overflow-y-auto pr-3">

              {/* Inbound SAT */}
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
                  <ArrowDownCircle className="h-3.5 w-3.5 text-blue-500" />
                  <p className="text-xs font-semibold text-slate-800">Inbound SAT</p>
                </div>
                <div className="px-4 py-3">
                  {loading ? (
                    <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>
                  ) : (
                    <>
                      <div className="grid grid-cols-3 gap-1.5 mb-3 text-center">
                        {[
                          { label: 'Total', value: inbSum.total_documents ?? 0 },
                          { label: 'In SAP', value: inbSum.merges_sent_to_sap ?? 0 },
                          { label: 'Pending', value: inbSum.merges_pending ?? 0 },
                        ].map(({ label, value }) => (
                          <div key={label}>
                            <p className="text-base font-extrabold text-slate-900">{fmt(value)}</p>
                            <p className="text-[9px] uppercase tracking-wide text-slate-400">{label}</p>
                          </div>
                        ))}
                      </div>
                      {inbound?.by_document_type?.length > 0 && (
                        <div className="space-y-1">
                          {inbound.by_document_type.slice(0, 4).map((d: any) => (
                            <div key={d.doc_type} className="flex items-center gap-1.5">
                              <span className="text-[9px] text-slate-500 w-16 truncate font-mono">{d.doc_type}</span>
                              <div className="flex-1 h-1 bg-slate-100 rounded-full overflow-hidden">
                                <div className="h-full bg-blue-400 rounded-full"
                                  style={{ width: `${Math.min(100, (d.count / (totalDocs || 1)) * 100)}%` }} />
                              </div>
                              <span className="text-[9px] font-bold text-slate-600 tabular-nums">{d.count}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              </div>

              {/* Outbound Funnel */}
              <div className="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                <div className="px-4 py-2.5 border-b border-slate-100 flex items-center gap-2">
                  <ArrowUpCircle className="h-3.5 w-3.5 text-indigo-500" />
                  <p className="text-xs font-semibold text-slate-800">Outbound Funnel</p>
                </div>
                <div className="px-4 py-3">
                  {loading ? (
                    <div className="flex justify-center py-4"><Loader2 className="h-4 w-4 animate-spin text-slate-400" /></div>
                  ) : (
                    <div className="space-y-0">
                      <FunnelRow step={1} label="Received"       value={outFunnel.documents_received ?? outFunnel.received ?? 0} />
                      <FunnelRow step={2} label="Validated ✓"    value={outFunnel.validated_ok ?? outFunnel.documents_validated ?? 0} />
                      <FunnelRow step={3} label="Validation ✗"   value={outFunnel.validation_failed ?? outFunnel.documents_validation_failed ?? 0} isRed />
                      <FunnelRow step={4} label="Converted ✓"    value={outFunnel.converted_ok ?? outFunnel.documents_converted ?? 0} />
                      <FunnelRow step={5} label="Converted ✗"    value={outFunnel.conversion_failed ?? outFunnel.documents_conversion_failed ?? 0} isRed />
                      <FunnelRow step={6} label="Pending"        value={outFunnel.pending ?? outFunnel.documents_pending ?? 0} />
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Centre: AI Chat */}
            <div className="flex-1 min-w-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden mx-3">
              <div className="flex items-center gap-2 px-4 py-2.5 border-b border-slate-100 bg-gradient-to-r from-indigo-50/60 to-white">
                <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center">
                  <Sparkles className="h-3 w-3 text-white" />
                </div>
                <p className="text-sm font-semibold text-slate-800">AI Analysis</p>
                <span className="text-[10px] text-slate-400 ml-1">Natural language → instant insights</span>
                <span className="ml-auto flex items-center gap-1.5 text-[10px] font-medium text-emerald-600">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-500" />
                  </span>
                  Live
                </span>
              </div>
              <div className="h-[calc(100%-45px)] overflow-hidden">
                <AIChatPanel />
              </div>
            </div>

            {/* Right: What can you ask */}
            <div className="w-[240px] flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
              <WhatCanYouAsk onAsk={(q) => {
                // pre-fill the chat and switch to it
                handleAsk(q);
              }} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
