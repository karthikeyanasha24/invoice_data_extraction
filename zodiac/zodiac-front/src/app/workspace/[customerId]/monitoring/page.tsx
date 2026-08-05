'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import { useAuth } from '@/contexts/AuthContext';
import { monitoringApi, workspaceApi } from '@/lib/api';
import WorkspaceShell from '@/components/workspace/WorkspaceShell';

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
    </div>
  );
}

export default function WorkspaceMonitoringPage() {
  const params = useParams();
  const customerId = decodeURIComponent(String(params.customerId || ''));
  const { user, loading } = useAuth();
  const router = useRouter();
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [summary, setSummary] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !customerId) return;
    let cancelled = false;
    (async () => {
      try {
        const [ws, mon] = await Promise.all([
          workspaceApi.getWorkspace(customerId).catch(() => null),
          monitoringApi.getSummary(customerId),
        ]);
        if (!cancelled) {
          setDisplayName(ws?.display_name || null);
          setSummary(mon);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || 'Failed to load monitoring');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, customerId]);

  if (loading || !user) {
    return (
      <MainLayout>
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      </MainLayout>
    );
  }

  const counts = summary?.counts || {};
  const avg =
    summary?.average_processing_time_ms != null
      ? `${Math.round(summary.average_processing_time_ms)} ms`
      : '—';
  const success =
    summary?.success_rate_percent != null
      ? `${summary.success_rate_percent.toFixed(1)}%`
      : '—';

  return (
    <MainLayout>
      <div className="p-4 md:p-6">
        <WorkspaceShell
          customerId={customerId}
          displayName={displayName}
          activeTab="monitoring"
        >
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!summary ? (
            <div className="flex justify-center py-12">
              <Loader className="h-8 w-8 animate-spin text-blue-500" />
            </div>
          ) : (
            <div className="space-y-6">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
                <Stat label="Running" value={counts.running ?? 0} />
                <Stat label="Completed" value={counts.completed ?? 0} />
                <Stat label="Failed" value={counts.failed ?? 0} />
                <Stat label="Pending" value={counts.pending ?? 0} />
                <Stat label="Retrying" value={counts.retrying ?? 0} />
                <Stat label="Success rate" value={success} />
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <h2 className="text-sm font-semibold text-slate-800">Average processing time</h2>
                  <p className="mt-2 text-3xl font-semibold text-slate-900">{avg}</p>
                </div>
                <div className="rounded-xl border border-slate-200 bg-white p-4">
                  <h2 className="text-sm font-semibold text-slate-800">Top errors</h2>
                  <ul className="mt-3 space-y-2 text-sm text-slate-600">
                    {(summary.top_errors || []).length === 0 && (
                      <li className="text-slate-400">No failures in the recent window.</li>
                    )}
                    {(summary.top_errors || []).map((e: any) => (
                      <li key={e.key} className="flex justify-between gap-4">
                        <span className="font-mono text-slate-800">{e.key}</span>
                        <span>{e.count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Latest transactions</h2>
                <div className="mt-3 overflow-x-auto">
                  <table className="min-w-full text-left text-sm">
                    <thead className="text-xs uppercase text-slate-500">
                      <tr>
                        <th className="py-2 pr-4">Correlation</th>
                        <th className="py-2 pr-4">Status</th>
                        <th className="py-2 pr-4">Stage</th>
                        <th className="py-2 pr-4">Latency</th>
                        <th className="py-2">Country</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(summary.latest_transactions || []).map((t: any) => (
                        <tr key={t.correlation_id} className="border-t border-slate-100">
                          <td className="py-2 pr-4 font-mono text-xs text-slate-800">
                            {t.correlation_id}
                          </td>
                          <td className="py-2 pr-4">{t.status}</td>
                          <td className="py-2 pr-4">{t.current_stage || t.failed_stage || '—'}</td>
                          <td className="py-2 pr-4">
                            {t.latency_ms != null ? `${Math.round(t.latency_ms)} ms` : '—'}
                          </td>
                          <td className="py-2">{t.country_code || '—'}</td>
                        </tr>
                      ))}
                      {(summary.latest_transactions || []).length === 0 && (
                        <tr>
                          <td colSpan={5} className="py-6 text-center text-slate-400">
                            No pipeline transactions yet for this workspace.
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </WorkspaceShell>
      </div>
    </MainLayout>
  );
}
