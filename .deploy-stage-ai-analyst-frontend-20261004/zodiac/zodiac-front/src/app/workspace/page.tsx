'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Loader, Plus } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import { useAuth } from '@/contexts/AuthContext';
import { workspaceApi, customerApi } from '@/lib/api';

type WorkspaceItem = {
  workspace_id: string;
  customer_id: string;
  display_name?: string;
  pipeline_enabled: boolean;
  ai_scoped: boolean;
  has_settings: boolean;
  enabled_adapters: string[];
};

export default function WorkspaceIndexPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [items, setItems] = useState<WorkspaceItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [creatingFor, setCreatingFor] = useState<string | null>(null);
  const [customersWithoutSettings, setCustomersWithoutSettings] = useState<string[]>([]);

  useEffect(() => {
    if (!loading && !user) {
      router.replace('/');
    }
  }, [loading, user, router]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      setBusy(true);
      setError(null);
      try {
        const data = await workspaceApi.listWorkspaces();
        if (cancelled) return;
        setItems(data.workspaces || []);
        if (user.is_admin) {
          const cust = await customerApi.getCustomers(0, 200);
          const allIds: string[] = (cust.customers || []).map((c: { customer_id: string }) => c.customer_id);
          const withSettings = new Set((data.workspaces || []).filter((w: WorkspaceItem) => w.has_settings).map((w: WorkspaceItem) => w.customer_id));
          setCustomersWithoutSettings(allIds.filter((id) => !withSettings.has(id)));
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || 'Failed to load workspaces');
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user]);

  const enableWorkspace = async (customerId: string) => {
    setCreatingFor(customerId);
    try {
      await workspaceApi.createSettings({
        customer_id: customerId,
        display_name: customerId,
        pipeline_enabled: false,
        ai_scoped: true,
        monitoring_enabled: true,
        flags: { erp_update_mode: 'auto' },
      });
      router.push(`/workspace/${encodeURIComponent(customerId)}`);
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to create workspace');
    } finally {
      setCreatingFor(null);
    }
  };

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
    <MainLayout topSection={<TopSection title="Workspaces" subtitle="Customer exclusive spaces" />}>
      <div className="space-y-6 p-4 md:p-6">
        <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-600">
          Customer workspaces for BridgeEDI onboarding. Create the customer under{' '}
          <code>/customers</code>, enable workspace settings here, then complete ERP, secrets,
          country adapter, government endpoint, monitoring, and AI Ops on the Settings tab.
          Existing SAT / V1 / V2 routes are unchanged.
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {busy ? (
          <div className="flex justify-center py-16">
            <Loader className="h-8 w-8 animate-spin text-blue-500" />
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {items.map((w) => (
              <Link
                key={w.customer_id}
                href={`/workspace/${encodeURIComponent(w.customer_id)}`}
                className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-blue-300 hover:shadow"
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h2 className="font-semibold text-slate-900">{w.display_name || w.customer_id}</h2>
                    <p className="mt-1 font-mono text-xs text-slate-500">{w.customer_id}</p>
                  </div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      w.has_settings ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-600'
                    }`}
                  >
                    {w.has_settings ? 'Configured' : 'No settings yet'}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2 text-xs text-slate-600">
                  <span>Pipeline: {w.pipeline_enabled ? 'on' : 'off'}</span>
                  <span>AI scoped: {w.ai_scoped ? 'yes' : 'no'}</span>
                </div>
                {w.enabled_adapters?.length > 0 && (
                  <p className="mt-2 text-xs text-blue-700">
                    Adapters: {w.enabled_adapters.join(', ')}
                  </p>
                )}
              </Link>
            ))}
          </div>
        )}

        {user.is_admin && customersWithoutSettings.length > 0 && (
          <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-4">
            <h3 className="text-sm font-semibold text-slate-800">Enable workspace settings</h3>
            <p className="mt-1 text-xs text-slate-600">
              Creates a <code>workspace_settings</code> row for an existing customer (admin only).
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {customersWithoutSettings.slice(0, 20).map((id) => (
                <button
                  key={id}
                  type="button"
                  disabled={creatingFor === id}
                  onClick={() => enableWorkspace(id)}
                  className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-blue-400 hover:text-blue-700 disabled:opacity-50"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {creatingFor === id ? 'Creating…' : id}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </MainLayout>
  );
}
