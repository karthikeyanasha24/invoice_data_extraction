'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import { useAuth } from '@/contexts/AuthContext';
import { workspaceApi } from '@/lib/api';
import WorkspaceShell from '@/components/workspace/WorkspaceShell';

const SECRET_REF_PREFIXES = ['vault:', 'env:', 'secret:', 'arn:', 'kms:', 'ref:'];

function isSecretRef(value: string): boolean {
  const v = value.trim();
  if (!v) return true;
  return SECRET_REF_PREFIXES.some((p) => v.startsWith(p));
}

function isEndpointOrRef(value: string): boolean {
  const v = value.trim();
  if (!v) return true;
  if (v.startsWith('http://') || v.startsWith('https://')) return true;
  return isSecretRef(v);
}

export default function WorkspaceSettingsPage() {
  const params = useParams();
  const customerId = decodeURIComponent(String(params.customerId || ''));
  const { user, loading } = useAuth();
  const router = useRouter();
  const [ws, setWs] = useState<any>(null);
  const [onboarding, setOnboarding] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [displayName, setDisplayName] = useState('');
  const [pipelineEnabled, setPipelineEnabled] = useState(false);
  const [aiScoped, setAiScoped] = useState(true);
  const [monitoringEnabled, setMonitoringEnabled] = useState(true);
  const [erpUpdateMode, setErpUpdateMode] = useState('auto');
  const [connectionKey, setConnectionKey] = useState('primary');
  const [callbackUrl, setCallbackUrl] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [authType, setAuthType] = useState('none');
  const [clientIdRef, setClientIdRef] = useState('');
  const [clientSecretRef, setClientSecretRef] = useState('');
  const [countryCode, setCountryCode] = useState('mx_cfdi');
  const [adapterEnabled, setAdapterEnabled] = useState(false);
  const [govEndpointRef, setGovEndpointRef] = useState('');
  const [govAuthType, setGovAuthType] = useState('none');
  const [govAuthSecretRef, setGovAuthSecretRef] = useState('');

  const refresh = async () => {
    const [data, status] = await Promise.all([
      workspaceApi.getWorkspace(customerId),
      workspaceApi.getOnboardingStatus(customerId),
    ]);
    setWs(data);
    setOnboarding(status);
    setDisplayName(data.display_name || customerId);
    setPipelineEnabled(!!data.pipeline_enabled);
    setAiScoped(data.ai_scoped !== false);
    setMonitoringEnabled(data.monitoring_enabled !== false);
    const mode = (data.flags?.erp_update_mode as string) || 'auto';
    setErpUpdateMode(mode);
    if (data.erp) {
      setConnectionKey(data.erp.connection_key || 'primary');
      setBaseUrl(data.erp.base_url || '');
      setCallbackUrl(data.erp.callback_url || '');
      setAuthType(data.erp.auth_type || 'none');
      setClientIdRef(data.erp.client_id_ref || '');
      setClientSecretRef(data.erp.client_secret_ref || '');
    }
    const mx =
      (data.adapters || []).find((a: any) => a.country_code === 'mx_cfdi') ||
      (data.adapters || [])[0];
    if (mx) {
      setCountryCode(mx.country_code);
      setAdapterEnabled(!!mx.enabled);
      setGovEndpointRef(mx.endpoint_url_ref || '');
      setGovAuthType(mx.auth_type || 'none');
      setGovAuthSecretRef(mx.auth_secret_ref || '');
    }
  };

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !customerId) return;
    (async () => {
      try {
        await refresh();
      } catch (e: any) {
        setError(e?.response?.data?.detail || e?.message || 'Failed to load');
      }
    })();
  }, [user, customerId]);

  const validateClient = (): string | null => {
    if (!isSecretRef(clientIdRef)) {
      return 'ERP client ID must be a secret ref (vault:/env:/secret:…) or empty';
    }
    if (!isSecretRef(clientSecretRef)) {
      return 'ERP client secret must be a secret ref (vault:/env:/secret:…) or empty';
    }
    if (!isEndpointOrRef(govEndpointRef)) {
      return 'Government endpoint must be https://… or a secret ref';
    }
    if (!isSecretRef(govAuthSecretRef)) {
      return 'Government auth secret must be a secret ref or empty';
    }
    if (authType !== 'none' && !clientSecretRef.trim() && authType !== 'mtls') {
      return `ERP auth_type=${authType} requires client_secret_ref`;
    }
    if ((authType === 'oauth2' || authType === 'basic') && !clientIdRef.trim()) {
      return `ERP auth_type=${authType} requires client_id_ref`;
    }
    if (
      pipelineEnabled &&
      onboarding &&
      onboarding.pipeline_prerequisites_met === false &&
      !(ws?.pipeline_enabled)
    ) {
      const missing = (onboarding.pipeline_prerequisites_missing || []).join(', ');
      return `Cannot enable pipeline until prerequisites are complete: ${missing || 'ERP, adapter, government'}`;
    }
    return null;
  };

  const onSaveSettings = async (e: FormEvent) => {
    e.preventDefault();
    if (!user?.is_admin) return;
    const validationError = validateClient();
    if (validationError) {
      setError(validationError);
      return;
    }
    setSaving(true);
    setMessage(null);
    setError(null);
    try {
      if (!ws?.has_settings) {
        await workspaceApi.createSettings({
          customer_id: customerId,
          display_name: displayName,
          pipeline_enabled: pipelineEnabled,
          ai_scoped: aiScoped,
          monitoring_enabled: monitoringEnabled,
          flags: { erp_update_mode: erpUpdateMode },
        });
      } else {
        await workspaceApi.updateSettings(customerId, {
          display_name: displayName,
          pipeline_enabled: pipelineEnabled,
          ai_scoped: aiScoped,
          monitoring_enabled: monitoringEnabled,
          flags: { erp_update_mode: erpUpdateMode },
        });
      }
      await workspaceApi.upsertErp(customerId, {
        connection_key: connectionKey || 'primary',
        base_url: baseUrl || undefined,
        callback_url: callbackUrl || undefined,
        auth_type: authType,
        client_id_ref: clientIdRef || undefined,
        client_secret_ref: clientSecretRef || undefined,
        is_active: true,
      });
      await workspaceApi.upsertAdapter(customerId, {
        country_code: countryCode,
        enabled: adapterEnabled,
        endpoint_url_ref: govEndpointRef || undefined,
        auth_type: govAuthType === 'none' ? undefined : govAuthType,
        auth_secret_ref: govAuthSecretRef || undefined,
      });
      await refresh();
      setMessage('Workspace configuration saved. Review onboarding checklist below.');
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Save failed');
    } finally {
      setSaving(false);
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
    <MainLayout>
      <div className="p-4 md:p-6">
        <WorkspaceShell customerId={customerId} displayName={displayName} activeTab="settings">
          {!user.is_admin ? (
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-600">
              Settings are admin-only. You can view overview and transaction tabs for assigned workspaces.
            </div>
          ) : (
            <form onSubmit={onSaveSettings} className="max-w-2xl space-y-6">
              {error && (
                <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
                  {typeof error === 'string' ? error : JSON.stringify(error)}
                </div>
              )}
              {message && (
                <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
                  {message}
                </div>
              )}

              {onboarding && (
                <section
                  className={`space-y-3 rounded-xl border p-4 ${
                    onboarding.ready
                      ? 'border-emerald-200 bg-emerald-50'
                      : 'border-amber-200 bg-amber-50'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="text-sm font-semibold text-slate-800">
                      Readiness wizard — {onboarding.ready ? 'Ready for production' : 'Incomplete'}
                    </h2>
                    <span className="text-xs font-medium text-slate-600">
                      {onboarding.summary?.progress_pct ?? 0}% complete
                    </span>
                  </div>
                  <div className="h-2 w-full overflow-hidden rounded-full bg-white/70">
                    <div
                      className={`h-full rounded-full transition-all ${
                        onboarding.ready ? 'bg-emerald-600' : 'bg-amber-500'
                      }`}
                      style={{ width: `${Math.min(100, onboarding.summary?.progress_pct ?? 0)}%` }}
                    />
                  </div>
                  <ul className="space-y-1 text-xs text-slate-700">
                    {(onboarding.steps || []).map((s: any) => (
                      <li key={s.key} className="flex gap-2">
                        <span className={s.ok ? 'text-emerald-700' : 'text-amber-800'}>
                          {s.ok ? '✓' : '○'}
                        </span>
                        <span>
                          {s.label}
                          {!s.required ? ' (advisory)' : ''}
                          {s.detail ? (
                            <span className="text-slate-500"> — {s.detail}</span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {!onboarding.pipeline_prerequisites_met && (
                    <p className="text-xs text-amber-900">
                      Pipeline enablement is locked until ERP, adapter, government endpoint, and
                      monitoring are configured.
                    </p>
                  )}
                  {onboarding.ready && (
                    <p className="text-xs font-medium text-emerald-800">
                      ✓ Ready for production — this workspace can process invoices on the BridgeEDI
                      path.
                    </p>
                  )}
                </section>
              )}

              <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Workspace settings</h2>
                <label className="block text-xs text-slate-600">
                  Display name
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                  />
                </label>
                <label className="flex items-start gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={pipelineEnabled}
                    disabled={
                      !pipelineEnabled &&
                      onboarding &&
                      onboarding.pipeline_prerequisites_met === false
                    }
                    onChange={(e) => setPipelineEnabled(e.target.checked)}
                  />
                  <span>
                    Pipeline enabled (shared pipeline path for this workspace)
                    {!pipelineEnabled &&
                      onboarding &&
                      onboarding.pipeline_prerequisites_met === false && (
                        <span className="mt-0.5 block text-xs text-amber-700">
                          Complete ERP, country adapter, and government endpoint first.
                        </span>
                      )}
                  </span>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={aiScoped}
                    onChange={(e) => setAiScoped(e.target.checked)}
                  />
                  AI Ops scoped to this workspace
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={monitoringEnabled}
                    onChange={(e) => setMonitoringEnabled(e.target.checked)}
                  />
                  Monitoring enabled
                </label>
                <label className="block text-xs text-slate-600">
                  ERP update mode
                  <select
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={erpUpdateMode}
                    onChange={(e) => setErpUpdateMode(e.target.value)}
                  >
                    <option value="auto">auto — skip platform ERP if submit already updated ERP</option>
                    <option value="always">always — always run platform ERP push</option>
                    <option value="never">never — disable platform ERP push</option>
                  </select>
                </label>
              </section>

              <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">ERP connection (secret refs only)</h2>
                <p className="text-xs text-amber-700">
                  Use prefixes <code>vault:</code> / <code>env:</code> / <code>secret:</code> — plaintext
                  secrets are rejected by the API.
                </p>
                <label className="block text-xs text-slate-600">
                  Connection key (supports multiple ERPs, e.g. primary / billing)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={connectionKey}
                    onChange={(e) => setConnectionKey(e.target.value)}
                  />
                </label>
                <label className="block text-xs text-slate-600">
                  Base URL
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="https://erp.customer.example/api"
                  />
                </label>
                <label className="block text-xs text-slate-600">
                  Confirmation callback URL
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={callbackUrl}
                    onChange={(e) => setCallbackUrl(e.target.value)}
                  />
                </label>
                <label className="block text-xs text-slate-600">
                  Auth type
                  <select
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={authType}
                    onChange={(e) => setAuthType(e.target.value)}
                  >
                    <option value="none">none</option>
                    <option value="api_key">api_key</option>
                    <option value="bearer">bearer</option>
                    <option value="oauth2">oauth2</option>
                    <option value="basic">basic</option>
                    <option value="mtls">mtls</option>
                  </select>
                </label>
                <label className="block text-xs text-slate-600">
                  Client ID ref (vault/env)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={clientIdRef}
                    onChange={(e) => setClientIdRef(e.target.value)}
                    placeholder="vault:acme/erp/client_id"
                  />
                </label>
                <label className="block text-xs text-slate-600">
                  Client secret / token ref (vault/env)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={clientSecretRef}
                    onChange={(e) => setClientSecretRef(e.target.value)}
                    placeholder="vault:acme/erp/client_secret"
                  />
                </label>
              </section>

              <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Country adapter</h2>
                <label className="block text-xs text-slate-600">
                  Country adapter
                  <select
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={countryCode}
                    onChange={(e) => setCountryCode(e.target.value)}
                  >
                    <option value="mx_cfdi">mx_cfdi — Mexico CFDI / SAT</option>
                    <option value="sample_gst">sample_gst — Sample GST (demo)</option>
                  </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={adapterEnabled}
                    onChange={(e) => setAdapterEnabled(e.target.checked)}
                  />
                  Enabled for this workspace
                </label>
                <label className="block text-xs text-slate-600">
                  Government endpoint (https://… or vault:… ref)
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={govEndpointRef}
                    onChange={(e) => setGovEndpointRef(e.target.value)}
                    placeholder="https://gov.example/api or vault:acme/gov/url"
                  />
                </label>
                <label className="block text-xs text-slate-600">
                  Government auth type
                  <select
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    value={govAuthType}
                    onChange={(e) => setGovAuthType(e.target.value)}
                  >
                    <option value="none">none</option>
                    <option value="bearer">bearer</option>
                    <option value="api_key">api_key</option>
                    <option value="basic">basic</option>
                  </select>
                </label>
                <label className="block text-xs text-slate-600">
                  Government auth secret ref
                  <input
                    className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm font-mono"
                    value={govAuthSecretRef}
                    onChange={(e) => setGovAuthSecretRef(e.target.value)}
                    placeholder="vault:acme/gov/token"
                  />
                </label>
                <p className="text-xs text-slate-500">
                  Enabling <code>mx_cfdi</code> stores workspace adapter config used by the existing
                  country adapter registry. SAT / V1 / V2 routes are unchanged.
                </p>
              </section>

              <button
                type="submit"
                disabled={saving}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {saving ? 'Saving…' : 'Save workspace configuration'}
              </button>
            </form>
          )}
        </WorkspaceShell>
      </div>
    </MainLayout>
  );
}
