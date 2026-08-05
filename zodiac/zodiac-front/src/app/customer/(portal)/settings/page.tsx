'use client';

import { useEffect, useState } from 'react';
import { Loader } from 'lucide-react';
import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import { workspaceApi } from '@/lib/api';

/** Read-only workspace / ERP / adapter status for customers (mutations remain admin-only). */
export default function CustomerSettingsPortalPage() {
  const { customerId } = useCustomerPortal();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!customerId) return;
    let cancelled = false;
    (async () => {
      try {
        const ws = await workspaceApi.getWorkspace(customerId);
        if (!cancelled) {
          setData(ws);
          setError(null);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || 'Failed to load settings');
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

  const erp = data.erp;
  const erps = data.erps || (erp ? [erp] : []);

  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Read-only view of your workspace configuration. Changes are managed by your BridgeEDI
        administrator.
      </p>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Workspace</h2>
        <dl className="mt-3 space-y-2 text-sm text-slate-600">
          <div className="flex justify-between gap-4">
            <dt>Display name</dt>
            <dd>{data.display_name || customerId}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>Pipeline</dt>
            <dd>{data.pipeline_enabled ? 'Enabled' : 'Disabled'}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>Monitoring</dt>
            <dd>{data.monitoring_enabled !== false ? 'Enabled' : 'Disabled'}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>AI Ops scoped</dt>
            <dd>{data.ai_scoped ? 'Yes' : 'No'}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt>ERP update mode</dt>
            <dd className="font-mono">{(data.flags?.erp_update_mode as string) || 'auto'}</dd>
          </div>
        </dl>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">ERP connections</h2>
        {erps.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No ERP connection configured.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {erps.map((e: any) => (
              <li
                key={e.connection_key || e.id}
                className="rounded-lg border border-slate-100 px-3 py-2 text-sm text-slate-600"
              >
                <p className="font-medium text-slate-800">
                  {e.label || e.connection_key || 'ERP'}{' '}
                  <span className="font-mono text-xs text-slate-500">
                    ({e.is_active === false ? 'inactive' : 'active'})
                  </span>
                </p>
                <p className="mt-1 font-mono text-xs break-all">{e.base_url || '—'}</p>
                <p className="mt-1 text-xs">Auth: {e.auth_type || 'none'}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Country adapters</h2>
        {(data.adapters || []).length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No adapters configured.</p>
        ) : (
          <ul className="mt-3 space-y-2 text-sm text-slate-600">
            {data.adapters.map((a: any) => (
              <li key={a.country_code} className="flex justify-between gap-4 font-mono text-xs">
                <span>{a.country_code}</span>
                <span>{a.enabled ? 'enabled' : 'disabled'}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
