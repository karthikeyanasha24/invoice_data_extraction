'use client';

/**
 * DashboardAIAnalysis.tsx — Complete Re-Architecture
 * ===================================================
 * Power BI-style AI analytics interface.
 *
 * Pipeline driven (no Schema Browser):
 *   1. User asks a natural language question
 *   2. Backend answers with governed SQL and a structured result
 *   3. Response contains: sql, data, kpis, charts, summary, keyFindings
 *   4. Frontend renders: KPI cards → Charts → Scrollable table → Insights
 */

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { dashboardApi } from '@/lib/api';
import { publicApiError } from '@/lib/apiErrors';
import { humanizeFollowups } from '@/lib/followupChips';
import {
  analysisTrustFromResult,
  dataGapTryInstead,
  humanizePublicSummary,
  humanizeDataGapMessage,
  isDataGapResult,
  isInvestigationFailure,
} from '@/lib/analysisTrust';
import {
  analystPathWithoutQuery,
  investigationLaunch,
} from '@/lib/investigationLaunch';
import {
  ADAPTIVE_CONTEXT_POLICY,
  followupContextForSend,
  lastSuccessfulAnalyticalContext,
  updateLastSuccessfulAnalyticalContext,
  type LastSuccessfulAnalyticalContext,
} from '@/lib/adaptiveChatContext';
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
  { label: 'Highest-profit products', q: 'Show the products with the highest profits.' },
  { label: 'Inventory versus sales', q: 'Show inventory versus sales.' },
  { label: 'Supplier concentration', q: 'Show supplier concentration.' },
  { label: 'What changed this month?', q: 'Show monthly revenue.' },
  { label: 'High stock / low sales', q: 'Which have high inventory but low sales?' },
  { label: 'Products driving growth', q: 'Which products grew the most?' },
];

