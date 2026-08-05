'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Loader } from 'lucide-react';
import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import { workspaceApi } from '@/lib/api';

export default function CustomerOverviewPage() {
  const { customerId } = useCustomerPortal();
  const [data, setData] = useState<any>(null);
  const [activity, setActivity] = useState<any>(null);
  const [onboarding, setOnboarding] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) return;
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
          setError(null);
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
  }, [customerId]);

  if (!customerId) {
    return <p className="text-sm text-slate-600">No workspace assigned.</p>;
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        {error}
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex justify-center py-16">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" />
      </div>
    );
  }

  return (
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
              Workspace readiness — {onboarding.ready ? 'Ready' : 'Setup in progress'}
            </h2>
            <Link href="/customer/settings" className="text-xs font-medium text-emerald-800 hover:underline">
              View settings
            </Link>
          </div>
          <p className="mt-1 text-xs text-slate-600">
            {onboarding.ready
              ? 'Your BridgeEDI workspace is fully configured.'
              : 'Your administrator is finishing ERP, government, and pipeline setup.'}
            {' '}
            ({onboarding.summary?.required_ok ?? 0}/{onboarding.summary?.required_total ?? 0}{' '}
            steps · {onboarding.summary?.progress_pct ?? 0}%)
          </p>
          {!onboarding.ready && (
            <ul className="mt-2 grid gap-1 text-xs text-slate-700 sm:grid-cols-2">
              {(onboarding.steps || [])
                .filter((s: any) => s.required)
                .map((s: any) => (
                  <li key={s.key} className="flex gap-1.5">
                    <span>{s.ok ? '✓' : '○'}</span>
                    <span>{s.label}</span>
                  </li>
                ))}
            </ul>
          )}
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Workspace status</h2>
        <dl className="mt-3 space-y-2 text-sm text-slate-600">
          <div className="flex justify-between">
            <dt>Pipeline</dt>
            <dd>{data.pipeline_enabled ? 'Enabled' : 'Off'}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Monitoring</dt>
            <dd>{data.monitoring_enabled !== false ? 'On' : 'Off'}</dd>
          </div>
          <div className="flex justify-between">
            <dt>AI Ops</dt>
            <dd>{data.ai_scoped ? 'Scoped' : 'Off'}</dd>
          </div>
          <div className="flex justify-between">
            <dt>ERP update mode</dt>
            <dd className="font-mono">{(data.flags?.erp_update_mode as string) || 'auto'}</dd>
          </div>
          <div className="flex justify-between">
            <dt>Target format</dt>
            <dd className="font-mono">{data.target_format || '—'}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Activity</h2>
        <dl className="mt-3 space-y-2 text-sm text-slate-600">
          <div className="flex justify-between">
            <dt>V2 validated invoices</dt>
            <dd>{activity?.v2_validated_count ?? '—'}</dd>
          </div>
          <div className="flex justify-between">
            <dt>SAT documents</dt>
            <dd>{activity?.sat_document_count ?? '—'}</dd>
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
                </li>
              ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-slate-500">None enabled yet.</p>
        )}
      </div>
    </div>
  );
}
