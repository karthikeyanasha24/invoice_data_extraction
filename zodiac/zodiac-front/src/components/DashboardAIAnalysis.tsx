'use client';

/**
 * DashboardAIAnalysis.tsx — Complete Re-Architecture
 * ===================================================
 * Power BI-style AI analytics interface.
 *
 * Pipeline driven (no Schema Browser):
 *   1. User asks a natural language question
 *   2. Backend runs 15-stage analyst pipeline
 *   3. Response contains: sql, data, kpis, charts, summary, keyFindings
 *   4. Frontend renders: KPI cards → Charts → Scrollable table → Insights
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { dashboardApi } from '@/lib/api';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  Send, Sparkles, RotateCcw, Copy, Check, Loader2,
  TrendingUp, BarChart3, PieChart as PieIcon,
  LineChart as LineIcon, Table2, Lightbulb, AlertCircle,
  CheckCircle2, Code2, ChevronDown, ChevronUp, X,
  ArrowRight, Zap, Database,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import AIChartRenderer from './ai/AIChartRenderer';

/** Persist adaptive Full Chat thread id (reuses backend chat_thread_store via ada_ prefix). */
const ADA_THREAD_KEY = 'zodiac_ada_thread_id';

function ensureAdaptiveThreadId(): string {
  if (typeof window === 'undefined') return `ada_ssr_${Date.now()}`;
  let tid = sessionStorage.getItem(ADA_THREAD_KEY) || '';
  if (!tid.startsWith('ada_')) {
    tid = `ada_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    sessionStorage.setItem(ADA_THREAD_KEY, tid);
  }
  return tid;
}
// ─── Colour palette ──────────────────────────────────────────────────────────
const PALETTE = [
  '#6366f1','#f59e0b','#10b981','#ef4444','#3b82f6',
  '#a855f7','#f97316','#06b6d4','#ec4899','#14b8a6',
  '#eab308','#84cc16','#8b5cf6','#f43f5e','#0ea5e9',
];

// ─── Quick-question chips ────────────────────────────────────────────────────
const QUICK_QUESTIONS = [
  { label: 'Failed invoices', q: 'Summarize failed invoices and main failure reasons in the last 30 days' },
  { label: 'Top customers', q: 'Show top 10 customers ranked by total invoice amount' },
  { label: 'SAT inbound', q: 'Summarize inbound SAT documents: totals, top suppliers, sent to SAP vs pending' },
  { label: 'EDI status', q: 'Show EDI success vs failed count by Zodiac account for the last 30 days' },
  { label: 'Monthly trend', q: 'Show monthly invoice volume and total amount as a trend for the last 12 months' },
  { label: 'Conversion rate', q: 'What is the V2 invoice conversion success rate and where is the biggest backlog?' },
  { label: 'By supplier', q: 'Show top suppliers by document count comparing inbound SAT vs outbound invoices' },
  { label: 'Revenue by month', q: 'Show total billing revenue grouped by month for the last 6 months' },
];

// ─── Pipeline progress steps ─────────────────────────────────────────────────
const PIPELINE_STEPS = [
  { id: 'intent',   label: 'Understanding your question',       ms: 0     },
  { id: 'domain',   label: 'Classifying business domain',       ms: 1000  },
  { id: 'tables',   label: 'Selecting relevant tables',         ms: 2500  },
  { id: 'columns',  label: 'Ranking columns by relevance',      ms: 4000  },
  { id: 'sql',      label: 'Generating SQL',                    ms: 6000  },
  { id: 'execute',  label: 'Executing query',                   ms: 11000 },
  { id: 'analyze',  label: 'Analyzing results',                 ms: 18000 },
  { id: 'charts',   label: 'Building visualizations',           ms: 25000 },
];

// ─── Number formatting ────────────────────────────────────────────────────────
function fmt(v: any): string {
  const n = parseFloat(String(v ?? '').replace(/,/g, ''));
  if (isNaN(n)) return String(v ?? '');
  if (Math.abs(n) >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (Math.abs(n) >= 1_000)     return (n / 1_000).toFixed(1) + 'K';
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// ─── Table cell helpers (formatted numbers, ID detection) ───────────────────────
/** SAP/db key columns and ID-like values must stay verbatim, never formatted. */
function isIdLike(col: string, val: any): boolean {
  const lk = col.toLowerCase();
  if (/^(mandt|vbeln|kunnr|lifnr|matnr|werks|bukrs|vkorg|belnr|posnr|ebeln|ebelp|gjahr|uuid|rfc)$/.test(lk)) return true;
  if (/(_id|_code|_no|_key|_num|id$|code$|uuid|rfc)/.test(lk)) return true;
  if (typeof val === 'string' && /^\d{5,}$/.test(val.trim())) return true;
  return false;
}
function isMoneyName(col: string): boolean {
  const lk = col.toLowerCase();
  if (/count|qty|quantity|_pct|percent|ratio/.test(lk)) return false;
  return /\b(amount|total|value|revenue|sales|price|cost|net|gross|netwr|rmwwr|fkwrt|wert|betrag)\b/.test(lk);
}
function cellNum(v: any): number {
  if (typeof v === 'number') return v;
  const s = String(v ?? '').trim();
  return /^-?[\d.,]+$/.test(s) ? parseFloat(s.replace(/,/g, '')) : NaN;
}

// ─── Types ────────────────────────────────────────────────────────────────────
type KPI   = { label: string; value: string; change?: string };
type Chart = {
  type: 'bar' | 'line' | 'pie';
  title: string;
  labels: string[];
  datasets: { label: string; data: (number | null)[] }[];
  options?: Record<string, any>;
};
type QueryResult = {
  sql?: string;
  data?: any[];
  rowCount?: number;
  totalCount?: number;
  sqlStrategy?: string;
  summary?: string;
  keyFindings?: string[];
  kpis?: KPI[];
  charts?: Chart[];
  meta?: {
    domain?: string;
    intent?: string;
    schema_tables?: string[];
    pipeline_ms?: number;
    warnings?: string[];
  };
};
type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  result?: QueryResult;
  ts: number;
};

// ─── Copy hook ────────────────────────────────────────────────────────────────
function useCopy() {
  const [copied, setCopied] = useState(false);
  return {
    copied,
    copy: (text: string) => {
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true); setTimeout(() => setCopied(false), 2000);
      });
    },
  };
}

// ═══════════════════════════════════════════════════════════════════════════════
// KPI Cards
// ═══════════════════════════════════════════════════════════════════════════════
function KPICards({ kpis }: { kpis: KPI[] }) {
  if (!kpis?.length) return null;
  const icons = [TrendingUp, BarChart3, PieIcon, LineIcon];
  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
      {kpis.slice(0, 4).map((kpi, i) => {
        const Icon = icons[i % icons.length];
        const isPos = kpi.change?.startsWith('+');
        const isNeg = kpi.change?.startsWith('-');
        return (
          <div key={i}
            className="relative bg-white rounded-xl border border-slate-100 p-4 shadow-sm hover:shadow-md transition-shadow overflow-hidden"
            style={{ borderTop: `3px solid ${PALETTE[i]}` }}>
            <div className="absolute -right-4 -top-4 w-16 h-16 rounded-full opacity-10"
              style={{ background: PALETTE[i] }} />
            <div className="flex items-center gap-2 mb-2">
              <div className="p-1.5 rounded-lg" style={{ background: PALETTE[i] + '20' }}>
                <Icon className="h-4 w-4" style={{ color: PALETTE[i] }} />
              </div>
              <span className="text-xs text-slate-500 font-semibold uppercase tracking-wide truncate">{kpi.label}</span>
            </div>
            <div className="text-2xl font-extrabold text-slate-900 mb-1 tabular-nums">{kpi.value}</div>
            {kpi.change && (
              <div className={cn(
                "text-xs font-bold",
                isPos ? "text-emerald-600" : isNeg ? "text-red-500" : "text-slate-400"
              )}>
                {kpi.change}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Charts grid
// ═══════════════════════════════════════════════════════════════════════════════
function ChartsGrid({ charts }: { charts: any[] }) {
  if (!charts?.length) return null;

  // Backend now sends Recharts spec objects: { chart_type, title, data, x_key, y_keys, ... }.
  // Legacy shape was { type, labels, datasets }. Normalize BOTH into the spec shape and
  // render through AIChartRenderer (rich formatting, currency, dual axes).
  const specs = charts
    .map((c) => {
      if (c && Array.isArray(c.data) && (c.chart_type || c.x_key || c.y_keys || c.name_key)) {
        return c; // already a spec
      }
      if (c && Array.isArray(c.labels) && Array.isArray(c.datasets)) {
        const data = c.labels.map((label: string, i: number) => {
          const row: Record<string, any> = { name: label };
          for (const ds of c.datasets) row[ds.label] = ds.data?.[i] ?? null;
          return row;
        });
        return {
          chart_type: c.type || 'bar',
          title: c.title || 'Chart',
          data,
          x_key: 'name',
          y_keys: c.datasets.map((d: any) => d.label),
        };
      }
      return null;
    })
    .filter((c) => c && Array.isArray(c.data) && c.data.length > 0);

  if (!specs.length) return null;
  return (
    <div className="mb-4">
      <AIChartRenderer charts={specs as any} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Data table — fully scrollable horizontal + vertical
// ═══════════════════════════════════════════════════════════════════════════════
function DataTable({ data, totalCount, sql }: { data: any[]; totalCount?: number; sql?: string }) {
  const [showSql, setShowSql] = useState(false);
  const { copied, copy } = useCopy();

  // If no data AND no SQL, nothing to show
  if (!data?.length && !sql) return null;

  const headers = data?.length ? Object.keys(data[0]) : [];
  const isEmpty = !data?.length;

  return (
    <div className="bg-white rounded-xl border border-slate-100 shadow-sm mb-4">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100">
        <div className="flex items-center gap-2">
          <Table2 className="h-4 w-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-700">
            {isEmpty
              ? <span className="text-amber-600">0 rows returned</span>
              : totalCount && totalCount > data.length
                ? `Showing ${data.length.toLocaleString()} of ${totalCount.toLocaleString()} rows`
                : `${data.length.toLocaleString()} rows`}
          </span>
        </div>
        {sql && (
          <button onClick={() => setShowSql(v => !v)}
            className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 px-2.5 py-1.5 rounded-lg hover:bg-slate-50 transition-colors">
            <Code2 className="h-3.5 w-3.5" />
            {showSql ? 'Hide SQL' : 'View SQL'}
          </button>
        )}
      </div>

      {/* Always auto-expand SQL when empty so user can debug */}
      {sql && (isEmpty ? true : showSql) && (
        <div className="relative px-4 py-3 bg-slate-950 text-slate-200 text-xs font-mono overflow-x-auto border-b border-slate-800">
          <button onClick={() => copy(sql)}
            className="absolute top-2 right-2 p-1.5 rounded bg-slate-700 hover:bg-slate-600 transition-colors">
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <pre className="pr-8 whitespace-pre-wrap break-all leading-relaxed">{sql}</pre>
        </div>
      )}

      {/* Scrollable table — only when there's data */}
      {!isEmpty && (
        <div className="overflow-auto max-h-[420px]" style={{ scrollbarWidth: 'thin' }}>
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 z-10">
              <tr className="bg-gradient-to-r from-indigo-50 via-slate-50 to-violet-50">
                {headers.map(h => (
                  <th key={h} className="px-3 py-2.5 text-left font-bold text-slate-600 uppercase tracking-wide whitespace-nowrap border-b-2 border-indigo-100">
                    {h.replace(/_/g, ' ')}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.map((row, i) => (
                <tr key={i} className={cn(
                  'transition-colors hover:bg-indigo-50/40',
                  i % 2 === 0 ? 'bg-white' : 'bg-slate-50/50'
                )}>
                  {headers.map(h => {
                    const v = row[h];
                    const n = cellNum(v);
                    const isNum = !isIdLike(h, v) && Number.isFinite(n);
                    return (
                      <td key={h} className={cn(
                        'px-3 py-2 whitespace-nowrap border-b border-slate-100 max-w-[260px] overflow-hidden text-ellipsis',
                        isNum ? 'text-right tabular-nums' : 'text-slate-700',
                        isNum && isMoneyName(h) ? 'font-semibold text-emerald-700' : isNum ? 'text-slate-800' : ''
                      )}>
                        {v == null
                          ? <span className="text-slate-300 italic">null</span>
                          : isNum
                            ? n.toLocaleString('en-US', { maximumFractionDigits: 2 })
                            : String(v)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Insights panel
// ═══════════════════════════════════════════════════════════════════════════════
function InsightsPanel({ findings }: { findings: string[] }) {
  if (!findings?.length) return null;
  return (
    <div className="bg-gradient-to-br from-indigo-50 to-blue-50 rounded-xl border border-indigo-100 p-4 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <Lightbulb className="h-4 w-4 text-indigo-600" />
        <span className="text-sm font-semibold text-indigo-800">Key Findings</span>
      </div>
      <ul className="space-y-2">
        {findings.map((f, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm text-indigo-900">
            <CheckCircle2 className="h-3.5 w-3.5 text-indigo-400 mt-0.5 flex-shrink-0" />
            <span>{f}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Summary card
// ═══════════════════════════════════════════════════════════════════════════════
function SummaryCard({ summary }: { summary: string }) {
  return (
    <div className="relative bg-gradient-to-br from-white via-amber-50/30 to-orange-50/40 rounded-xl border border-amber-100 p-4 shadow-sm mb-4 overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-amber-400 to-orange-400" />
      <div className="flex items-center gap-2 mb-2">
        <div className="p-1 rounded-md bg-amber-100">
          <Sparkles className="h-3.5 w-3.5 text-amber-600" />
        </div>
        <span className="text-sm font-bold text-slate-800">Executive Summary</span>
      </div>
      <div className="prose prose-sm prose-slate max-w-none text-slate-700 text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{summary}</ReactMarkdown>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Meta strip (pipeline info)
// ═══════════════════════════════════════════════════════════════════════════════
function MetaStrip({ meta, sqlStrategy, rowCount, totalCount }: {
  meta?: QueryResult['meta'];
  sqlStrategy?: string;
  rowCount?: number;
  totalCount?: number;
}) {
  const [open, setOpen] = useState(false);
  if (!meta) return null;
  const tables = meta.schema_tables || [];
  const ms = meta.pipeline_ms;
  const warnings = meta.warnings || [];

  return (
    <div className="mt-2">
      <button onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 transition-colors">
        <Database className="h-3 w-3" />
        {tables.length > 0 && <span>{tables.length} tables</span>}
        {ms && <><span className="text-slate-300">·</span><span>{ms}ms</span></>}
        {sqlStrategy && sqlStrategy !== 'full' && (
          <><span className="text-slate-300">·</span>
          <span className="capitalize text-amber-600">{sqlStrategy}</span></>
        )}
        {rowCount != null && <><span className="text-slate-300">·</span><span>{rowCount.toLocaleString()} rows{totalCount && totalCount > rowCount ? ` of ${totalCount.toLocaleString()}` : ''}</span></>}
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="mt-2 p-3 rounded-lg bg-slate-50 border border-slate-100 text-xs text-slate-600 space-y-1">
          {tables.length > 0 && <div><span className="font-medium">Tables:</span> {tables.join(', ')}</div>}
          {meta.domain  && <div><span className="font-medium">Domain:</span> {meta.domain}</div>}
          {meta.intent  && <div><span className="font-medium">Intent:</span> {meta.intent}</div>}
          {warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-1.5 text-amber-600">
              <AlertCircle className="h-3.5 w-3.5 mt-px flex-shrink-0" /> {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Pipeline progress indicator
// ═══════════════════════════════════════════════════════════════════════════════
function PipelineProgress({ elapsed }: { elapsed: number }) {
  const activeIdx = PIPELINE_STEPS.findLastIndex(s => elapsed >= s.ms);
  return (
    <div className="space-y-2 py-2">
      {PIPELINE_STEPS.map((step, i) => {
        const done    = i < activeIdx;
        const active  = i === activeIdx;
        const pending = i > activeIdx;
        return (
          <div key={step.id} className={cn(
            "flex items-center gap-3 text-sm transition-all duration-300",
            done    && "text-emerald-600",
            active  && "text-indigo-700 font-medium",
            pending && "text-slate-300",
          )}>
            {done    ? <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
            : active  ? <Loader2    className="h-4 w-4 flex-shrink-0 animate-spin" />
            :           <div       className="h-4 w-4 flex-shrink-0 rounded-full border-2 border-slate-200" />}
            <span>{step.label}</span>
          </div>
        );
      })}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Full result renderer (Power BI-style dashboard)
// ═══════════════════════════════════════════════════════════════════════════════
function ResultDashboard({ result }: { result: QueryResult }) {
  if (!result) return null;
  const { kpis, charts, summary, keyFindings, data, totalCount, sql, sqlStrategy, rowCount, meta } = result;

  const hasKpis    = (kpis?.length ?? 0) > 0;
  const hasCharts  = (charts?.length ?? 0) > 0;
  const hasData    = (data?.length ?? 0) > 0;
  const hasSummary = !!summary;
  const hasInsights = (keyFindings?.length ?? 0) > 0 && keyFindings?.[0] !== 'No results found.';

  return (
    <div className="space-y-0">
      {hasKpis    && <KPICards kpis={kpis!} />}
      {/* Pass charts through untouched — ChartsGrid normalizes BOTH legacy
          {labels,datasets} and Recharts spec {chart_type,data,x_key} shapes.
          Converting here stripped `data` and silently dropped spec charts. */}
      {hasCharts  && <ChartsGrid charts={charts!} />}
      {hasSummary && <SummaryCard summary={summary!} />}
      {hasInsights && <InsightsPanel findings={keyFindings!} />}
      {(hasData || sql) && <DataTable data={data || []} totalCount={totalCount} sql={sql} />}
      <MetaStrip meta={meta} sqlStrategy={sqlStrategy} rowCount={rowCount} totalCount={totalCount} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════
export default function DashboardAIAnalysis({ initialQuestion }: { initialQuestion?: string } = {}) {
  const [messages,   setMessages]   = useState<Message[]>([]);
  const [input,      setInput]      = useState('');
  const [loading,    setLoading]    = useState(false);
  const [elapsed,    setElapsed]    = useState(0);
  const [error,      setError]      = useState<string | null>(null);
  const [isNewQuestion, setIsNewQuestion] = useState(false);
  const [threadId,   setThreadId]   = useState<string>('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef   = useRef<HTMLDivElement>(null);
  const timerRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const inputRef    = useRef<HTMLTextAreaElement>(null);
  const initialSentRef = useRef<string | null>(null);

  // Resolve / restore adaptive thread id once on mount
  useEffect(() => {
    setThreadId(ensureAdaptiveThreadId());
  }, []);

  // Load persisted turns from chat_thread_store (ada_* via adaptive history API)
  useEffect(() => {
    if (!threadId || historyLoaded) return;
    let cancelled = false;
    (async () => {
      try {
        const hist = await dashboardApi.getAdaptiveChatHistory(threadId);
        if (cancelled) return;
        const restored: Message[] = (hist.messages || [])
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m, i) => ({
            id: `hist-${i}-${Date.now()}`,
            role: m.role as 'user' | 'assistant',
            content: m.content || '',
            result: m.role === 'assistant' && m.result ? {
              sql: m.result.sql,
              data: m.result.data || [],
              rowCount: m.result.rowCount ?? (m.result.data?.length ?? 0),
              charts: m.result.charts || [],
              summary: m.result.summary || m.content,
            } : undefined,
            ts: Date.now() + i,
          }));
        if (restored.length > 0) {
          setMessages((prev) => (prev.length === 0 ? restored : prev));
        }
      } catch {
        /* history optional */
      } finally {
        if (!cancelled) setHistoryLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [threadId, historyLoaded]);

  // auto-scroll
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // elapsed timer while loading
  useEffect(() => {
    if (loading) {
      setElapsed(0);
      timerRef.current = setInterval(() => setElapsed(e => e + 500), 500);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loading]);

  const sendQuestion = useCallback(async (question: string) => {
    const q = (question || '').trim().replace(/^undefined/i, '').trim();
    if (!q || loading) return;

    const tid = threadId || ensureAdaptiveThreadId();
    if (!threadId) setThreadId(tid);

    setError(null);
    setInput('');
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: q, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);

    // build contextData only when the user is following up (not starting a new question)
    const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant' && m.result);
    const contextData = (!isNewQuestion && lastAssistant?.result)
      ? {
          previousQuestion: lastAssistant.content,
          previousSQL:      lastAssistant.result.sql || '',
          data:             lastAssistant.result.data?.slice(0, 20) || [],
        }
      : null;
    setIsNewQuestion(false); // reset after each send

    try {
      const res = await dashboardApi.postAdaptiveQuery({
        question: q,
        contextData,
        threadId: tid,
      });

      // Normalise response — backend may return old shape or new pipeline shape
      const result: QueryResult = {
        sql:         res.sql || res.generatedSql,
        data:        res.data || res.rows || [],
        rowCount:    res.rowCount ?? res.row_count ?? (res.data?.length ?? 0),
        totalCount:  res.totalCount ?? res.total_count ?? -1,
        sqlStrategy: res.sqlStrategy || res.sql_strategy || 'full',
        summary:     res.summary || res.executive_summary || '',
        keyFindings: res.keyFindings || res.key_findings || [],
        kpis:        res.kpis || [],
        charts:      res.charts || res.chart_configs || [],
        meta:        res.meta || {
          domain:        res.domain,
          intent:        res.intent,
          schema_tables: res.schema_tables || res.meta?.schema_tables,
          pipeline_ms:   res.pipeline_ms,
          warnings:      res.warnings || [],
        },
      };

      // If it's a pure analysis reply (follow-up text answer)
      const summaryContent = res.type === 'analysis'
        ? (res.answer || res.summary || 'Done.')
        : (result.summary || (result.rowCount === 0
            ? 'Query executed but returned no data for this environment.'
            : `Query returned ${result.rowCount} row(s).`));

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: summaryContent,
        result: res.type === 'analysis' ? undefined : result,
        ts: Date.now(),
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      setError(err.message || 'Query failed. Please try rephrasing.');
      // Keep the user message visible so history does not silently lose questions
    } finally {
      setLoading(false);
    }
    // isNewQuestion MUST be a dep: without it the memoized closure keeps a stale
    // value and the "New question" button silently never takes effect.
  }, [messages, loading, isNewQuestion, threadId]);

  // Auto-run a question handed over from another view (e.g. "What can you ask?"
  // sidebar on the Real-time tab). Guarded so the same question only fires once.
  // Wait for history load so we don't race with restored messages.
  useEffect(() => {
    const q = (initialQuestion || '').trim();
    if (q && historyLoaded && initialSentRef.current !== q && !loading) {
      initialSentRef.current = q;
      sendQuestion(q);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion, historyLoaded]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendQuestion(input);
    }
  };

  const clearAll = () => {
    setMessages([]);
    setError(null);
    // Start a fresh adaptive thread so cleared UI does not reload old turns
    if (typeof window !== 'undefined') {
      const tid = `ada_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(ADA_THREAD_KEY, tid);
      setThreadId(tid);
      setHistoryLoaded(true);
    }
  };

  return (
    <div className="flex flex-col h-full bg-slate-50">

      {/* ── Header ── */}
      <div className="flex-none bg-gradient-to-r from-indigo-50/80 via-white to-violet-50/60 border-b border-slate-200 px-5 py-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-lg shadow-sm">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-800">AI Data Analyst</h2>
              <p className="text-xs text-slate-400">15-stage pipeline · Auto charts · Executive summaries</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button onClick={clearAll}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="Clear conversation">
                <RotateCcw className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Messages / Welcome ── */}
      <div className="flex-1 overflow-y-auto px-4 py-4 space-y-6" style={{ scrollbarWidth: 'thin' }}>

        {messages.length === 0 && !loading && (
          <div className="max-w-3xl mx-auto text-center py-8">
            <div className="inline-flex p-4 bg-gradient-to-br from-indigo-100 to-violet-100 rounded-2xl mb-4 shadow-sm">
              <Sparkles className="h-8 w-8 text-indigo-500" />
            </div>
            <h3 className="text-xl font-bold bg-gradient-to-r from-indigo-700 to-violet-600 bg-clip-text text-transparent mb-2">
              Ask anything about your data
            </h3>
            <p className="text-sm text-slate-500 mb-6">
              I analyze your question, select the right tables, write SQL, execute it, and
              return charts, KPIs, and insights — automatically.
            </p>
            {/* Quick questions */}
            <div className="grid grid-cols-2 gap-2 text-left">
              {QUICK_QUESTIONS.map(({ label, q }, qi) => (
                <button key={label}
                  onClick={() => sendQuestion(q)}
                  className="flex items-start gap-2.5 p-3 bg-white rounded-xl border border-slate-200 hover:shadow-md transition-all text-left group"
                  style={{ borderLeft: `3px solid ${PALETTE[qi % PALETTE.length]}` }}>
                  <ArrowRight className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 group-hover:translate-x-0.5 transition-transform"
                    style={{ color: PALETTE[qi % PALETTE.length] }} />
                  <div>
                    <div className="text-xs font-bold text-slate-700">{label}</div>
                    <div className="text-xs text-slate-400 mt-0.5 line-clamp-2">{q}</div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(msg => (
          <div key={msg.id} className={cn(
            "flex gap-3",
            msg.role === 'user' ? 'justify-end' : 'justify-start'
          )}>
            {msg.role === 'assistant' && (
              <div className="flex-none w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center mt-0.5 shadow-sm">
                <Sparkles className="h-4 w-4 text-white" />
              </div>
            )}
            <div className={cn(
              "space-y-3",
              msg.role === 'user'
                ? 'max-w-[75%] items-end flex flex-col'
                : 'flex-1 min-w-0' /* assistant answers occupy the entire width */
            )}>
              {msg.role === 'user' ? (
                <div className="bg-gradient-to-r from-indigo-600 to-violet-600 text-white rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm shadow-sm">
                  {msg.content}
                </div>
              ) : (
                <>
                  {/* Summary text (assistant text reply) */}
                  {msg.content && (
                    <div className="text-sm text-slate-700 leading-relaxed">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                    </div>
                  )}
                  {/* Power BI-style dashboard output */}
                  {msg.result && <ResultDashboard result={msg.result} />}
                </>
              )}
            </div>
          </div>
        ))}

        {/* Loading state — pipeline progress */}
        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="flex-none w-8 h-8 rounded-full bg-indigo-600 flex items-center justify-center">
              <Loader2 className="h-4 w-4 text-white animate-spin" />
            </div>
            <div className="bg-white rounded-2xl rounded-tl-sm border border-slate-100 shadow-sm px-5 py-4 max-w-sm w-full">
              <div className="text-xs font-semibold text-slate-500 mb-3 flex items-center gap-1.5">
                <Zap className="h-3.5 w-3.5 text-amber-500" />
                Running AI Analyst Pipeline…
              </div>
              <PipelineProgress elapsed={elapsed} />
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-red-700">
            <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">Query failed</div>
              <div className="text-red-600">{error}</div>
            </div>
            <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ── */}
      <div className="flex-none bg-white border-t border-slate-200 px-4 py-3">
        {/* Follow-up / New question toggle — only shown when there is a previous result */}
        {messages.some(m => m.role === 'assistant' && m.result) && (
          <div className="flex items-center gap-2 mb-2.5">
            <button
              onClick={() => setIsNewQuestion(false)}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all border",
                !isNewQuestion
                  ? "bg-indigo-600 text-white border-indigo-600 shadow-sm"
                  : "bg-white text-slate-500 border-slate-200 hover:border-indigo-300 hover:text-indigo-600"
              )}>
              <ArrowRight className="h-3 w-3" />
              Follow-up
            </button>
            <button
              onClick={() => { setIsNewQuestion(true); setInput(''); }}
              className={cn(
                "flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all border",
                isNewQuestion
                  ? "bg-emerald-600 text-white border-emerald-600 shadow-sm"
                  : "bg-white text-slate-500 border-slate-200 hover:border-emerald-400 hover:text-emerald-600"
              )}>
              <Sparkles className="h-3 w-3" />
              New question
            </button>
            {isNewQuestion && (
              <span className="text-xs text-emerald-600 font-medium ml-1">
                Next question will run independently
              </span>
            )}
          </div>
        )}
        <div className="flex items-end gap-2.5">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={loading}
              placeholder="Ask anything — e.g. 'Show top 10 customers by revenue last quarter'"
              className={cn(
                "w-full resize-none rounded-xl border border-slate-200 bg-slate-50",
                "px-4 py-3 pr-12 text-sm text-slate-800 placeholder:text-slate-400",
                "focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent",
                "disabled:opacity-50 max-h-32 overflow-y-auto",
                "transition-all leading-relaxed"
              )}
              style={{ scrollbarWidth: 'thin' }}
              onInput={e => {
                const el = e.currentTarget;
                el.style.height = 'auto';
                el.style.height = Math.min(el.scrollHeight, 128) + 'px';
              }}
            />
          </div>
          <button
            onClick={() => sendQuestion(input)}
            disabled={!input.trim() || loading}
            className={cn(
              "flex-none w-10 h-10 rounded-xl flex items-center justify-center transition-all",
              input.trim() && !loading
                ? "bg-indigo-600 hover:bg-indigo-700 shadow-md hover:shadow-lg"
                : "bg-slate-200 cursor-not-allowed"
            )}>
            {loading
              ? <Loader2 className="h-4 w-4 text-white animate-spin" />
              : <Send className="h-4 w-4 text-white" />}
          </button>
        </div>
        <div className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-400 px-1">
          <Zap className="h-3 w-3 text-amber-400" />
          <span>15-stage pipeline · Auto SQL · Auto charts · No schema browser needed</span>
        </div>
      </div>

    </div>
  );
}