// ─── Pipeline progress steps ─────────────────────────────────────────────────
const PIPELINE_STAGE_LABELS: Record<string, string> = {
  UNDERSTANDING: 'Understanding your question',
  RETRIEVING_SCHEMA: 'Finding relevant data',
  SELECTING_TABLES: 'Selecting tables',
  SELECTING_COLUMNS: 'Selecting columns',
  BUILDING_PLAN: 'Building the analysis plan',
  VALIDATING_PLAN: 'Validating the plan',
  GENERATING_SQL: 'Generating the query',
  VALIDATING_SQL: 'Validating the query',
  EXECUTING: 'Running the query',
  REPAIRING: 'Repairing the analysis',
  VALIDATING_RESULT: 'Checking the result',
  COMPLETED: 'Preparing your answer',
  TIMEOUT: 'Stopping — time limit reached',
  FAILED: 'Could not complete this analysis',
  CANCELLED: 'Cancelled',
};

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
  suggested_followups?: string[];
  answer_status?: string;
  failure_class?: string;
  query_plan?: any;
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
    domain?: string;
    intent?: string;
    schema_tables?: string[];
    pipeline_ms?: number;
    warnings?: string[];
    deep_analysis?: boolean;
    mode?: string;
    investigation_status?: string;
    failure_class?: string;
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
  return (
    <div className="mb-4">
      <AIChartRenderer charts={specs as any} />
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
  totalCount,
  sql,
  heading,
  columnSemantics,
}: {
  data: any[];
  totalCount?: number;
  sql?: string;
  heading?: string;
  columnSemantics?: QueryResult['column_semantics'];
}) {
  const [showSql, setShowSql] = useState(false);
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(0);
  const [filter, setFilter] = useState('');
  const { copied, copy } = useCopy();
  const pageSize = 25;

  if (!data?.length && !sql) return null;

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
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm mb-4">
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-100 gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Table2 className="h-4 w-4 text-slate-400" />
          <span className="text-sm font-medium text-slate-700">
            {isEmpty
              ? <span className="text-amber-700">No rows for this question</span>
              : `${heading || 'Results'} · ${data.length.toLocaleString()} rows`}
          </span>
        </div>
        <div className="flex items-center gap-1">
          {!isEmpty && (
            <input
              type="search"
              value={filter}
              onChange={(e) => { setFilter(e.target.value); setPage(0); }}
              placeholder="Filter rows"
              aria-label="Filter table rows"
              className="hidden sm:block w-36 text-xs rounded-lg border border-slate-200 px-2 py-1.5 mr-1"
            />
          )}
          {!isEmpty && (
            <button
              type="button"
              onClick={() => exportCsv(sorted, 'bridgeedi-analysis.csv')}
              className="text-xs text-slate-600 hover:text-slate-900 px-2.5 py-1.5 rounded-lg hover:bg-slate-50"
            >
              Export CSV
            </button>
          )}
          {sql && (
            <button onClick={() => setShowSql(v => !v)}
              className="flex items-center gap-1.5 text-xs text-slate-500 hover:text-slate-700 px-2.5 py-1.5 rounded-lg hover:bg-slate-50">
              <Code2 className="h-3.5 w-3.5" />
              {showSql ? 'Hide SQL' : 'View SQL'}
            </button>
          )}
        </div>
      </div>

      {sql && showSql && (
        <div className="relative px-4 py-3 bg-slate-950 text-slate-200 text-xs font-mono overflow-x-auto border-b border-slate-800">
          <button onClick={() => copy(sql)}
            className="absolute top-2 right-2 p-1.5 rounded bg-slate-700 hover:bg-slate-600">
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
          </button>
          <pre className="pr-8 whitespace-pre-wrap break-all leading-relaxed">{sql}</pre>
        </div>
      )}

      {!isEmpty && (
        <>
          <div className="overflow-auto max-h-[420px]" style={{ scrollbarWidth: 'thin' }}>
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 z-10">
                <tr className="bg-slate-50">
                  {headers.map(h => (
                    <th key={h} className="px-3 py-2.5 text-left font-semibold text-slate-600 uppercase tracking-wide whitespace-nowrap border-b border-slate-200" scope="col" aria-sort={sortKey === h ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                      <button type="button" onClick={() => toggleSort(h)} className="hover:text-slate-900">
                        {h.replace(/_/g, ' ')}{sortKey === h ? (sortDir === 'asc' ? ' ↑' : ' ↓') : ''}
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
                      const isDate = sem?.semantic_type === 'date' || /(_date|fkdat|audat|erdat|bedat)$/i.test(h);
                      const isPct = sem?.semantic_type === 'percentage';
                      const isInt = sem?.semantic_type === 'integer';
                      const isNum = !isIdLike(h, v) && !isDate && Number.isFinite(n);
                      const display = (() => {
                        if (v == null) return null;
                        if (isDate) {
                          const s = String(v).trim();
                          if (/^\d{8}$/.test(s)) {
                            const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
                            const mo = Number(s.slice(4, 6));
                            if (mo >= 1 && mo <= 12) return `${s.slice(6, 8)} ${months[mo - 1]} ${s.slice(0, 4)}`;
                          }
                          return String(v);
                        }
                        if (isPct && Number.isFinite(n)) return `${n.toFixed(2)}%`;
                        if (isInt && Number.isFinite(n)) return Math.round(n).toLocaleString('en-US');
                        if (isNum) {
                          const digits = isMoneyName(h) || sem?.semantic_type === 'money' ? 2 : (sem?.precision ?? 2);
                          return n.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: sem?.semantic_type === 'money' ? 2 : 0 });
                        }
                        return String(v);
                      })();
                      return (
                        <td key={h} className={cn(
                          'px-3 py-2 whitespace-nowrap border-b border-slate-100 max-w-[260px] overflow-hidden text-ellipsis',
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
                <button type="button" disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-40">Previous</button>
                <button type="button" disabled={page >= pageCount - 1} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-40">Next</button>
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
      return true;
    });
}

function ConversationCard({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 mb-4">
      <p className="text-sm text-slate-800 whitespace-pre-line leading-relaxed">{message}</p>
    </div>
  );
}

function ClarificationCard({ message, onAskFollowup }: { message: string; onAskFollowup?: (q: string) => void }) {
  const asksLimit = /how many|should i return|answer with a number/i.test(message || '');
  const examples = asksLimit
    ? [
        { label: 'Top 5', question: 'top 5 customers by billed sales' },
        { label: 'Top 10', question: 'top 10 customers by billed sales' },
        { label: 'Top 20', question: 'top 20 customers by billed sales' },
      ]
    : [
        { label: 'Sales orders', question: 'How many sales orders are there?' },
        { label: 'Billed invoices', question: 'Show the top customers by billed sales.' },
        { label: 'Highest sales by country', question: 'Show the highest sales by country.' },
      ];
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 mb-4">
      <p className="text-sm text-slate-800 whitespace-pre-line">{message}</p>
      {onAskFollowup && (
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
    <div className="relative bg-gradient-to-br from-white via-amber-50/30 to-orange-50/40 rounded-xl border border-amber-100 p-4 shadow-sm mb-4 overflow-hidden">
      <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-amber-400 to-orange-400" />
      <div className="flex items-center gap-2 mb-2">
        <div className="p-1 rounded-md bg-amber-100">
          <Sparkles className="h-3.5 w-3.5 text-amber-600" />
        </div>
        <span className="text-sm font-bold text-slate-800">What we found</span>
      </div>
      <div className="prose prose-sm prose-slate max-w-none text-slate-700 text-sm leading-relaxed">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{humanizePublicSummary(summary, intent)}</ReactMarkdown>
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
function AnalysisProgress({ elapsed, stage }: { elapsed: number; stage: string }) {
  const label = PIPELINE_STAGE_LABELS[stage] || PIPELINE_STAGE_LABELS.UNDERSTANDING;
  return (
    <div className="space-y-2 py-1">
      <div className="flex items-center gap-3 text-sm font-medium text-indigo-700">
        <Loader2 className="h-4 w-4 flex-shrink-0 animate-spin" />
        <span>{label}</span>
      </div>
      {elapsed > 5000 && (
        <p className="text-xs text-slate-500 pl-7">Still working — larger questions can take a few seconds.</p>
      )}
      {elapsed > 20000 && (
        <p className="text-xs text-amber-700 pl-7">Taking longer than usual. You can wait or try a simpler question.</p>
      )}
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
  const mapped = humanizeFollowups(followups);
  const seen = new Set(mapped.map((c) => c.question.toLowerCase()));
  const chips = [
    ...mapped,
    ...dataGapTryInstead(message).filter((c) => !seen.has(c.question.toLowerCase())),
  ].slice(0, 6);
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 space-y-3" role="status">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-amber-800">Data limitation</p>
      <p className="text-sm text-slate-800 leading-relaxed">{humanizeDataGapMessage(message)}</p>
      <p className="text-xs text-slate-600">
        This is not an application failure. The question was understood, but the required data is not in this extract.
        No unsupported number was calculated. Previous conversation context is kept.
      </p>
      {onAskFollowup && (
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
// Full result renderer (Power BI-style dashboard)
// ═══════════════════════════════════════════════════════════════════════════════
function ResultDashboard({
  result,
  onAskFollowup,
}: {
  result: QueryResult;
  onAskFollowup?: (q: string) => void;
}) {
  if (!result) return null;
  const { kpis, charts, summary, keyFindings, data, totalCount, sql, sqlStrategy, rowCount, meta, suggested_followups } = result;

  const hasKpis    = (kpis?.length ?? 0) > 0;
  const hasCharts  = (charts?.length ?? 0) > 0;
  const hasData    = (data?.length ?? 0) > 0;
  const hasSummary = !!summary;
  const cleanFindings = humanizeFindings(keyFindings);
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

  if (isGeneral && !isClarification && !isGap && !isTechFailure) {
    // Metadata list-all: show the text once + optional table of names (no Key Findings echo).
    if (mode === 'database_metadata' && hasData && (data?.length ?? 0) > 1) {
      return (
        <div className="space-y-3">
          <ConversationCard message={summary || ''} />
          <DataTable
            data={data || []}
            totalCount={totalCount}
            sql={undefined}
            heading="Tables"
            columnSemantics={result.column_semantics}
          />
        </div>
      );
    }
    return <ConversationCard message={summary || 'Hello! How can I help you today?'} />;
  }

  if (isClarification) {
    return (
      <ClarificationCard
        message={summary || 'I need one more detail to answer this accurately.'}
        onAskFollowup={onAskFollowup}
      />
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
      (result as any).failure_class || result.meta?.investigation_status || ''
    ).toUpperCase();
    const heading =
      failure === 'TOOL_FAILURE' || failure === 'EXECUTION_FAILED'
        ? 'Data service unavailable'
        : failure === 'MODEL_FAILURE' || failure === 'SQL_GENERATION_FAILED'
          ? 'Analysis could not be planned'
          : 'Investigation incomplete';
    const fallback =
      failure === 'TOOL_FAILURE' || failure === 'EXECUTION_FAILED'
        ? "I couldn't complete the database analysis because the data service is temporarily unavailable."
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
      {hasSummary && <SummaryCard summary={summary!} intent={trust.intent} />}
      {hasKpis    && <KPICards kpis={kpis!} />}
      {hasCharts  && <ChartsGrid charts={charts!} />}
      {(hasData || sql) && <DataTable data={data || []} totalCount={totalCount} sql={sql} heading={heading || 'Results'} columnSemantics={result.column_semantics} />}
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
  const [pipelineStage, setPipelineStage] = useState('UNDERSTANDING');
  const [error,      setError]      = useState<string | null>(null);
  const [launchBanner, setLaunchBanner] = useState<string | null>(null);
  const [threadId,   setThreadId]   = useState<string>('');
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const bottomRef   = useRef<HTMLDivElement>(null);
  const timerRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const inputRef    = useRef<HTMLTextAreaElement>(null);
  const initialSentRef = useRef<string | null>(null);
  const lastSuccessfulAnalyticalRef = useRef<LastSuccessfulAnalyticalContext | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const investigationIdRef = useRef<string>('');

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
            const rawResult = m.role === 'assistant' && m.result ? {
              sql: m.result.sql,
              data: m.result.data || [],
              rowCount: m.result.rowCount ?? (m.result.data?.length ?? 0),
              charts: m.result.charts || [],
              summary: m.result.summary || m.content,
              query_plan: (m.result as any).query_plan || (m.result as any).queryPlan || null,
              answer_status: (m.result as any).answer_status
                || ((m.result as any).mode === 'general_chat' ? 'SUCCESS'
                  : ((m.result.sql || '').trim() ? 'SUCCESS' : 'SUCCESS')),
              mode: (m.result as any).mode,
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

  const sendQuestion = useCallback(async (question: string, opts?: { asNew?: boolean; source?: 'overview-url' | 'overview-chip' | 'followup-chip' | 'explicit-new' | 'saved-restore' | 'typed-continue' }) => {
    const q = (question || '').trim().replace(/^undefined/i, '').trim();
    if (!q || loading) return;

    const tid = threadId || ensureAdaptiveThreadId();
    if (!threadId) setThreadId(tid);

    setError(null);
    setInput('');
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content: q, ts: Date.now() };
    setMessages(prev => [...prev, userMsg]);
    setLoading(true);
    setPipelineStage('UNDERSTANDING');

    // Continuous chat (ChatGPT-style): typed messages always carry the latest
    // turn context. Only Overview / saved deep-links start an isolated ask.
    const treatAsNew = Boolean(opts?.asNew) && (
      opts?.source === 'overview-url'
      || opts?.source === 'overview-chip'
      || opts?.source === 'saved-restore'
    );
    const contextData = followupContextForSend(
      messages,
      lastSuccessfulAnalyticalRef.current,
      treatAsNew,
    );
    const dirty = lastSuccessfulAnalyticalRef.current != null || messages.length > 0;
    const source = opts?.source
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
    const poll = window.setInterval(() => {
      dashboardApi.getInvestigationStatus(investigationId).then((st) => {
        if (st?.pipeline_stage) setPipelineStage(st.pipeline_stage);
      }).catch(() => undefined);
    }, 800);

    try {
      const res = await dashboardApi.postAdaptiveQuery({
        question: q,
        // Explicit null (not omitted) so a dirty thread cannot leak prior SQL/filters.
        contextData: treatAsNew ? null : contextData,
        threadId: tid,
        investigationId,
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

      // Normalise response — backend may return old shape or new pipeline shape
      const result: QueryResult = {
        sql:         isTimeout ? undefined : (res.sql || res.generatedSql),
        data:        isCannotAnswer || isTimeout ? [] : (res.data || res.rows || []),
        rowCount:    isCannotAnswer || isTimeout ? 0 : (res.rowCount ?? res.row_count ?? (res.data?.length ?? 0)),
        totalCount:  res.totalCount ?? res.total_count ?? -1,
        sqlStrategy: res.sqlStrategy || res.sql_strategy || 'full',
        summary:     humanizePublicSummary(
          res.summary || res.executive_summary || res.answer || '',
          String((res.query_plan || res.queryPlan || {}).analytical_context?.intent || res.intent || ''),
        ),
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
        calculation: res.calculation,
        meta:        res.meta || {
          domain:        res.domain,
          intent:        res.intent,
          schema_tables: res.schema_tables || res.meta?.schema_tables,
          pipeline_ms:   res.pipeline_ms,
          warnings:      res.warnings || [],
        },
        ...( {
          query_plan: res.query_plan || res.queryPlan,
          answer_status: isTimeout
            ? 'TIMEOUT'
            : isClarification
            ? 'CLARIFICATION'
            : (answerStatus || (isCannotAnswer ? 'CANNOT_ANSWER' : 'SUCCESS')),
        } as any),
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
        result: res.type === 'analysis' && !isCannotAnswer ? undefined : result,
        ts: Date.now(),
      };
      if (!isClarification && !isCannotAnswer && !isTimeout) {
        lastSuccessfulAnalyticalRef.current = updateLastSuccessfulAnalyticalContext(
          lastSuccessfulAnalyticalRef.current,
          q,
          result,
        );
      }
      setMessages(prev => [...prev, assistantMsg]);
    } catch (err: any) {
      if (err?.code === 'ERR_CANCELED' || err?.name === 'CanceledError' || err?.name === 'AbortError') {
        return;
      }
      setError(publicApiError(err, 'Could not complete this analysis. Please try rephrasing.'));
      // Keep the user message visible so history does not silently lose questions
    } finally {
      window.clearInterval(poll);
      setLoading(false);
    }
    // Continuous chat: keep latest turn in the dependency list so follow-ups
    // always see the newest assistant context.
  }, [messages, loading, threadId]);

  // Auto-run a question handed over from another view (e.g. "What can you ask?"
  // sidebar on the Real-time tab). Guarded so the same question only fires once.
  // Wait for history load so we don't race with restored messages.
  useEffect(() => {
    const q = (initialQuestion || '').trim();
    if (q && historyLoaded && initialSentRef.current !== q && !loading) {
      initialSentRef.current = q;
      const dirty = lastSuccessfulAnalyticalRef.current != null || messages.length > 0;
      setLaunchBanner(investigationLaunch('overview-url', dirty).banner);
      void sendQuestion(q, { asNew: true, source: 'overview-url' });
      router.replace(analystPathWithoutQuery(), { scroll: false });
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
    lastSuccessfulAnalyticalRef.current = null;
    setError(null);
    setLaunchBanner(investigationLaunch('explicit-new', true).banner);
    // Start a fresh adaptive thread so cleared UI does not reload old turns
    if (typeof window !== 'undefined') {
      const tid = `ada_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem(ADA_THREAD_KEY, tid);
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
      className="flex flex-col h-full bg-slate-50"
      data-adaptive-context-policy={ADAPTIVE_CONTEXT_POLICY}
    >

      {/* ── Header ── */}
      <div className="flex-none bg-gradient-to-r from-indigo-50/80 via-white to-violet-50/60 border-b border-slate-200 px-5 py-3.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="p-1.5 bg-gradient-to-br from-indigo-500 to-violet-600 rounded-lg shadow-sm">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-800">AI Analyst</h2>
              <p className="text-xs text-slate-500">Ask anything — conversation, schema, or business data</p>
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
          <div className="flex items-center gap-2">
            {messages.length > 0 && (
              <button onClick={clearAll}
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-colors"
                title="Clear chat"
                aria-label="Clear chat">
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
            <h3 className="text-xl font-semibold text-slate-900 mb-2">
              How can I help?
            </h3>
            <p className="text-sm text-slate-500 mb-6">
              Ask a question, follow up naturally, or explore your SAP data — same continuous chat.
            </p>
            {/* Quick questions */}
            <div className="grid grid-cols-2 gap-2 text-left">
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
                  {msg.result?.answer_status === 'CANNOT_ANSWER' ? (
                    <ResultDashboard
                      result={msg.result}
                      onAskFollowup={(fq) => {
                        void sendQuestion(fq, { source: 'followup-chip' });
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
                        />
                      ) : (
                        msg.content && (
                          <div className="text-sm text-slate-700 leading-relaxed">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {humanizePublicSummary(msg.content, undefined)}
                            </ReactMarkdown>
                          </div>
                        )
                      )}
                    </>
                  )}
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
              <AnalysisProgress elapsed={elapsed} stage={pipelineStage} />
              <button
                type="button"
                onClick={() => {
                  const id = investigationIdRef.current;
                  if (id) dashboardApi.cancelInvestigation(id);
                  abortRef.current?.abort();
                  setLoading(false);
                }}
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
              <p className="mt-1 text-xs text-red-600">Try again or rephrase — your chat history is still here.</p>
            </div>
            <button onClick={() => setError(null)} className="ml-auto text-red-400 hover:text-red-600" aria-label="Dismiss error">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* ── Input bar ── */}
      <div className="flex-none bg-white border-t border-slate-200 px-4 py-3">
        <div className="flex items-end gap-2.5">
          <div className="flex-1 relative">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              disabled={loading}
              placeholder='Ask anything — e.g. "Hi", "How many tables?", "Top customers by sales"'
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
          {loading ? (
            <button
              type="button"
              onClick={() => {
                const id = investigationIdRef.current;
                if (id) dashboardApi.cancelInvestigation(id);
                abortRef.current?.abort();
                setLoading(false);
              }}
              className="flex-none h-10 px-3 rounded-xl bg-slate-700 text-white text-xs font-medium hover:bg-slate-800"
              aria-label="Cancel analysis"
            >
              Cancel
            </button>
          ) : (
            <button
              onClick={() => sendQuestion(input)}
              disabled={!input.trim()}
              aria-label="Send question"
              className={cn(
                "flex-none w-10 h-10 rounded-xl flex items-center justify-center transition-all",
                input.trim()
                  ? "bg-emerald-800 hover:bg-emerald-900 shadow-md"
                  : "bg-slate-200 cursor-not-allowed"
              )}>
              <Send className="h-4 w-4 text-white" />
            </button>
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-400 px-1">
          <Zap className="h-3 w-3 text-amber-400" />
          <span>Same continuous chat — follow-ups keep context. Use Clear chat (top right) to reset.</span>
        </div>
      </div>

    </div>
  );
}
