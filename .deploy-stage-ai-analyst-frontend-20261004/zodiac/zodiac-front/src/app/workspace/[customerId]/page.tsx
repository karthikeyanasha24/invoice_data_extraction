'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useParams, useRouter } from 'next/navigation';
import { Loader } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import { useAuth } from '@/contexts/AuthContext';
import { workspaceApi } from '@/lib/api';
import WorkspaceShell from '@/components/workspace/WorkspaceShell';

export default function WorkspaceOverviewPage() {
  const params = useParams();
  const customerId = decodeURIComponent(String(params.customerId || ''));
  const { user, loading } = useAuth();
  const router = useRouter();
  const [data, setData] = useState<any>(null);
  const [activity, setActivity] = useState<any>(null);
  const [onboarding, setOnboarding] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !customerId) return;
    let cancelled = false;
    (async () => {
      try {
        const [ws, act, status] = await Promise.all([
          workspaceApi.getWorkspace(customerId),
          workspaceApi.getActivity(customerId),
          workspaceApi.getOnboardingStatus(customerId),
        ]);
        if (!cancelled) {
          setData(ws);
          setActivity(act);
          setOnboarding(status);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || 'Failed to load workspace');
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

  return (
    <MainLayout>
      <div className="p-4 md:p-6">
        <WorkspaceShell
          customerId={customerId}
          displayName={data?.display_name}
          activeTab="overview"
        >
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
          {!data ? (
            <div className="flex justify-center py-12">
              <Loader className="h-8 w-8 animate-spin text-blue-500" />
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2">
              {onboarding && (
                <div
                  className={`rounded-xl border p-4 md:col-span-2 ${
                    onboarding.ready
                      ? 'border-emerald-200 bg-emerald-50'
                      : 'border-amber-200 bg-amber-50'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold text-slate-800">
                      Customer readiness — {onboarding.ready ? 'Ready' : 'Configuration incomplete'}
                    </h2>
                    <Link
                      href={`/workspace/${encodeURIComponent(customerId)}/settings`}
                      className="text-xs font-medium text-blue-700 hover:underline"
                    >
                      Open settings
                    </Link>
                  </div>
                  <p className="mt-1 text-xs text-slate-600">
                    {onboarding.summary?.required_ok ?? 0}/
                    {onboarding.summary?.required_total ?? 0} required steps complete
                    {onboarding.missing?.length
                      ? ` · missing: ${onboarding.missing.join(', ')}`
                      : ''}
                  </p>
                </div>
              )}

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Workspace flags</h2>
                <dl className="mt-3 space-y-2 text-sm text-slate-600">
                  <div className="flex justify-between">
                    <dt>Settings row</dt>
                    <dd>{data.has_settings ? 'Yes' : 'No — enable from /workspace'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Pipeline enabled</dt>
                    <dd>{data.pipeline_enabled ? 'Yes' : 'No'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Monitoring</dt>
                    <dd>{data.monitoring_enabled !== false ? 'Yes' : 'No'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>AI Ops scoped</dt>
                    <dd>{data.ai_scoped ? 'Yes' : 'No'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>ERP update mode</dt>
                    <dd className="font-mono">
                      {(data.flags?.erp_update_mode as string) || 'auto (default)'}
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Target format</dt>
                    <dd className="font-mono">{data.target_format || '—'}</dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Activity (scoped)</h2>
                <dl className="mt-3 space-y-2 text-sm text-slate-600">
                  <div className="flex justify-between">
                    <dt>V2 validated invoices</dt>
                    <dd>{activity?.v2_validated_count ?? '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>SAT documents (via RFCs)</dt>
                    <dd>{activity?.sat_document_count ?? '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Receiver RFCs</dt>
                    <dd>{activity?.receiver_rfc_count ?? '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>ERP connections</dt>
                    <dd>{activity?.erp_connection_count ?? '—'}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt>Adapters</dt>
                    <dd>{activity?.adapter_count ?? '—'}</dd>
                  </div>
                </dl>
                {activity?.notes?.length > 0 && (
                  <ul className="mt-3 list-disc pl-4 text-xs text-amber-700">
                    {activity.notes.map((n: string) => (
                      <li key={n}>{n}</li>
                    ))}
                  </ul>
                )}
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4 md:col-span-2">
                <h2 className="text-sm font-semibold text-slate-800">Enabled adapters</h2>
                {data.adapters?.filter((a: any) => a.enabled).length ? (
                  <ul className="mt-2 space-y-1 text-sm text-slate-600">
                    {data.adapters
                      .filter((a: any) => a.enabled)
                      .map((a: any) => (
                        <li key={a.country_code} className="font-mono">
                          {a.country_code}
                          {a.endpoint_url_ref ? ` · gov=${a.endpoint_url_ref}` : ''}
                          {a.rules_version ? ` @ ${a.rules_version}` : ''}
                        </li>
                      ))}
                  </ul>
                ) : (
                  <p className="mt-2 text-sm text-slate-500">
                    None enabled yet. Configure on the Settings tab (admin).
                  </p>
                )}
              </div>
            </div>
          )}
        </WorkspaceShell>
      </div>
    </MainLayout>
  );
}
