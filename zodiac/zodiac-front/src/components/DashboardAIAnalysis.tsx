'use client';

/**
 * DashboardAIAnalysis.tsx — Complete Re-Architecture
 * ===================================================
 * Conversational AI analytics with verified database evidence.
 *
 * Pipeline driven (no Schema Browser):
 *   1. User asks a natural language question
 *   2. Backend answers with governed SQL and a structured result
 *   3. Response contains: sql, data, kpis, charts, summary, keyFindings
 *   4. Frontend renders: KPI cards → Charts → Scrollable table → Insights
 */

import { useState, useRef, useEffect, useCallback, useId } from 'react';
import { useRouter } from 'next/navigation';
import { dashboardApi } from '@/lib/api';
import AnalystQuestionPicker from './AnalystQuestionPicker';
import AnalystRagHelp from './AnalystRagHelp';
import BasicSqlTraining from './BasicSqlTraining';
import { publicApiError } from '@/lib/apiErrors';
import { ANALYST_STAGE_LABELS, mergeAnalystProgress, type AnalystProgress } from '@/lib/analystProgress';
import { analystSqlEvidence, analystSqlFields, type AnalystSqlFields } from '@/lib/analystSql';
import { additionalAgentResults, agentStepLabel, agentStepFeedback, type AgentResultSet, type AgentStep } from '@/lib/analystAgent';
import { humanizeFollowups } from '@/lib/followupChips';
import {
  analysisTrustFromResult,
  humanizePublicSummary,
  humanizeDataGapMessage,
  isDataGapResult,
  isInvestigationFailure,
} from '@/lib/analysisTrust';
import {
  analystPathWithoutQuery,
  investigationLaunch,
  shouldTreatAsNew,
} from '@/lib/investigationLaunch';
import {
  ADAPTIVE_CONTEXT_POLICY,
  followupContextForSend,
  lastSuccessfulAnalyticalContext,
  updateLastSuccessfulAnalyticalContext,
  type LastSuccessfulAnalyticalContext,
} from '@/lib/adaptiveChatContext';
import ReactMarkdown from 'react-markdown';
import { analystAnswerText, analystChartCurrency, analystDateCell, comparisonColumnLabel, comparisonYears, defaultAnalystCurrency, isAnalystChartDimension, isAnalystDateColumn, labelComparisonText } from '@/lib/analystPresentation';
import { analystScrollPosition } from '@/lib/analystChatScroll';
import remarkGfm from 'remark-gfm';
import {
  Send, Sparkles, RotateCcw, Copy, Check, Loader2,
  TrendingUp, BarChart3, PieChart as PieIcon,
  LineChart as LineIcon, Table2, Lightbulb, AlertCircle,
  CheckCircle2, ChevronDown, ChevronUp, X,
  ArrowRight, Zap, Database,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import AIChartRenderer from './ai/AIChartRenderer';
import AnalystDrilldown from './ai/AnalystDrilldown';
import { analystNumeric, analystDecimal, matchingResultRow } from '@/lib/analystNumbers';

/** Persist adaptive Full Chat thread id (reuses backend chat_thread_store via ada_ prefix). */
const ADA_THREAD_KEY = 'zodiac_ada_thread_id';

function adaptiveThreadStorageKey(): string {
  try {
    const user = JSON.parse(localStorage.getItem('user_data') || '{}');
    return user.id != null ? `${ADA_THREAD_KEY}:${user.id}` : '';
  } catch { return ''; }
}

function saveAdaptiveThreadId(tid: string) {
  try {
    const key = adaptiveThreadStorageKey();
    if (key) localStorage.setItem(key, tid);
    else sessionStorage.setItem(ADA_THREAD_KEY, tid);
  } catch { /* Chat still works when browser storage is unavailable. */ }
}

function ensureAdaptiveThreadId(): string {
  if (typeof window === 'undefined') return `ada_ssr_${Date.now()}`;
  let tid = '';
  try {
    const key = adaptiveThreadStorageKey();
    tid = (key ? localStorage.getItem(key) : sessionStorage.getItem(ADA_THREAD_KEY)) || '';
  } catch { /* Generate a session when browser storage is unavailable. */ }
  if (!tid.startsWith('ada_')) {
    tid = `ada_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    saveAdaptiveThreadId(tid);
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
  { label: 'Quick calculation', q: 'What is 2 plus 2?' },
  { label: 'Explain a concept', q: 'Explain what an API is in simple language.' },
  { label: 'Highest-profit products', q: 'Show the products with the highest profits.' },
  { label: 'Inventory versus sales', q: 'Show inventory versus sales.' },
  { label: 'Supplier concentration', q: 'Show supplier concentration.' },
  { label: 'What changed this month?', q: 'Show monthly revenue.' },
  { label: 'High stock / low sales', q: 'Which have high inventory but low sales?' },
  { label: 'Products driving growth', q: 'Which products grew the most?' },
];

// ─── Pipeline progress steps ─────────────────────────────────────────────────

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
  if (isAnalystChartDimension(col)) return true;
  if (/^(client|sap_client|client_id|mandt|vbeln|kunnr|kunag|lifnr|matnr|werks|bukrs|vkorg|belnr|posnr|ebeln|ebelp|gjahr|uuid|rfc)$/.test(lk)) return true;
  if (/(^year$|_year$|billing_year|fiscal_year)/.test(lk)) return true;
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
  return analystNumeric(v);
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
type QueryResult = AnalystSqlFields & {
  data?: any[];
  rowCount?: number;
  totalCount?: number;
  sqlStrategy?: string;
  summary?: string;
  answer?: string;
  keyFindings?: string[];
  kpis?: KPI[];
  charts?: Chart[];
  suggested_followups?: string[];
  answer_status?: string;
  failure_class?: string;
  query_plan?: any;
  agent_results?: AgentResultSet[];
  agent_primary_result_id?: string;
  column_semantics?: Record<string, { semantic_type?: string; precision?: number; format?: string }>;
  mode?: string;
  route?: string;
  type?: string;
  calculation?: {
    source?: string;
    definition?: string;
    aggregation?: string;
    period?: string;
    grain?: string;
    limitations?: string[];
  };
  meta?: {
    provider?: string;
    analysis_method?: string;
    retrieval?: {reused?: boolean; examples?: number; method?: string; queries?: number};
    gemini_field_lookup?: {called?: boolean; status?: string; field?: string};
    basic_fallback?: string;
    basic_training_reference?: {id: string; question: string};
    basic_pattern_confirmation?: {question: string; logic: string; warning?: string};
    result_reference?: {id: string; measures: string[]; created_at: string};
    drilldown_unavailable?: string;
    usage?: {total_tokens: number; input_tokens: number; cached_tokens: number; output_tokens: number; reasoning_tokens: number; calls: unknown[]; estimated_cost_usd: string | null; models?: string[]};
    domain?: string;
    intent?: string;
    schema_tables?: string[];
    pipeline_ms?: number;
    warnings?: string[];
    deep_analysis?: boolean;
    mode?: string;
    investigation_status?: string;
    failure_class?: string;
    service_issue?: string;
    data_gap?: boolean;
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
  const [copyFailed, setCopyFailed] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (timeoutRef.current) clearTimeout(timeoutRef.current); }, []);
  return {
    copied,
    copyFailed,
    copy: (text: string) => {
      setCopyFailed(false);
      if (!navigator.clipboard) { setCopyFailed(true); return; }
      navigator.clipboard.writeText(text).then(() => {
        setCopied(true);
        if (timeoutRef.current) clearTimeout(timeoutRef.current);
        timeoutRef.current = setTimeout(() => setCopied(false), 2000);
      }).catch(() => setCopyFailed(true));
    },
  };
}

function CopyAnswer({ text }: { text: string }) {
  const { copied, copyFailed, copy } = useCopy();
  return <button type="button" onClick={() => copy(text)} aria-label="Copy answer"
    className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-slate-100 hover:text-slate-700">
    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    <span role="status">{copied ? 'Copied' : copyFailed ? 'Copy unavailable' : 'Copy answer'}</span>
  </button>;
}

// ═══════════════════════════════════════════════════════════════════════════════
// KPI Cards
// ═══════════════════════════════════════════════════════════════════════════════
function KPICards({ kpis }: { kpis: KPI[] }) {
  if (!kpis?.length) return null;
  const icons = [TrendingUp, BarChart3, PieIcon, LineIcon];
  return (
    <div className="grid gap-3 mb-4" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 180px), 1fr))' }}>
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
              <span className="text-xs text-slate-500 font-semibold tracking-wide break-words">{kpi.label}</span>
            </div>
            <div className="text-xl sm:text-2xl font-bold text-slate-900 mb-1 tabular-nums break-words">{kpi.value}</div>
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
function ChartsGrid({ charts, onSelect }: { charts: any[]; onSelect?: (row: any) => void }) {
  const [selectedCurrency, setSelectedCurrency] = useState('');
  if (!charts?.length) return null;

  // Backend now sends Recharts spec objects: { chart_type, title, data, x_key, y_keys, ... }.
  // Legacy shape was { type, labels, datasets }. Normalize BOTH into the spec shape and
  // render through AIChartRenderer (rich formatting, currency, dual axes).
  const specs = charts
    .map((c) => {
      const cleanTitle = (t: string | undefined) => {
        const s = (t || '').trim();
        if (!s || /continuation/i.test(s)) return 'Results';
        return s;
      };
      if (c && Array.isArray(c.data) && (c.chart_type || c.x_key || c.y_keys || c.name_key)) {
        return { ...c, title: cleanTitle(c.title) };
      }
      if (c && Array.isArray(c.labels) && Array.isArray(c.datasets)) {
        const data = c.labels.map((label: string, i: number) => {
          const row: Record<string, any> = { name: label };
          for (const ds of c.datasets) row[ds.label] = ds.data?.[i] ?? null;
          return row;
        });
        return {
          chart_type: c.type || 'bar',
          title: cleanTitle(c.title),
          data,
          x_key: 'name',
          y_keys: c.datasets.map((d: any) => d.label),
        };
      }
      return null;
    })
    .filter((c) => c && Array.isArray(c.data) && c.data.length > 0);

  if (!specs.length) return null;
  const currencies = Array.from(new Set(specs.map(analystChartCurrency).filter(Boolean)));
  const showSelector = currencies.length > 1;
  const activeCurrency = currencies.includes(selectedCurrency)
    ? selectedCurrency : defaultAnalystCurrency(specs);
  const visible = showSelector
    ? specs.filter(spec => analystChartCurrency(spec) === activeCurrency)
    : specs;
  return (
    <div className="mb-4 min-w-0">
      {showSelector && (
        <div className="flex flex-wrap items-center gap-3 mb-3 rounded-xl border border-slate-200 bg-white px-4 py-3">
          <label className="text-xs font-medium text-slate-700">
            Chart currency
            <select value={activeCurrency} onChange={event => setSelectedCurrency(event.target.value)}
              className="ml-2 min-h-10 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm"
              aria-label="Chart currency">
              {currencies.map(currency => <option key={currency} value={currency}>{currency}</option>)}
            </select>
          </label>
          <span className="text-xs text-slate-500">{currencies.length} currencies available. The table includes every currency.</span>
        </div>
      )}
      <AIChartRenderer charts={visible as any} onSelect={onSelect} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Data table — fully scrollable horizontal + vertical
// ═══════════════════════════════════════════════════════════════════════════════
function exportCsv(data: any[], filename: string) {
  if (!data?.length) return;
  const headers = Object.keys(data[0]);
  const lines = [
    headers.join(','),
    ...data.map((row) =>
      headers
        .map((h) => {
          const v = row[h] == null ? '' : String(row[h]);
          return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
        })
        .join(','),
    ),
  ];
  const blob = new Blob(['\uFEFF' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function DataTable({
  data,
  rowCount,
  totalCount,
  heading,
  columnSemantics,
  question = '',
}: {
  data: any[];
  rowCount?: number;
  totalCount?: number;
  heading?: string;
  columnSemantics?: QueryResult['column_semantics'];
  question?: string;
}) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const pageSize = 25;

  if (!data?.length) return null;

  const headers = data?.length ? Object.keys(data[0]) : [];
  const isEmpty = !data?.length;
  const filtered = (data || []).filter((row) => {
    if (!filter.trim()) return true;
    const q = filter.trim().toLowerCase();
    return Object.values(row).some((v) => String(v ?? '').toLowerCase().includes(q));
  });
  const sorted = [...filtered].sort((a, b) => {
    if (!sortKey) return 0;
    const av = a[sortKey];
    const bv = b[sortKey];
    const an = cellNum(av);
    const bn = cellNum(bv);
    let cmp = 0;
    if (Number.isFinite(an) && Number.isFinite(bn)) cmp = an - bn;
    else cmp = String(av ?? '').localeCompare(String(bv ?? ''));
    return sortDir === 'asc' ? cmp : -cmp;
  });
  const pageCount = Math.max(1, Math.ceil(sorted.length / pageSize));
  const pageRows = sorted.slice(page * pageSize, (page + 1) * pageSize);

  const toggleSort = (h: string) => {
    if (sortKey === h) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(h);
      setSortDir('desc');
    }
    setPage(0);
  };

  return (
    <div className="min-w-0 bg-white rounded-xl border border-slate-200 shadow-sm mb-4 overflow-hidden">
      <div className="flex flex-wrap items-center justify-between px-3 sm:px-4 py-3 border-b border-slate-100 gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <Table2 className="h-4 w-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-700">
            {isEmpty
              ? <span className="text-amber-700">No rows for this question</span>
              : `${heading || 'Results'} · ${data.length.toLocaleString()} ${rowCount && rowCount > data.length ? `sample rows of ${rowCount.toLocaleString()} returned` : 'rows'}`}
          </span>
        </div>
        <div className="flex w-full sm:w-auto items-center gap-2 min-w-0">
          {!isEmpty && (
            <input
              type="search"
              value={filter}
              onChange={(e) => { setFilter(e.target.value); setPage(0); }}
              placeholder="Filter rows"
              aria-label="Filter table rows"
              className="min-w-0 flex-1 sm:flex-none sm:w-44 min-h-10 text-xs rounded-lg border border-slate-200 bg-slate-50 px-3 py-2"
            />
          )}
          {!isEmpty && (
            <button
              type="button"
              onClick={() => exportCsv(sorted, 'bridgeedi-analysis.csv')}
              className="shrink-0 min-h-10 text-xs font-medium text-slate-600 hover:text-slate-900 px-3 py-2 rounded-lg border border-slate-200 hover:bg-slate-50"
            >
              Export CSV
            </button>
          )}
        </div>
      </div>

      {!isEmpty && (
        <>
          <div className="overflow-auto max-h-[420px]" role="region" aria-label={`${heading || 'Results'} data table; scroll for more columns`} tabIndex={0} style={{ scrollbarWidth: 'thin' }}>
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-slate-50">
                  {headers.map(h => (
                    <th key={h} className="px-3 py-2.5 text-left font-semibold text-slate-600 uppercase tracking-wide whitespace-nowrap border-b border-slate-200" scope="col" aria-sort={sortKey === h ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                      <button type="button" onClick={() => toggleSort(h)} className="min-h-8 hover:text-slate-900">
                        {comparisonColumnLabel(h, question)}{sortKey === h ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pageRows.map((row, i) => (
                  <tr key={i} className={i % 2 === 0 ? 'bg-white' : 'bg-slate-50/60'}>
                    {headers.map(h => {
                      const v = row[h];
                      const n = cellNum(v);
                      const sem = columnSemantics?.[h];
                      const isDate = isAnalystDateColumn(h, sem?.semantic_type);
                      const isPct = sem?.semantic_type === 'percentage';
                      const isInt = sem?.semantic_type === 'integer';
                      const isNum = !isIdLike(h, v) && !isDate && Number.isFinite(n);
                      const display = (() => {
                        if (v == null) return null;
                        if (isDate) {
                          return analystDateCell(h, v, sem?.semantic_type) ?? String(v);
                        }
                        if (isPct && Number.isFinite(n)) return `${n.toFixed(2)}%`;
                        if (isInt && Number.isFinite(n)) return Math.round(n).toLocaleString('en-US');
                        if (isNum) {
                          const digits = isMoneyName(h) || sem?.semantic_type === 'money' ? 2 : (sem?.precision ?? 2);
                          return analystDecimal(v, digits);
                        }
                        return String(v);
                      })();
                      return (
                        <td key={h} title={v == null ? undefined : String(v)} className={cn(
                          'px-3 py-3 whitespace-nowrap border-b border-slate-100 max-w-[320px] overflow-hidden text-ellipsis',
                          isNum ? 'text-right tabular-nums text-slate-800' : 'text-slate-700',
                          isNum && n < 0 ? 'text-red-700' : ''
                        )}>
                          {display == null
                            ? <span className="text-slate-400">—</span>
                            : display}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {pageCount > 1 && (
            <div className="flex items-center justify-between px-4 py-2 border-t border-slate-100 text-xs text-slate-600">
              <span>Page {page + 1} of {pageCount}</span>
              <div className="flex gap-2">
                <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="min-h-10 px-3 rounded-lg hover:bg-slate-100 disabled:opacity-40">Previous</button>
                <button type="button" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)} className="min-h-10 px-3 rounded-lg hover:bg-slate-100 disabled:opacity-40">Next</button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Insights panel
// ═══════════════════════════════════════════════════════════════════════════════
// Internal reason codes must never surface to a business user.
const INTERNAL_REASON_CODES = new Set([
  'too_short','no_business_signal','non_business','empty_question',
  'unsafe_or_non_business','business_token','year','followup_context',
  'schema','deep_analytical_followup','clarification','needs_clarification',
]);
function humanizeFindings(findings?: string[]): string[] {
  if (!Array.isArray(findings)) return [];
  return findings
    .map((f) => String(f || '').trim())
    .filter(Boolean)
    .filter((f) => {
      const key = f.toLowerCase();
      if (INTERNAL_REASON_CODES.has(key)) return false;
      if (/^[a-z]+(_[a-z]+)+$/.test(key)) return false; // bare snake_case code
      if (/sql generation|query generation failed|no unrelated edi fallback/i.test(f)) return false;
      if (/^[\{\[\(]/.test(f) && /[:\],]/.test(f)) return false;
      return true;
    });
}

function AnswerMarkdown({ text }: { text: string }) {
  const readableStyle = { maxWidth: '48rem' };
  return (
    <div className="analyst-prose min-w-0 text-sm leading-7 break-words [&_p]:mb-3 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-3 [&_li]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-3 [&_h2]:font-semibold [&_h2]:text-base [&_h2]:mt-4 [&_h2]:mb-2 [&_h3]:font-semibold [&_h3]:mt-4 [&_h3]:mb-2 [&_th]:px-3 [&_th]:py-2 [&_th]:text-left [&_th]:bg-slate-50 [&_td]:px-3 [&_td]:py-2 [&_tr]:border-b [&_tr]:border-slate-200 [&_code]:text-xs [&_pre]:overflow-x-auto">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={{
        p: ({ children }) => <p style={readableStyle}>{children}</p>,
        ul: ({ children }) => <ul style={readableStyle}>{children}</ul>,
        ol: ({ children }) => <ol style={readableStyle}>{children}</ol>,
        h1: ({ children }) => <h1 style={readableStyle}>{children}</h1>,
        h2: ({ children }) => <h2 style={readableStyle}>{children}</h2>,
        h3: ({ children }) => <h3 style={readableStyle}>{children}</h3>,
        h4: ({ children }) => <h4 style={readableStyle}>{children}</h4>,
        blockquote: ({ children }) => <blockquote style={readableStyle}>{children}</blockquote>,
        table: ({ children }) => (
          <div className="max-w-full overflow-x-auto my-4 rounded-xl border border-slate-200" role="region" aria-label="Answer table; scroll for more columns" tabIndex={0}>
            <table className="w-full border-collapse whitespace-nowrap text-xs sm:text-sm">{children}</table>
          </div>
        ),
      }}>{text}</ReactMarkdown>
    </div>
  );
}

function ConversationCard({ message }: { message: string }) {
  return (
    <div className="py-1 mb-3">
      <div className="text-slate-800"><AnswerMarkdown text={message} /></div>
    </div>
  );
}

function ClarificationCard({ message, followups, onAskFollowup }: {
  message: string;
  followups?: string[];
  onAskFollowup?: (q: string) => void;
}) {
  const examples = humanizeFollowups(followups);
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 mb-4">
      <p className="text-sm text-slate-800 whitespace-pre-line">{message}</p>
      {examples.length > 0 && onAskFollowup && (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {examples.map((e) => (
            <button key={e.question} type="button" onClick={() => onAskFollowup(e.question)}
              className="text-left text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 hover:bg-slate-100 transition-colors">
              {e.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function BasicPatternConfirmationCard({ confirmation, onUseBasicPattern, onUseAgentic, onOpenSqlTraining }: {
  confirmation: { question: string; logic: string; warning?: string };
  onUseBasicPattern?: (q: string) => void;
  onUseAgentic?: (q: string) => void;
  onOpenSqlTraining?: (q: string) => void;
}) {
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 mb-4">
      <h4 className="text-sm font-semibold text-amber-950">Basic found a predefined SQL pattern</h4>
      <p className="mt-2 text-sm text-amber-950">Proposed logic: <strong>{confirmation.logic}</strong>.</p>
      {confirmation.warning && <p role="alert" className="mt-2 text-sm font-medium text-red-800">{confirmation.warning}.</p>}
      <p className="mt-2 text-sm text-amber-900">Basic has not run this query yet. The Basic pattern uses 0 model calls. Agentic may use API credits; SQL Training lets you define and check your own query.</p>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={() => onUseBasicPattern?.(confirmation.question)}
          className="rounded-lg bg-amber-800 px-3 py-2 text-xs font-semibold text-white hover:bg-amber-900">
          Run: {confirmation.logic}
        </button>
        <button type="button" onClick={() => onUseAgentic?.(confirmation.question)}
          className="rounded-lg border border-indigo-300 bg-white px-3 py-2 text-xs font-semibold text-indigo-800 hover:bg-indigo-50">
          Ask Agentic to investigate
        </button>
        <button type="button" onClick={() => onOpenSqlTraining?.(confirmation.question)}
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50">
          Define it in SQL Training
        </button>
      </div>
    </div>
  );
}

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
function SummaryCard({ summary, intent }: { summary: string; intent?: string }) {
  return (
    <div className="py-1 mb-4">
      <div className="prose prose-sm prose-slate max-w-none text-slate-700 text-sm leading-relaxed">
        <AnswerMarkdown text={humanizePublicSummary(summary, intent)} />
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Meta strip (pipeline info)
// ═══════════════════════════════════════════════════════════════════════════════
function MetaStrip({ meta, sqlStrategy: _sqlStrategy, rowCount, totalCount }: {
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
        <span>View SQL sources</span>
        {rowCount != null && <><span className="text-slate-300">·</span><span>{rowCount.toLocaleString()} rows{totalCount && totalCount > rowCount ? ` of ${totalCount.toLocaleString()}` : ''}</span></>}
        {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
      </button>
      {open && (
        <div className="mt-2 p-3 rounded-lg bg-slate-50 border border-slate-100 text-xs text-slate-600 space-y-1">
          {tables.length > 0 && <div><span className="font-medium">Data sources:</span> {tables.join(', ')}</div>}
          {ms != null && <div><span className="font-medium">Processing time:</span> {ms} ms</div>}
          {meta.domain  && <div><span className="font-medium">Business area:</span> {meta.domain}</div>}
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
function AnalysisProgress({ elapsed, progress }: { elapsed: number; progress: AnalystProgress }) {
  const totalElapsed = Math.max(elapsed, (progress.elapsed_s || 0) * 1000);
  const stage = progress.pipeline_stage || 'UNDERSTANDING';
  const label = ANALYST_STAGE_LABELS[stage] || 'Working on your question';
  const history = (progress.stages || []).filter((step, i, list) =>
    ANALYST_STAGE_LABELS[step.pipeline_stage] && (i === 0 || step.pipeline_stage !== list[i - 1].pipeline_stage));
  const previousSteps = history[history.length - 1]?.pipeline_stage === stage
    ? history.slice(0, -1) : history;
  return (
    <div className="space-y-3 py-1">
      <div className="flex items-center gap-3 text-sm font-medium text-indigo-700" role="status">
        <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin" />
        <span>{label}</span>
      </div>
      <p className="text-xs text-slate-500 pl-7" aria-live="off">
        {Math.floor(totalElapsed / 1000)}s elapsed
        {progress.stage_elapsed_s != null && ` · ${Math.floor(progress.stage_elapsed_s)}s on this step`}
      </p>
      {previousSteps.length > 0 && (
        <ol className="space-y-1.5 pl-7 text-xs text-slate-500" aria-label="Previous analysis steps">
          {previousSteps.slice(-6).map((step, i) => (
            <li key={`${step.pipeline_stage}-${i}`} className="flex items-center gap-2">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-400" aria-hidden="true" />
              <span>{ANALYST_STAGE_LABELS[step.pipeline_stage]}</span>
            </li>
          ))}
        </ol>
      )}
      {totalElapsed > 15000 && <p className="text-xs text-slate-500 pl-7">Still working on this step. You can stop the analysis at any time.</p>}
    </div>
  );
}

function StatusOutcomeCard({
  heading,
  message,
  tone,
}: {
  heading: string;
  message: string;
  tone: 'amber' | 'slate' | 'rose';
}) {
  const tones = {
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    slate: 'border-slate-200 bg-slate-50 text-slate-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-800',
  };
  return (
    <div className={`rounded-xl border p-4 space-y-2 ${tones[tone]}`} role="status">
      <p className="text-[11px] font-semibold uppercase tracking-wide">{heading}</p>
      <p className="text-sm text-slate-800 leading-relaxed">{message}</p>
    </div>
  );
}

function DataGapCard({
  message,
  followups,
  onAskFollowup,
}: {
  message: string;
  followups?: string[];
  onAskFollowup?: (q: string) => void;
}) {
  const chips = humanizeFollowups(followups);
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3" role="status">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">Data limitation</p>
      <p className="text-sm text-slate-800 leading-relaxed">{humanizeDataGapMessage(message)}</p>
      <p className="text-xs text-slate-600">
        This is not an application failure. The question was understood, but the required data is not in this extract.
        No unsupported number was calculated. Previous conversation context is kept.
      </p>
      {chips.length > 0 && onAskFollowup && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-900 mb-1.5">Try instead</p>
          <div className="flex flex-wrap gap-1.5">
            {chips.map((chip) => (
              <button
                key={chip.question}
                type="button"
                onClick={() => onAskFollowup(chip.question)}
                className="text-left text-xs px-2.5 py-1.5 rounded-lg border border-amber-200 bg-white text-slate-800 hover:bg-amber-100"
              >
                {chip.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function TrustPanel({ result }: { result: QueryResult }) {
  const [open, setOpen] = useState(false);
  const trust = analysisTrustFromResult(result);
  return (
    <div className="mb-3 rounded-lg border border-slate-200 bg-white">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-center justify-between px-3 py-2 text-xs font-medium text-slate-600 hover:bg-slate-50"
      >
        <span>How this was calculated</span>
        {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
      </button>
      {open && (
        <div className="px-3 pb-3 text-xs text-slate-600 space-y-1.5 border-t border-slate-100 pt-2">
          {trust.domain && <p><span className="font-semibold text-slate-800">Domain:</span> {trust.domain}</p>}
          {trust.source && <p><span className="font-semibold text-slate-800">Source:</span> {trust.source}</p>}
          {trust.tables && <p><span className="font-semibold text-slate-800">Tables:</span> {trust.tables}</p>}
          {trust.joins && <p><span className="font-semibold text-slate-800">Join path:</span> {trust.joins}</p>}
          {trust.calculation && <p><span className="font-semibold text-slate-800">Definition:</span> {trust.calculation}</p>}
          {trust.aggregation && <p><span className="font-semibold text-slate-800">Aggregation:</span> {trust.aggregation}</p>}
          <p><span className="font-semibold text-slate-800">Period:</span> {trust.period}</p>
          {trust.grain && <p><span className="font-semibold text-slate-800">Grain:</span> {trust.grain}</p>}
          {trust.rowLimit && <p><span className="font-semibold text-slate-800">Result size:</span> {trust.rowLimit}</p>}
          {trust.limitations.length === 0 ? (
            <p><span className="font-semibold text-slate-800">Limitations:</span> None reported for this result.</p>
          ) : trust.limitations.map((g) => (
            <p key={g} className="text-amber-800"><span className="font-semibold">Limitations:</span> {g}</p>
          ))}
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Conversational answer with inspectable data and execution evidence
// ═══════════════════════════════════════════════════════════════════════════════
function TeachBasic({ reference }: { reference: { id: string; question: string } }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState(false);
  return (
    <div className="space-y-2 rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs text-slate-500">Happy with this result? Save its checked SQL, then ask the saved question in Basic for fresh data with no model tokens.</p>
      <button type="button" disabled={busy || saved} onClick={async () => {
        setBusy(true); setMessage(''); setFailed(false);
        try {
          const result = await dashboardApi.teachBasic(reference.id, reference.question);
          setMessage(result.message);
          setSaved(true);
          window.dispatchEvent(new Event('basic-queries-saved'));
        } catch (error) {
          setFailed(true); setMessage(error instanceof Error ? error.message : 'Could not save this example.');
        } finally { setBusy(false); }
      }} className="rounded-full bg-slate-900 px-3 py-1.5 text-xs text-white disabled:opacity-50">
        {busy ? 'Saving…' : saved ? 'Saved in Basic Model' : 'Reuse it in Basic Model'}
      </button>
      {message && <p role={failed ? 'alert' : 'status'} className={cn('text-xs', failed ? 'text-red-700' : 'text-emerald-700')}>{message}</p>}
    </div>
  );
}

function ResultDashboard({
  result,
  onAskFollowup,
  onUseBasicPattern,
  onUseAgentic,
  onOpenSqlTraining,
}: {
  result: QueryResult;
  onAskFollowup?: (q: string) => void;
  onUseBasicPattern?: (q: string) => void;
  onUseAgentic?: (q: string) => void;
  onOpenSqlTraining?: (q: string) => void;
}) {
  const basicPath = result.meta?.analysis_method === 'basic'
    ? result.meta.retrieval?.reused
      ? `Checked SQL replay${result.meta.retrieval.queries ? ` · ${result.meta.retrieval.queries} queries` : ''}`
      : result.meta.provider === 'ollama' || result.meta.provider === 'groq'
        ? 'Basic model investigation'
        : result.sql_status === 'executed'
          ? 'Basic SQL pattern'
          : ''
    : '';
  return (
    <div className="space-y-3">
      {basicPath && <p className="inline-flex rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-800" aria-label={`Answer path: ${basicPath}`}>{basicPath}</p>}
      {result.meta?.gemini_field_lookup?.called && <p className="text-xs text-slate-600" role="status">
        {result.meta.gemini_field_lookup.status === 'validated'
          ? `Gemini suggested a field for ${result.meta.gemini_field_lookup.field}; Basic confirmed that column exists in live schema before investigating. This lookup used Gemini API quota.`
          : `Gemini could not provide a column confirmed by live schema for ${result.meta.gemini_field_lookup.field}. Basic continued without that hint; the lookup may have used Gemini API quota.`}
      </p>}
      {result.meta?.basic_fallback && <p role="status" className="text-xs text-slate-500">Basic could not safely reuse a saved query. Agentic handled this request; model calls may use credits.</p>}
      <ResultContent result={result} onAskFollowup={onAskFollowup} onUseBasicPattern={onUseBasicPattern}
        onUseAgentic={onUseAgentic} onOpenSqlTraining={onOpenSqlTraining} />
      {additionalAgentResults(result).map(set => (
        <details key={set.id} className="rounded-xl border border-slate-200 bg-white">
          <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-slate-600">
            Supporting data · {set.row_count ?? set.rows.length} rows
          </summary>
          <div className="space-y-2 px-2 pb-2 sm:px-3">
          <DataTable data={set.rows} rowCount={set.row_count} heading="Supporting result" />
          {set.truncated && <p className="text-xs text-slate-500">This table shows a bounded sample.</p>}
          {set.sql && <SqlDisclosure result={{ sql: set.sql, sql_status: 'executed', answer_status: 'SUCCESS' }} />}
          </div>
        </details>
      ))}
      {Array.isArray(result.query_plan?.agent_trace) && result.query_plan.agent_trace.length > 0 && (
        <details className="rounded-xl border border-slate-200 bg-white px-4 py-3">
          <summary className="cursor-pointer text-xs font-medium text-slate-700">Steps taken</summary>
          <ol className="mt-3 space-y-2 text-xs text-slate-600">
            {result.query_plan.agent_trace.map((step: AgentStep, index: number) => (
              <li key={index}>
                {index + 1}. {agentStepLabel(step)}
                {agentStepFeedback(step) && <p className="mt-1 text-slate-500">{agentStepFeedback(step)}</p>}
              </li>
            ))}
          </ol>
        </details>
      )}
      <SqlDisclosure result={result} />
      {result.meta?.basic_training_reference && <TeachBasic key={result.meta.basic_training_reference.id} reference={result.meta.basic_training_reference} />}
    </div>
  );
}

function SqlDisclosure({ result }: { result: QueryResult }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const { copied, copy } = useCopy();
  const evidence = analystSqlEvidence(result);
  if (!evidence) {
    return null;
  }
  return (
    <div className="rounded-xl border border-slate-200 bg-white overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(value => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={open ? 'Collapse SQL query' : 'Expand SQL query'}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-slate-50"
      >
        <span className="flex items-center gap-2 text-xs font-medium text-slate-700">
          <Database className="h-4 w-4 flex-shrink-0 text-slate-400" />
          {evidence.label}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-indigo-700 flex-shrink-0">
          {open ? 'Collapse SQL' : 'Expand SQL'}
          {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>
      <div id={panelId} role="region" aria-label={evidence.label} hidden={!open}>
        <p className="border-t border-slate-100 px-4 py-2 text-xs text-slate-600">{evidence.explanation}</p>
        <div className="relative max-h-[60vh] overflow-auto px-4 py-3 bg-slate-950 text-slate-200 text-xs font-mono">
          <button
            type="button"
            onClick={() => copy(evidence.sql)}
            aria-label="Copy SQL query"
            className="sticky float-right top-2 z-10 p-1.5 rounded bg-slate-700 hover:bg-slate-600"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <pre className="whitespace-pre leading-relaxed">{evidence.sql}</pre>
        </div>
      </div>
    </div>
  );
}

function ResultContent({ result, onAskFollowup, onUseBasicPattern, onUseAgentic, onOpenSqlTraining }: {
  result: QueryResult;
  onAskFollowup?: (q: string) => void;
  onUseBasicPattern?: (q: string) => void;
  onUseAgentic?: (q: string) => void;
  onOpenSqlTraining?: (q: string) => void;
}) {
  const [drillRow, setDrillRow] = useState<number | null>(null);
  if (!result) return null;
  const { kpis, charts, summary, keyFindings, data, totalCount, sqlStrategy, rowCount, meta, suggested_followups } = result;

  const hasKpis    = (kpis?.length ?? 0) > 0;
  const hasCharts  = (charts?.length ?? 0) > 0;
  const hasData    = (data?.length ?? 0) > 0;
  const question = String(result.query_plan?.effective_question || '');
  const years = comparisonYears(question);
  const fullAnswer = labelComparisonText(analystAnswerText(result), question);
  const hasSummary = !!fullAnswer;
  const cleanFindings = humanizeFindings(keyFindings).filter(f => f !== summary && f !== fullAnswer);
  const hasInsights = cleanFindings.length > 0 && cleanFindings[0] !== 'No results found.';
  const followups = humanizeFollowups(suggested_followups);
  const status = String(result.answer_status || '').toUpperCase();
  const mode = String(result.mode || result.meta?.mode || result.route || '').toLowerCase();
  const isGeneral = mode === 'general_chat' || mode === 'general' || mode === 'database_metadata' || (
    status === 'SUCCESS' && !(result.sql || '').trim() && !hasData && mode !== 'clarification'
  );
  const isTimeout = status === 'TIMEOUT' || mode === 'timeout' || String(result.type || '').toLowerCase() === 'timeout';
  const isEmptySuccess = status === 'SUCCESS_EMPTY' || status === 'NO_DATA';
  const isGap = isDataGapResult(result);
  const isTechFailure = isInvestigationFailure(result);
  const isClarification = status === 'CLARIFICATION' || status === 'NEEDS_CLARIFICATION';
  const trust = analysisTrustFromResult(result);
  const heading = trust.analysisLabel;

  if (isTimeout) {
    return (
      <StatusOutcomeCard
        heading="Timed out"
        message={summary || 'This analysis exceeded the allowed processing time and was stopped.'}
        tone="amber"
      />
    );
  }
  if (status === 'CANCELLED' || mode === 'cancelled') {
    return <StatusOutcomeCard heading="Stopped" message={summary || 'This analysis was stopped.'} tone="slate" />;
  }

  if (isGeneral && !isClarification && !isGap && !isTechFailure) {
    // Metadata list-all: show the text once + optional table of names (no Key Findings echo).
    if (mode === 'database_metadata' && hasData && (data?.length ?? 0) > 1) {
      return (
        <div className="space-y-3">
          <ConversationCard message={fullAnswer} />
          <DataTable
            data={data || []}
            totalCount={totalCount}
            heading="Tables"
            columnSemantics={result.column_semantics}
          />
        </div>
      );
    }
    return <ConversationCard message={fullAnswer || 'Hello! How can I help you today?'} />;
  }

  if (isClarification) {
    return (
      <div className="space-y-3">
        {meta?.basic_pattern_confirmation ? (
          <BasicPatternConfirmationCard confirmation={meta.basic_pattern_confirmation}
            onUseBasicPattern={onUseBasicPattern} onUseAgentic={onUseAgentic} onOpenSqlTraining={onOpenSqlTraining} />
        ) : <ClarificationCard
            message={fullAnswer || 'I need one more detail to answer this accurately.'}
            followups={suggested_followups}
            onAskFollowup={onAskFollowup}
          />}
        {meta?.result_reference && <AnalystDrilldown reference={meta.result_reference} rows={data || []} selectedRow={null} />}
      </div>
    );
  }

  if (isGap) {
    return (
      <DataGapCard
        message={summary || 'The available data does not contain the information required to answer this.'}
        followups={suggested_followups}
        onAskFollowup={onAskFollowup}
      />
    );
  }

  if (isTechFailure) {
    const failure = String(
      result.failure_class || result.meta?.investigation_status || ''
    ).toUpperCase();
    const issue = result.meta?.service_issue
    const heading =
      result.meta?.provider === 'ollama' && issue
        ? 'Local Basic model could not complete'
        : issue === 'quota_exhausted'
        ? 'OpenAI credits needed'
        : issue === 'timeout'
        ? 'Analysis timed out'
        : issue === 'rate_limited'
        ? 'AI service is busy'
        : issue
        ? 'AI service unavailable'
        : failure === 'ANALYSIS_LIMIT_REACHED'
        ? 'Analysis limit reached'
        : failure === 'TOOL_FAILURE' || failure === 'EXECUTION_FAILED'
        ? 'Query could not be completed'
        : failure === 'MODEL_FAILURE' || failure === 'SQL_GENERATION_FAILED'
          ? 'Analysis could not be planned'
          : 'Investigation incomplete';
    const fallback =
      failure === 'TOOL_FAILURE' || failure === 'EXECUTION_FAILED'
        ? "I couldn't complete a verified query for that breakdown. Try asking with one metric and one dimension at a time."
        : "I couldn't verify the requested analysis from the available database evidence.";
    return (
      <StatusOutcomeCard
        heading={heading}
        message={summary || fallback}
        tone="rose"
      />
    );
  }

  if (isEmptySuccess && !hasData) {
    return (
      <div className="space-y-3">
        <StatusOutcomeCard
          heading="No matching records"
          message={summary || 'No matching records were found for the requested period and condition.'}
          tone="slate"
        />
        {hasSummary && summary && !/no matching records/i.test(summary) && (
          <SummaryCard summary={summary} intent={trust.intent} />
        )}
      </div>
    );
  }

  return (
    <div className="space-y-0">
      {years && data?.some(row => row && 'period_a' in row && 'period_b' in row) &&
        <p className="mb-3 rounded-xl bg-indigo-50 px-3 py-2 text-xs font-medium text-indigo-900">
          Period A = {years[0]} · Period B = {years[1]} · Change = {years[1]} minus {years[0]}
        </p>}
      {hasSummary && <SummaryCard summary={fullAnswer} intent={trust.intent} />}
      {hasKpis    && <KPICards kpis={kpis!} />}
      {hasCharts  && <ChartsGrid charts={charts!} onSelect={point => setDrillRow(matchingResultRow(data || [], point))} />}
      {meta?.result_reference && <AnalystDrilldown reference={meta.result_reference} rows={data || []} selectedRow={drillRow} />}
      {meta?.drilldown_unavailable && <p className="mb-3 text-xs text-amber-800">{meta.drilldown_unavailable}</p>}
      {meta?.usage && <details className="mb-3 text-xs text-slate-600"><summary className="cursor-pointer">Usage · {meta.usage.total_tokens?.toLocaleString() || 0} tokens · {meta.usage.calls?.length || 0} model calls</summary><p className="mt-2">Input: {meta.usage.input_tokens} · Cached input: {meta.usage.cached_tokens} · Output: {meta.usage.output_tokens} · Reasoning (included in output): {meta.usage.reasoning_tokens}. {meta.usage.estimated_cost_usd != null ? `Estimated model cost: $${meta.usage.estimated_cost_usd}` : `Dollar cost needs a rate for ${(meta.usage.models || []).join(', ') || 'this model'} in analyst_model_rates.json. The token counts above are the measured usage.`}</p></details>}
      {hasData && <details className="rounded-xl border border-slate-200 bg-white mb-4">
        <summary className="cursor-pointer px-4 py-3 text-xs font-medium text-slate-600">
          View verified data · {(rowCount ?? data?.length ?? 0).toLocaleString()} rows
        </summary>
        <div className="px-2 pb-2 sm:px-3"><DataTable data={data || []} rowCount={rowCount} totalCount={totalCount} heading={heading || 'Results'} columnSemantics={result.column_semantics} question={question} /></div>
      </details>}
      {hasInsights && <InsightsPanel findings={cleanFindings} />}
      {!isGeneral && <TrustPanel result={result} />}
      {followups.length > 0 && onAskFollowup && (
        <div className="mt-3 mb-1 px-1">
          <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 mb-2">
            Next investigation
          </p>
          <div className="flex flex-wrap gap-1.5">
            {followups.map((f) => (
              <button
                key={f.question}
                type="button"
                onClick={() => onAskFollowup(f.question)}
                className="text-left text-xs px-2.5 py-1.5 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-900 hover:bg-emerald-100 transition-colors"
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      )}
      <MetaStrip meta={meta} sqlStrategy={sqlStrategy} rowCount={rowCount} totalCount={totalCount} />
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════════
export default function DashboardAIAnalysis({ initialQuestion }: { initialQuestion?: string } = {}) {
  const router = useRouter();
  const [messages,   setMessages]   = useState<Message[]>([]);
  const [input,      setInput]      = useState('');
  const [loading,    setLoading]    = useState(false);
  const [elapsed,    setElapsed]    = useState(0);
  const [progress, setProgress] = useState<AnalystProgress>({ pipeline_stage: 'UNDERSTANDING' });
  const [error,      setError]      = useState<string | null>(null);
  const [failedQuestion, setFailedQuestion] = useState<string | null>(null);
  const [launchBanner, setLaunchBanner] = useState<string | null>(null);
  const [threadId,   setThreadId]   = useState<string>('');
  const [analysisMethod, setAnalysisMethod] = useState<'agent' | 'basic' | 'training'>('agent');
  const [startFreshQuestion, setStartFreshQuestion] = useState(false);
  const [trainingQuestion, setTrainingQuestion] = useState(initialQuestion);
  const [trainingDraftRevision, setTrainingDraftRevision] = useState(0);
  const trainingQuestionRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (trainingDraftRevision > 0) trainingQuestionRef.current?.focus();
  }, [trainingDraftRevision]);
  const [trainedQueryPickerOpen, setTrainedQueryPickerOpen] = useState(false);
  const [trainedQueries, setTrainedQueries] = useState<{ id: string; question: string; revision: number; source: string; validation_status: string; replayable?: boolean; answerability_issues?: string[]; schema?: { tables?: Record<string, unknown> } }[]>([]);
  const [trainedQueriesLoaded, setTrainedQueriesLoaded] = useState(false);
  const [trainedQueriesLoading, setTrainedQueriesLoading] = useState(false);
  const [trainedQuerySearch, setTrainedQuerySearch] = useState('');
  const [trainedQueryError, setTrainedQueryError] = useState('');
  const selectedSuggestionRef = useRef<string | null>(null);
  const analysisMethodRef = useRef<'agent' | 'basic' | 'training'>('agent');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const conversationRef = useRef<HTMLDivElement>(null);
  const conversationContentRef = useRef<HTMLDivElement>(null);
  const followLatestRef = useRef(true);
  const [scrollPosition, setScrollPosition] = useState({ canGoUp: false, canGoDown: false, nearBottom: true });
  useEffect(() => {
    const saved = window.localStorage.getItem('ai-analyst-method');
    if (saved === 'basic' || saved === 'agent' || saved === 'training') {
      analysisMethodRef.current = saved;
      setAnalysisMethod(saved);
    }
  }, []);
  const timerRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const inputRef    = useRef<HTMLTextAreaElement>(null);
  const initialSentRef = useRef<string | null>(null);
  const lastSuccessfulAnalyticalRef = useRef<LastSuccessfulAnalyticalContext | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const investigationIdRef = useRef<string>('');

  useEffect(() => () => { abortRef.current?.abort(); }, []);

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
          .map((m, i) => {
            const storedRows = Array.isArray(m.result?.data) ? m.result.data : [];
            const storedCount = Number(m.result?.rowCount);
            const rawResult = m.role === 'assistant' && m.result ? {
              ...analystSqlFields(m.result),
              data: storedRows,
              rowCount: Number.isFinite(storedCount)
                ? Math.max(storedCount, storedRows.length)
                : storedRows.length,
              charts: m.result.charts || [],
              meta: m.result.meta || {},
              summary: m.result.summary || m.content,
              answer: m.result.answer || m.content,
              query_plan: m.result.query_plan || m.result.queryPlan || null,
              agent_results: m.result.agent_results || m.result.query_plan?.agent_results,
              agent_primary_result_id: m.result.agent_primary_result_id || m.result.query_plan?.agent_primary_result_id,
              answer_status: m.result.answer_status
                || (m.result.mode === 'general_chat' ? 'SUCCESS'
                  : ((m.result.sql || '').trim() ? 'SUCCESS' : 'SUCCESS')),
              mode: m.result.mode,
              failure_class: m.result.failure_class || m.result.meta?.failure_class,
            } : undefined;
            const intent = rawResult ? analysisTrustFromResult(rawResult).intent : undefined;
            return {
              id: `hist-${i}-${Date.now()}`,
              role: m.role as 'user' | 'assistant',
              content: m.role === 'assistant'
                ? humanizePublicSummary(m.content || '', intent)
                : (m.content || ''),
              result: rawResult ? {
                ...rawResult,
                summary: humanizePublicSummary(rawResult.summary || '', intent),
              } : undefined,
              ts: Date.now() + i,
            };
          });
        if (restored.length > 0) {
          setMessages((prev) => {
            if (prev.length !== 0) return prev;
            lastSuccessfulAnalyticalRef.current = lastSuccessfulAnalyticalContext(restored);
            return restored;
          });
        }
      } catch {
        /* history optional */
      } finally {
        if (!cancelled) setHistoryLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [threadId, historyLoaded]);

  const updateScrollPosition = useCallback(() => {
    const el = conversationRef.current;
    if (!el) return;
    const next = analystScrollPosition(el.scrollTop, el.scrollHeight, el.clientHeight);
    setScrollPosition(previous => previous.canGoUp === next.canGoUp && previous.canGoDown === next.canGoDown
      && previous.nearBottom === next.nearBottom ? previous : next);
  }, []);

  const jumpTo = useCallback((edge: 'top' | 'bottom') => {
    const el = conversationRef.current;
    if (!el) return;
    followLatestRef.current = edge === 'bottom';
    el.scrollTo({ top: edge === 'top' ? 0 : el.scrollHeight,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
  }, []);

  // Follow new replies only when the reader is already near the latest message.
  useEffect(() => {
    const el = conversationRef.current;
    if (el && followLatestRef.current) el.scrollTop = el.scrollHeight;
    updateScrollPosition();
  }, [messages, loading, updateScrollPosition]);

  useEffect(() => {
    const el = conversationRef.current;
    const content = conversationContentRef.current;
    if (!el || !content) return;
    const observer = new ResizeObserver(() => {
      if (followLatestRef.current) el.scrollTop = el.scrollHeight;
      updateScrollPosition();
    });
    observer.observe(content);
    observer.observe(el);
    return () => observer.disconnect();
  }, [updateScrollPosition]);

  // elapsed timer while loading
  useEffect(() => {
    if (loading) {
      setElapsed(0);
      const startedAt = Date.now();
      timerRef.current = setInterval(() => setElapsed(Date.now() - startedAt), 500);
    } else {
      if (timerRef.current) clearInterval(timerRef.current);
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, [loading]);

  const sendQuestion = useCallback(async (question: string, opts?: { asNew?: boolean; retry?: boolean; source?: 'overview-url' | 'overview-chip' | 'followup-chip' | 'explicit-new' | 'saved-restore' | 'typed-continue'; analysisMode?: 'agent' | 'basic'; approveBasicPattern?: boolean; newQuestion?: boolean; trainingExample?: { id: string; revision: number } }) => {
    const q = (question || '').trim().replace(/^undefined/i, '').trim();
    if (!q || loading || !historyLoaded) return;

    const tid = threadId || ensureAdaptiveThreadId();
    if (!threadId) setThreadId(tid);

    setError(null);
    setFailedQuestion(null);
    followLatestRef.current = true;
    setInput('');
    setStartFreshQuestion(false);
    if (inputRef.current) inputRef.current.style.height = 'auto';
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: q, ts: Date.now() };
    if (!opts?.retry) setMessages(prev => [...prev, userMsg]);
    setLoading(true);
    setProgress({ pipeline_stage: 'UNDERSTANDING', elapsed_s: 0, stages: [] });

    // Continuous chat is the default; an explicit new-question choice isolates
    // this ask from earlier messages, SQL, and filters while keeping visible history.
    const fromSuggestion = selectedSuggestionRef.current === q;
    selectedSuggestionRef.current = null;
    const treatAsNew = fromSuggestion || shouldTreatAsNew({
      source: opts?.source,
      asNewFlag: opts?.asNew,
      newQuestionToggle: opts?.newQuestion,
    });
    const contextMessages = opts?.retry ? messages.slice(0, -1) : messages;
    const contextData = followupContextForSend(
      contextMessages,
      lastSuccessfulAnalyticalRef.current,
      treatAsNew,
    );
    const dirty = lastSuccessfulAnalyticalRef.current != null || messages.length > 0;
    const source = (fromSuggestion ? 'saved-restore' : opts?.source)
      || (opts?.asNew ? 'overview-url' : dirty ? 'typed-continue' : 'typed-continue');
    const launch = investigationLaunch(source, dirty);
    if (launch.banner) setLaunchBanner(launch.banner);

    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const investigationId =
      (typeof crypto !== 'undefined' && crypto.randomUUID)
        ? crypto.randomUUID().replace(/-/g, '')
        : `inv_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
    investigationIdRef.current = investigationId;
    let polling = true;
    let poll: ReturnType<typeof setTimeout> | undefined;
    let statusPollDelayMs = 1200;
    const pollStatus = async () => {
      if (!polling || ac.signal.aborted || investigationIdRef.current !== investigationId) return;
      try {
        const st = await dashboardApi.getInvestigationStatus(investigationId, ac.signal);
        if (!polling || ac.signal.aborted || investigationIdRef.current !== investigationId) return;
        setProgress(previous => mergeAnalystProgress(previous, st));
        statusPollDelayMs = 1200;
      } catch {
        // Status polling is auxiliary: a transient poll timeout must not stop
        // the investigation or leave the progress UI frozen until the answer
        // POST completes. Retry with a short capped backoff; the main request
        // remains authoritative for success, failure, and cancellation.
        if (!polling || ac.signal.aborted || investigationIdRef.current !== investigationId) return;
        statusPollDelayMs = Math.min(Math.max(statusPollDelayMs * 2, 1200), 5000);
      }
      if (polling && !ac.signal.aborted && investigationIdRef.current === investigationId) {
        poll = setTimeout(pollStatus, statusPollDelayMs);
      }
    };
    poll = setTimeout(pollStatus, 300);

    try {
      const res = await dashboardApi.postAdaptiveQuery({
        question: q,
        // Explicit null (not omitted) so a dirty thread cannot leak prior SQL/filters.
        contextData: treatAsNew ? null : contextData,
        threadId: tid,
        investigationId,
        newQuestion: treatAsNew,
        analysisMode: opts?.analysisMode || (analysisMethodRef.current === 'training' ? 'basic' : analysisMethodRef.current),
        basicPresetApproved: opts?.approveBasicPattern === true,
        basicTrainingExampleId: opts?.trainingExample?.id,
        basicTrainingRevision: opts?.trainingExample?.revision,
        conversationHistory: treatAsNew ? [] : contextMessages.slice(-40).map(message => ({
          role: message.role, content: message.content.slice(0, 6000), mode: message.result?.mode,
        })),
      }, { signal: ac.signal });

      const answerStatus = res.answer_status || res.answerStatus || '';
      const isTimeout =
        answerStatus === 'TIMEOUT' || res.status === 'timeout' || res.mode === 'timeout' || res.type === 'timeout';
      const isClarification =
        answerStatus === 'CLARIFICATION' || res.type === 'clarification';
      const isCannotAnswer =
        !isTimeout && (
        answerStatus === 'CANNOT_ANSWER' ||
        res.type === 'cannot_answer' ||
        !!res.degraded_fallback);
      const responseData = isCannotAnswer || isTimeout ? [] : (res.data || res.rows || []);
      const reportedRowCount = Number(res.rowCount ?? res.row_count);

      // Normalise response — backend may return old shape or new pipeline shape
      const result: QueryResult = {
        ...analystSqlFields(res),
        data:        responseData,
        rowCount:    isCannotAnswer || isTimeout
          ? 0
          : Number.isFinite(reportedRowCount)
            ? Math.max(reportedRowCount, responseData.length)
            : responseData.length,
        totalCount:  res.totalCount ?? res.total_count ?? -1,
        sqlStrategy: res.sqlStrategy || res.sql_strategy || 'full',
        summary:     humanizePublicSummary(
          res.summary || res.executive_summary || res.answer || '',
          String((res.query_plan || res.queryPlan || {}).analytical_context?.intent || res.intent || ''),
        ),
        answer: res.answer || res.summary || res.executive_summary || '',
        keyFindings: res.keyFindings || res.key_findings || [],
        kpis:        isCannotAnswer || isTimeout ? [] : (res.kpis || []),
        charts:      isCannotAnswer || isTimeout ? [] : (res.charts || res.chart_configs || []),
        suggested_followups: res.suggested_followups || res.suggestedFollowups || [],
        answer_status: isTimeout
          ? 'TIMEOUT'
          : isClarification
          ? 'CLARIFICATION'
          : (answerStatus || (isCannotAnswer ? 'CANNOT_ANSWER' : 'SUCCESS')),
        mode:        res.mode || res.route || res.meta?.mode,
        type:        res.type,
        failure_class: res.failure_class || res.meta?.failure_class || res.meta?.investigation_status,
        calculation: res.calculation,
        meta:        res.meta || {
          domain:        res.domain,
          intent:        res.intent,
          schema_tables: res.schema_tables || res.meta?.schema_tables,
          pipeline_ms:   res.pipeline_ms,
          warnings:      res.warnings || [],
        },
        query_plan: res.query_plan || res.queryPlan,
        agent_results: isCannotAnswer || isTimeout ? [] : res.agent_results,
        agent_primary_result_id: res.agent_primary_result_id,
      };

      const timeoutMessage = 'This analysis exceeded the allowed processing time and was stopped. No unsupported result was returned.';
      const summaryContent = isTimeout
        ? (res.summary || res.answer || timeoutMessage)
        : isCannotAnswer
        ? humanizeDataGapMessage(res.summary || res.answer || 'The available data does not support this question.')
        : res.type === 'analysis' || isClarification
        ? humanizePublicSummary(res.answer || res.summary || 'Done.')
        : (result.summary || (result.rowCount === 0
            ? 'No rows were returned for this question.'
            : `This result includes ${result.rowCount} row(s).`));

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: summaryContent,
        // Keep result for follow-up context even on cannot_answer (plan/status), but no fake rows
        result,
        ts: Date.now(),
      };
      if (!isClarification && !isCannotAnswer && !isTimeout) {
        lastSuccessfulAnalyticalRef.current = updateLastSuccessfulAnalyticalContext(
          lastSuccessfulAnalyticalRef.current,
          q,
          result,
        );
      }
      if (!ac.signal.aborted && investigationIdRef.current === investigationId) setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.name === 'AbortError') {
        return;
      }
      setError(publicApiError(err, 'Could not complete this analysis. Please try rephrasing.'));
      setFailedQuestion(q);
      // Keep the user message visible so history does not silently lose questions
    } finally {
      polling = false;
      if (poll) window.clearTimeout(poll);
      if (investigationIdRef.current === investigationId) setLoading(false);
    }
    // Continuous chat: keep latest turn in the dependency list so follow-ups
    // always see the newest assistant context.
  }, [messages, loading, threadId, historyLoaded]);

  // Auto-run a question handed over from another view (e.g. "What can you ask?"
  // sidebar on the Real-time tab). Guarded so the same question only fires once.
  // Wait for history load so we don't race with restored messages.
  useEffect(() => {
    const q = (initialQuestion || '').trim();
    if (q && historyLoaded && initialSentRef.current !== q && !loading) {
      initialSentRef.current = q;
      if (analysisMethodRef.current === 'training') {
        setTrainingQuestion(q);
        setLaunchBanner('Question copied into Basic SQL Training. Review the schema and SQL; no model was called.');
        router.replace(analystPathWithoutQuery(), { scroll: false });
        return;
      }
      const dirty = lastSuccessfulAnalyticalRef.current != null || messages.length > 0;
      setLaunchBanner(investigationLaunch('overview-url', dirty).banner);
      void sendQuestion(q, { asNew: true, source: 'overview-url' });
      router.replace(analystPathWithoutQuery(), { scroll: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion, historyLoaded]);

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      sendQuestion(input, startFreshQuestion ? { newQuestion: true, source: 'explicit-new' } : undefined);
    }
  };

  const toggleTrainedQueryPicker = async () => {
    if (trainedQueryPickerOpen) { setTrainedQueryPickerOpen(false); return; }
    setTrainedQueryPickerOpen(true);
    if (trainedQueriesLoaded || trainedQueriesLoading) return;
    setTrainedQueriesLoading(true); setTrainedQueryError('');
    try {
      const result = await dashboardApi.getBasicTrainingExamples();
      // Fail closed when connected to an API version that does not return the
      // semantic replay check. A stale checked SQL example must never be run
      // just because the old server still labels it "executed".
      setTrainedQueries(result.examples || []);
      setTrainedQueriesLoaded(true);
    } catch (cause) {
      setTrainedQueryError(cause instanceof Error ? cause.message : 'Could not load saved SQL Training queries.');
    } finally { setTrainedQueriesLoading(false); }
  };

  const runTrainedQuery = (example: { id: string; revision: number; question: string; validation_status: string; replayable?: boolean }) => {
    if (example.validation_status !== 'executed' || example.replayable !== true) return;
    setTrainedQueryPickerOpen(false);
    setTrainedQuerySearch('');
    void sendQuestion(example.question, { asNew: true, source: 'saved-restore', analysisMode: 'basic', trainingExample: example });
  };

  const stopAnalysis = () => {
    const id = investigationIdRef.current;
    if (id) void dashboardApi.cancelInvestigation(id);
    abortRef.current?.abort();
    setLoading(false);
    setMessages(previous => [...previous, {
      id: `cancelled-${id}`, role: 'assistant', content: 'This analysis was stopped.', ts: Date.now(),
      result: { answer_status: 'CANCELLED', mode: 'cancelled', summary: 'This analysis was stopped.', data: [] },
    }]);
  };

  const startNewChat = () => {
    followLatestRef.current = true;
    setInput('');
    setStartFreshQuestion(false);
    selectedSuggestionRef.current = null;
    if (inputRef.current) inputRef.current.style.height = 'auto';
    setMessages([]);
    lastSuccessfulAnalyticalRef.current = null;
    setError(null);
    setFailedQuestion(null);
    if (analysisMethod === 'training') {
      setTrainingQuestion('');
      setTrainingDraftRevision(revision => revision + 1);
      setLaunchBanner(null);
      if (initialQuestion) {
        initialSentRef.current = initialQuestion.trim();
        router.replace(analystPathWithoutQuery(), { scroll: false });
      }
    } else {
      setLaunchBanner(investigationLaunch('explicit-new', true).banner);
    }
    // Start a fresh adaptive thread so cleared UI does not reload old turns
    if (typeof window !== 'undefined') {
      const tid = `ada_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
      saveAdaptiveThreadId(tid);
      setThreadId(tid);
      setHistoryLoaded(true);
    }
  };

  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant' && m.result);
  const investigation = lastAssistant?.result
    ? analysisTrustFromResult(lastAssistant.result)
    : null;
  const selectedN = Array.isArray(
    (lastAssistant?.result as any)?.query_plan?.analytical_context?.selected_products
  )
    ? (lastAssistant?.result as any).query_plan.analytical_context.selected_products.length
    : 0;

  return (
    <div
      className="flex flex-1 flex-col min-h-0 bg-white"
      data-adaptive-context-policy={ADAPTIVE_CONTEXT_POLICY}
    >

      {/* ── Header ── */}
      <div className="flex-none bg-white border-b border-slate-100 px-3 sm:px-5 py-3">
        <div className="space-y-2">
          <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div className="p-1.5 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-lg shadow-sm">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="text-sm font-bold text-slate-800">AI Analyst</h2>
              <p className="hidden sm:block text-xs text-slate-500">Conversation, schema, and verified business data</p>
              {investigation?.analysisLabel && (
                <p className="text-[11px] text-slate-600 mt-0.5">
                  Working on: {investigation.analysisLabel}
                  {selectedN > 0 ? ` · ${selectedN} product${selectedN === 1 ? '' : 's'} selected` : ''}
                </p>
              )}
              {launchBanner && (
                <p className="text-[11px] text-emerald-800 mt-0.5" role="status">
                  {launchBanner}
                </p>
              )}
            </div>
          </div>
          <button type="button" onClick={startNewChat} disabled={loading}
            className="inline-flex min-h-8 shrink-0 items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-2.5 text-slate-700 hover:bg-slate-50 disabled:opacity-40"
            title="Start a fresh chat" aria-label="New chat">
            <RotateCcw className="h-3.5 w-3.5" /><span className="text-xs font-medium">New chat</span>
          </button>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-1 sm:gap-2">
            {analysisMethod === 'training' && <div className="flex rounded-full bg-slate-100 p-1" role="group" aria-label="Analysis method">
              {(['agent', 'basic', 'training'] as const).map(method => <button key={method} type="button" aria-pressed={analysisMethod === method}
                onClick={() => { analysisMethodRef.current = method; setAnalysisMethod(method); window.localStorage.setItem('ai-analyst-method', method); }}
                className={cn('rounded-full px-2.5 py-1.5 text-xs font-medium', analysisMethod === method ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white')}>
                {method === 'agent' ? 'Agentic' : method === 'basic' ? 'Basic' : 'SQL Training'}
              </button>)}
            </div>}
            <button type="button" onClick={() => jumpTo('top')} disabled={!scrollPosition.canGoUp}
              aria-label="Jump to top" title="Jump to top"
              className="h-10 w-10 flex items-center justify-center rounded-full text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-default">
              <ChevronUp className="h-5 w-5" />
            </button>
            <button type="button" onClick={() => jumpTo('bottom')} disabled={!scrollPosition.canGoDown}
              aria-label="Jump to bottom" title="Jump to bottom"
              className="h-10 w-10 flex items-center justify-center rounded-full text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-default">
              <ChevronDown className="h-5 w-5" />
            </button>
            <AnalystRagHelp />
            <AnalystQuestionPicker predefined={QUICK_QUESTIONS.map(item => item.q)} disabled={loading}
              onSelect={(question, verified) => {
                if (verified) {
                  analysisMethodRef.current = 'basic';
                  setAnalysisMethod('basic');
                  window.localStorage.setItem('ai-analyst-method', 'basic');
                }
                selectedSuggestionRef.current = question;
                setInput(question);
                inputRef.current?.focus();
              }} />
          </div>
        </div>
      </div>

      {/* ── Messages / Welcome ── */}
      {analysisMethod === 'training' ? (
        <div className="flex-1 min-h-0">
          <BasicSqlTraining
            key={trainingDraftRevision}
            initialQuestion={trainingQuestion ?? initialQuestion}
            questionRef={trainingQuestionRef}
          />
        </div>
      ) : <>
      <div className="relative flex-1 min-h-0">
      <div ref={conversationRef} role="region" aria-label="Conversation" tabIndex={0}
        onScroll={() => {
          const el = conversationRef.current;
          if (el) followLatestRef.current = analystScrollPosition(el.scrollTop, el.scrollHeight, el.clientHeight).nearBottom;
          updateScrollPosition();
        }}
        className="h-full overflow-y-auto overscroll-contain px-3 sm:px-6 lg:px-8 py-6" style={{ scrollbarWidth: 'thin' }}>
      <div ref={conversationContentRef} className="w-full max-w-7xl mx-auto space-y-8 pb-8">

        {messages.length === 0 && !loading && (
          <div className="max-w-3xl mx-auto text-center py-8">
            <div className="inline-flex p-4 bg-gradient-to-br from-indigo-100 to-violet-100 rounded-2xl mb-4 shadow-sm">
              <Sparkles className="h-8 w-8 text-indigo-500" />
            </div>
            <h3 className="text-xl font-semibold text-slate-900 mb-2">
              How can I help?
            </h3>
            <p className="text-sm text-slate-500 mb-6">
              Ask a question, follow up naturally, or explore your SAP data — same continuous chat.
            </p>
            {/* Quick questions */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-left">
              {QUICK_QUESTIONS.map(({ label, q }, qi) => (
                <button key={label}
                  onClick={() => sendQuestion(q, { source: 'typed-continue' })}
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
            "flex gap-2 sm:gap-3",
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
                ? 'max-w-[90%] sm:max-w-[80%] items-end flex flex-col'
                : 'flex-1 min-w-0'
            )} style={msg.role === 'user' ? { maxWidth: 'min(85%, 768px)' } : undefined}>
              {msg.role === 'user' ? (
                <div className="bg-slate-100 text-slate-900 rounded-3xl px-5 py-3 text-sm whitespace-pre-wrap break-words">
                  {msg.content}
                </div>
              ) : (
                <>
                  {msg.result?.answer_status === 'CANNOT_ANSWER' ? (
                    <ResultDashboard
                      result={msg.result}
                      onAskFollowup={(fq) => {
                        void sendQuestion(fq, { source: 'followup-chip' });
                      }}
                      onUseBasicPattern={(fq) => void sendQuestion(fq, { source: 'followup-chip', analysisMode: 'basic', approveBasicPattern: true })}
                      onUseAgentic={(fq) => void sendQuestion(fq, { source: 'followup-chip', analysisMode: 'agent' })}
                      onOpenSqlTraining={(fq) => {
                        setTrainingQuestion(fq);
                        analysisMethodRef.current = 'training';
                        setAnalysisMethod('training');
                        window.localStorage.setItem('ai-analyst-method', 'training');
                      }}
                    />
                  ) : (
                    <>
                      {/* Prefer ResultDashboard when present — avoid duplicating summary text */}
                      {msg.result ? (
                        <ResultDashboard
                          result={msg.result}
                          onAskFollowup={(fq) => {
                            void sendQuestion(fq, { source: 'followup-chip' });
                          }}
                          onUseBasicPattern={(fq) => void sendQuestion(fq, { source: 'followup-chip', analysisMode: 'basic', approveBasicPattern: true })}
                          onUseAgentic={(fq) => void sendQuestion(fq, { source: 'followup-chip', analysisMode: 'agent' })}
                          onOpenSqlTraining={(fq) => {
                            setTrainingQuestion(fq);
                            analysisMethodRef.current = 'training';
                            setAnalysisMethod('training');
                            window.localStorage.setItem('ai-analyst-method', 'training');
                          }}
                        />
                      ) : (
                        msg.content && (
                          <div className="text-slate-700">
                            <AnswerMarkdown text={humanizePublicSummary(msg.content, undefined)} />
                          </div>
                        )
                      )}
                    </>
                  )}
                  <CopyAnswer text={msg.result ? analystAnswerText(msg.result) || msg.content : msg.content} />
                </>
              )}
            </div>
          </div>
        ))}

        {/* Loading state — pipeline progress */}
        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="flex-none w-8 h-8 rounded-full bg-emerald-800 flex items-center justify-center">
              <Loader2 className="h-4 w-4 text-white animate-spin" />
            </div>
            <div className="bg-white rounded-2xl rounded-tl-sm border border-slate-100 shadow-sm px-5 py-4 max-w-sm w-full" aria-live="polite" aria-busy="true">
              <div className="text-xs font-semibold text-slate-500 mb-3 flex items-center gap-1.5">
                Working on your question
              </div>
              <AnalysisProgress elapsed={elapsed} progress={progress} />
              <button
                type="button"
                onClick={stopAnalysis}
                className="mt-3 text-xs font-medium text-slate-600 hover:text-slate-900 underline"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Error */}
        {error && (
          <div className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-xl p-4 text-sm text-red-800" role="alert">
            <AlertCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold mb-0.5">We could not complete this analysis</div>
              <div className="text-red-700">{error}</div>
              <p className="mt-1 text-xs text-red-600">Your chat history is still here.</p>
              {failedQuestion && (
                <button
                  type="button"
                  onClick={() => void sendQuestion(failedQuestion, { retry: true, source: 'typed-continue' })}
                  className="mt-2 rounded-lg bg-red-700 px-3 py-1.5 text-xs font-semibold text-white hover:bg-red-800"
                >
                  Retry last question
                </button>
              )}
            </div>
            <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600" aria-label="Dismiss error">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

      </div>
      </div>
      {scrollPosition.canGoDown && (
        <div className="absolute bottom-3 inset-x-0 flex justify-center pointer-events-none">
          <button type="button" onClick={() => jumpTo('bottom')} aria-label="Go to latest message"
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-4 py-2 text-xs font-medium text-slate-700 shadow-md hover:bg-slate-50">
            <ChevronDown className="h-4 w-4" /> Latest message
          </button>
        </div>
      )}
      </div>
      </>}

      {/* ── Input bar ── */}
      {analysisMethod !== 'training' && (
      <div className="flex-none bg-white px-3 sm:px-6 pt-2 pb-[max(12px,env(safe-area-inset-bottom))]">
      <div className="w-full max-w-4xl mx-auto">
        <div className="mb-2 flex flex-wrap items-center gap-2 px-1" role="group" aria-label="Analysis method">
          {(['agent', 'basic', 'training'] as const).map(method => (
            <button
              key={method}
              type="button"
              aria-pressed={analysisMethod === method}
              onClick={() => {
                analysisMethodRef.current = method;
                setAnalysisMethod(method);
                window.localStorage.setItem('ai-analyst-method', method);
              }}
              className={cn(
                'rounded-full px-3 py-1 text-xs font-medium',
                analysisMethod === method ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200',
              )}
            >
              {method === 'agent' ? 'Agentic' : method === 'basic' ? 'Basic' : 'Basic SQL Training'}
            </button>
          ))}
          <span className="text-xs text-slate-500">
            {analysisMethod === 'agent'
              ? 'Investigates with tools, then answers from verified SQL.'
              : analysisMethod === 'basic'
                ? 'Saved questions use no model tokens. New questions use the configured Basic model; without one, Agentic may use credits when fallback is enabled.'
                : 'Manual schema and read-only SQL workflow; no model calls.'}
          </span>
        </div>
        <label className="mb-2 flex w-fit cursor-pointer items-center gap-2 px-1 text-xs text-slate-600">
          <input type="checkbox" checked={startFreshQuestion} onChange={event => setStartFreshQuestion(event.target.checked)} disabled={loading} className="rounded border-slate-300" />
          New question · ignore earlier chat context
        </label>
        {analysisMethod === 'basic' && <div className="mb-2">
          <button type="button" onClick={() => void toggleTrainedQueryPicker()} disabled={loading || trainedQueriesLoading} aria-expanded={trainedQueryPickerOpen}
            className="rounded-lg border border-indigo-200 bg-indigo-50 px-3 py-1.5 text-xs font-medium text-indigo-800 hover:bg-indigo-100 disabled:opacity-50">
            {trainedQueriesLoading ? 'Loading saved SQL Training queries…' : 'Choose a saved SQL Training query'}
          </button>
          {trainedQueryPickerOpen && <div className="mt-2 rounded-xl border border-indigo-200 bg-white p-3 shadow-sm">
            <p className="text-xs text-slate-600">Saved queries are checked against their question before Basic can replay them. Examples that do not match need review in SQL Training.</p>
            {trainedQueries.length > 0 && <input aria-label="Search saved SQL Training queries" value={trainedQuerySearch} onChange={event => setTrainedQuerySearch(event.target.value)} placeholder="Search saved questions" className="mt-2 w-full rounded-lg border px-3 py-2 text-xs"/>}
            {trainedQueryError && <p role="alert" className="mt-2 text-xs text-red-700">{trainedQueryError}</p>}
            {!trainedQueriesLoading && !trainedQueryError && trainedQueries.length === 0 && <p className="mt-2 text-xs text-slate-500">No saved SQL Training queries yet. In SQL Training, select every table and column your join uses, run the SQL successfully, then choose “Save checked example.”</p>}
            <div className="mt-2 max-h-56 space-y-1 overflow-y-auto">{trainedQueries.filter(example => !trainedQuerySearch.trim() || example.question.toLowerCase().includes(trainedQuerySearch.trim().toLowerCase())).map(example => {
              const replayable = example.validation_status === 'executed' && example.replayable === true;
              return <div key={example.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-2">
                <div className="min-w-0 flex-1"><p className="text-xs font-medium text-slate-800">{example.question}</p><p className="mt-0.5 text-[10px] text-slate-500">Revision {example.revision} · {Object.keys(example.schema?.tables || {}).join(', ') || example.source}</p>
                  {!replayable && <><p className="mt-1 text-[11px] font-medium text-amber-800">Needs review · Basic will not run this saved SQL.</p>{example.answerability_issues?.length ? <ul className="mt-1 list-disc pl-4 text-[10px] text-amber-800">{example.answerability_issues.map(issue => <li key={issue}>{issue}</li>)}</ul> : <p className="mt-1 text-[10px] text-slate-500">The connected API has not verified this example against its question.</p>}</>}
                </div>
                {replayable ? <button type="button" onClick={() => runTrainedQuery(example)} className="shrink-0 rounded-md bg-indigo-700 px-2.5 py-1.5 text-[11px] font-semibold text-white hover:bg-indigo-800">Run in Basic</button> : <span className="shrink-0 rounded-md border border-amber-300 px-2.5 py-1.5 text-[11px] font-semibold text-amber-900">Review in SQL Training</span>}
              </div>;
            })}</div>
            {trainedQueriesLoaded && trainedQueries.length > 0 && !trainedQueries.some(example => !trainedQuerySearch.trim() || example.question.toLowerCase().includes(trainedQuerySearch.trim().toLowerCase())) && <p className="mt-2 text-xs text-slate-500">No saved questions match that search.</p>}
          </div>}
        </div>}
        <div className="flex items-end gap-2 rounded-3xl border border-slate-200 bg-slate-50 p-2 focus-within:border-slate-400 focus-within:ring-1 focus-within:ring-slate-200">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              aria-label="Message AI Analyst"
              placeholder="Message AI Analyst"
              className={cn(
                "block w-full resize-none border-0 bg-transparent",
                "px-3 py-2.5 text-sm text-slate-800 placeholder:text-slate-400",
                "focus:outline-none focus:ring-0",
                "max-h-32 overflow-y-auto",
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
          {loading ? (
            <button
              type="button"
              onClick={stopAnalysis}
              className="flex-none h-10 px-3 rounded-full bg-slate-800 text-white text-xs font-medium hover:bg-slate-900"
              aria-label="Cancel analysis"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={() => sendQuestion(input, startFreshQuestion ? { newQuestion: true, source: 'explicit-new' } : undefined)}
              disabled={!input.trim() || !historyLoaded}
              aria-label="Send question"
              className={cn(
                "flex-none w-10 h-10 rounded-full flex items-center justify-center transition-all",
                input.trim()
                  ? "bg-slate-900 hover:bg-slate-700"
                  : "bg-slate-200 cursor-not-allowed"
              )}>
              <Send className="h-4 w-4 text-white" />
            </button>
          )}
        </div>
        <div className="mt-2 text-center text-[11px] text-slate-400">
          <span>{loading ? 'You can draft your next question while I work.' : 'Enter to send · Shift + Enter for a new line · Follow-ups keep context'}</span>
        </div>
        </div>
      </div>
      )}

    </div>
  );
}
