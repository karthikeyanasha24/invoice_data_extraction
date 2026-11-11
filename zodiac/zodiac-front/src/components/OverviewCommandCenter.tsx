'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { dashboardApi } from '@/lib/api';
import { publicApiError } from '@/lib/apiErrors';
import { SUPPORTED_INVESTIGATIONS } from '@/lib/navConfig';
import {
  ArrowRight,
  AlertTriangle,
  Package,
  TrendingUp,
  TrendingDown,
  Sparkles,
  FileText,
  RefreshCw,
} from 'lucide-react';
import { cn } from '@/lib/utils';

function money(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  return n.toLocaleString(undefined, { maximumFractionDigits: 0 });
}

type InboundSummary = { total_documents?: number; merges_pending?: number; merges_sent_to_sap?: number; merges_total?: number };
type InboundOverview = { summary?: InboundSummary };
type RevenueTrend = { currency?: string | null; revenue_change_pct?: number | null; current_period_revenue?: number | null; requires_currency_selection?: boolean };
type BusinessOverview = { trend?: RevenueTrend; trend_by_currency?: RevenueTrend[] };

export default function OverviewCommandCenter() {
  const router = useRouter();
  const [inbound, setInbound] = useState<InboundOverview | null>(null);
  const [business, setBusiness] = useState<BusinessOverview | null>(null);
  const [error, setError] = useState('');
  const [partialErrors, setPartialErrors] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      setError('');
      setPartialErrors([]);
      const results = await Promise.allSettled([
        dashboardApi.getV2Inbound(0),
        dashboardApi.getV2Business(90, undefined, { includeInsights: false }),
      ]);
      const [inb, biz] = results;
      if (inb.status === 'fulfilled') setInbound(inb.value);
      else {
        setInbound(null);
        setPartialErrors(errors => [...errors, `Inbound operations: ${publicApiError(inb.reason, 'Could not load inbound activity.')}`]);
      }
      if (biz.status === 'fulfilled') setBusiness(biz.value);
      else {
        setBusiness(null);
        setPartialErrors(errors => [...errors, `Invoice activity: ${publicApiError(biz.reason, 'Could not load invoice activity.')}`]);
      }
      if (inb.status === 'rejected' && biz.status === 'rejected') {
        setError('Overview data is temporarily unavailable. The inbound-operations and invoice-activity services both failed.');
      }
    } catch (err: unknown) {
      setError(publicApiError(err, 'We could not load the overview. Try again.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const summary = inbound?.summary || {};
  const trend = business?.trend;
  const trendPct = typeof trend?.revenue_change_pct === 'number' ? trend.revenue_change_pct : null;
  const changeLabel = trendPct;
  const pending = inbound ? summary.merges_pending ?? null : null;
  const docs = inbound ? summary.total_documents ?? null : null;
  const sent = inbound ? summary.merges_sent_to_sap ?? null : null;
  const nextActions: { label: string; why: string; href?: string; question?: string }[] = [];
  if (pending != null && pending > 0) {
    nextActions.push({
      label: `Send ${pending} merge${pending === 1 ? '' : 's'} to SAP`,
      why: 'Validated inbound documents are waiting to post.',
      href: '/sat-documents',
    });
  }
  if (docs === 0) {
    nextActions.push({
      label: 'Upload the first SAT document',
      why: 'There is no inbound CFDI activity for this account yet.',
      href: '/sat-documents',
    });
  } else if (docs != null && pending === 0) {
    nextActions.push({
      label: 'Investigate highest-profit products',
      why: 'No merges are waiting to send. You can start a new investigation in AI Analyst.',
      question: 'Show the products with the highest profits.',
    });
  }

  const ask = (q: string) => {
    router.push(`/dashboard/ai?q=${encodeURIComponent(q)}`);
  };

  if (loading && !inbound && !business) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 text-slate-600">
        <RefreshCw className="h-6 w-6 animate-spin text-emerald-700" aria-hidden />
        <p className="text-sm font-medium">Loading your business snapshot…</p>
        <p className="text-xs text-slate-500">Inbound operations and revenue trend from the last 90 days.</p>
      </div>
    );
  }

  if (error && !inbound && !business) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-6">
        <p className="text-sm font-medium text-red-800">{error}</p>
        <button
          type="button"
          onClick={() => void load()}
          className="mt-3 rounded-lg bg-red-700 px-3 py-2 text-sm font-medium text-white hover:bg-red-800"
        >
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {partialErrors.length > 0 && <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        <p className="font-medium">Some overview data did not load. Available information is still shown below.</p>
        {partialErrors.map(message => <p key={message} className="mt-1 text-xs">{message}</p>)}
        <button type="button" onClick={() => void load()} className="mt-2 rounded-lg border border-amber-300 bg-white px-3 py-1.5 text-xs font-medium hover:bg-amber-100">Retry failed data</button>
      </div>}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Overview</h1>
        <p className="mt-1 text-sm text-slate-600">
          What is happening in operations, what needs attention, and what you can investigate in governed SAP data.
        </p>
      </div>

      {nextActions.length > 0 && (
        <section aria-labelledby="next-heading">
          <h2 id="next-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            What to do next
          </h2>
          <div className="mt-3 space-y-2">
            {nextActions.map((action) => (
              <button
                key={action.label}
                type="button"
                onClick={() => (action.question ? ask(action.question) : router.push(action.href || '/overview'))}
                className="flex w-full items-start justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50/60 px-4 py-3 text-left hover:bg-emerald-50"
              >
                <span>
                  <span className="block text-sm font-medium text-slate-900">{action.label}</span>
                  <span className="mt-0.5 block text-xs text-slate-600">{action.why}</span>
                </span>
                <ArrowRight className="mt-0.5 h-4 w-4 flex-shrink-0 text-emerald-800" />
              </button>
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="attention-heading">
        <h2 id="attention-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Needs attention
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className={cn('rounded-xl border p-4', pending != null && pending > 0 ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white')}>
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <AlertTriangle className={cn('h-4 w-4', pending != null && pending > 0 ? 'text-amber-700' : 'text-slate-400')} />
              Merges waiting to send
            </div>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{pending ?? '—'}</p>
            <p className="mt-1 text-xs text-slate-600">
              {pending == null ? 'Inbound activity is unavailable. Retry loading the overview.' : pending > 0
                ? 'Validated inbound merges have not been sent to SAP yet.'
                : docs === 0
                  ? 'No inbound documents yet. Upload a CFDI to start the SAT workflow.'
                  : 'No merges are waiting to send.'}
            </p>
            <button
              type="button"
              onClick={() => router.push('/sat-documents')}
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 hover:underline"
            >
              Open SAT documents <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <FileText className="h-4 w-4 text-slate-500" />
              Inbound SAT documents
            </div>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{docs ?? '—'}</p>
            <p className="mt-1 text-xs text-slate-600">
              All-time documents for this account. This is inbound SAT activity, not an ERP push.
            </p>
            <button
              type="button"
              onClick={() => router.push('/dashboard')}
              className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-emerald-800 hover:underline"
            >
              Open EDI operations <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </section>

      <section aria-labelledby="kpis-heading">
        <h2 id="kpis-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          EDI invoice activity
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Invoice-document totals from EDI (last 90 days). This is not SAP P&amp;L. Governed profitability is in AI Analyst.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">EDI invoice total</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
              {trend?.requires_currency_selection ? 'By currency below' : `${money(trend?.current_period_revenue)}${trend?.currency ? ` ${trend.currency}` : ''}`}
            </p>
            <p className="mt-1 text-xs text-slate-500">Last 90 days · invoice totals</p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Change vs prior period</p>
            <p className={cn('mt-2 flex items-center gap-1 text-2xl font-semibold tabular-nums', (changeLabel ?? 0) >= 0 ? 'text-emerald-700' : 'text-red-700')}>
              {changeLabel == null ? (
                <span className="text-slate-400">—</span>
              ) : (
                <>
                  {changeLabel >= 0 ? <TrendingUp className="h-5 w-5" /> : <TrendingDown className="h-5 w-5" />}
                  {`${changeLabel > 0 ? '+' : ''}${changeLabel.toFixed(1)}%`}
                </>
              )}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {changeLabel == null
                ? !business ? 'Invoice activity is unavailable'
                  : trend?.requires_currency_selection ? 'Currencies are compared separately below'
                  : 'No prior-period amount is available for comparison'
                : 'Compared with the previous 90 days'}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Sent to SAP</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{sent ?? '—'}</p>
            <p className="mt-1 text-xs text-slate-500">of {summary.merges_total ?? '—'} merges</p>
          </div>
        </div>
        {trend?.requires_currency_selection && (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2" aria-label="Invoice totals by currency">
            {(business?.trend_by_currency || []).map(row => <li key={row.currency} className="rounded-xl border border-slate-200 bg-white p-4 text-sm">
              <span className="font-medium">{row.currency === 'Unknown' ? 'Currency unavailable' : row.currency}</span>
              <span className="ml-2">{money(row.current_period_revenue)}</span>
              <p className="mt-1 text-xs text-slate-500">{row.revenue_change_pct == null ? 'No comparable prior-period amount' : `${row.revenue_change_pct > 0 ? '+' : ''}${row.revenue_change_pct.toFixed(1)}% vs prior 90 days`}</p>
            </li>)}
          </ul>
        )}
      </section>

      <section aria-labelledby="explore-heading">
        <h2 id="explore-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Investigate in AI Analyst
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Each chip opens a new investigation in AI Analyst. Previous filters from an unrelated question are not applied.
          Use Open AI Analyst to continue the current investigation.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {SUPPORTED_INVESTIGATIONS.map((item) => (
            <button
              key={item.question}
              type="button"
              onClick={() => ask(item.question)}
              className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 text-left hover:border-emerald-300 hover:bg-emerald-50/40"
            >
              <span className="text-sm font-medium text-slate-800">{item.label}</span>
              <Sparkles className="h-4 w-4 text-emerald-700" />
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => router.push('/dashboard/ai')}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-800 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-900"
        >
          <Package className="h-4 w-4" />
          Open AI Analyst
        </button>
      </section>
    </div>
  );
}
