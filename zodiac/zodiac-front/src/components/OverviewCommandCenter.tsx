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

export default function OverviewCommandCenter() {
  const router = useRouter();
  const [inbound, setInbound] = useState<any>(null);
  const [business, setBusiness] = useState<any>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    try {
      setLoading(true);
      setError('');
      const [inb, biz] = await Promise.all([
        dashboardApi.getV2Inbound(0),
        dashboardApi.getV2Business(90),
      ]);
      setInbound(inb);
      setBusiness(biz);
    } catch (err: any) {
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
  const currentRev = Number(trend?.current_period_revenue || 0);
  const changeLabel =
    trendPct == null || (currentRev === 0 && Math.abs(trendPct) >= 100)
      ? null
      : trendPct;
  const pending = Number(summary.merges_pending || 0);
  const docs = Number(summary.total_documents || 0);

  const ask = (q: string) => {
    router.push(`/dashboard/ai?q=${encodeURIComponent(q)}`);
  };

  if (loading) {
    return (
      <div className="flex min-h-[40vh] flex-col items-center justify-center gap-2 text-slate-600">
        <RefreshCw className="h-6 w-6 animate-spin text-emerald-700" aria-hidden />
        <p className="text-sm font-medium">Loading your business snapshot…</p>
        <p className="text-xs text-slate-500">Inbound operations and revenue trend from the last 90 days.</p>
      </div>
    );
  }

  if (error) {
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
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">Overview</h1>
        <p className="mt-1 text-sm text-slate-600">
          What is happening in operations, and what to investigate in governed SAP data.
        </p>
      </div>

      <section aria-labelledby="attention-heading">
        <h2 id="attention-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Needs attention
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <div className={cn('rounded-xl border p-4', pending > 0 ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-white')}>
            <div className="flex items-center gap-2 text-sm font-medium text-slate-800">
              <AlertTriangle className={cn('h-4 w-4', pending > 0 ? 'text-amber-700' : 'text-slate-400')} />
              Merges waiting to send
            </div>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{pending}</p>
            <p className="mt-1 text-xs text-slate-600">
              {pending > 0
                ? 'Validated inbound merges have not been sent to SAP yet.'
                : 'No pending merges. Inbound pipeline is clear.'}
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
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{docs}</p>
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
          Business snapshot
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          Invoice-document revenue from the EDI business dashboard (last 90 days). Governed SAP profitability lives in AI Analyst.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Period revenue</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
              {money(trend?.current_period_revenue)}
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
                ? 'Not enough invoice volume in this 90-day window to compare'
                : 'Compared with the previous 90 days'}
            </p>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Sent to SAP</p>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">
              {Number(summary.merges_sent_to_sap || 0)}
            </p>
            <p className="mt-1 text-xs text-slate-500">of {Number(summary.merges_total || 0)} merges</p>
          </div>
        </div>
      </section>

      <section aria-labelledby="explore-heading">
        <h2 id="explore-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Investigate in AI Analyst
        </h2>
        <p className="mt-1 text-xs text-slate-500">
          These questions use governed SAP metrics. Inventory aging is not available in this extract.
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
