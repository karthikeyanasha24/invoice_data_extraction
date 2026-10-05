'use client';

import { FormEvent, useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Loader } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import { useAuth } from '@/contexts/AuthContext';
import { aiOpsApi, workspaceApi } from '@/lib/api';
import WorkspaceShell from '@/components/workspace/WorkspaceShell';

export default function WorkspaceAiOpsPage() {
  const params = useParams();
  const customerId = decodeURIComponent(String(params.customerId || ''));
  const { user, loading } = useAuth();
  const router = useRouter();
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [summary, setSummary] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [question, setQuestion] = useState('What failed today?');
  const [answer, setAnswer] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !customerId) return;
    let cancelled = false;
    (async () => {
      try {
        const [ws, sum, rec] = await Promise.all([
          workspaceApi.getWorkspace(customerId).catch(() => null),
          aiOpsApi.getSummary(customerId),
          aiOpsApi.getRecommendations(customerId),
        ]);
        if (!cancelled) {
          setDisplayName(ws?.display_name || null);
          setSummary(sum);
          setRecommendations(rec?.recommendations || []);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || 'Failed to load AI Ops');
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [user, customerId]);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!question.trim()) return;
    setAsking(true);
    setError(null);
    try {
      const res = await aiOpsApi.ask(customerId, { question });
      setAnswer(res);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Ask failed');
    } finally {
      setAsking(false);
    }
  }

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
        <WorkspaceShell customerId={customerId} displayName={displayName} activeTab="ai">
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {typeof error === 'string' ? error : JSON.stringify(error)}
            </div>
          )}

          {!summary ? (
            <div className="flex justify-center py-12">
              <Loader className="h-8 w-8 animate-spin text-blue-500" />
            </div>
          ) : (
            <div className="space-y-6">
              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Operational summary</h2>
                <p className="mt-2 text-sm leading-relaxed text-slate-700">{summary.narrative}</p>
                <dl className="mt-4 grid gap-3 sm:grid-cols-3 text-sm">
                  <div>
                    <dt className="text-slate-500">Success rate</dt>
                    <dd className="font-semibold text-slate-900">
                      {summary.success_rate_percent != null
                        ? `${summary.success_rate_percent.toFixed(1)}%`
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Avg processing</dt>
                    <dd className="font-semibold text-slate-900">
                      {summary.average_processing_time_ms != null
                        ? `${Math.round(summary.average_processing_time_ms)} ms`
                        : '—'}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-slate-500">Failures today</dt>
                    <dd className="font-semibold text-slate-900">
                      {summary.failures_today_count ?? 0}
                    </dd>
                  </div>
                </dl>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Recommendations</h2>
                <ul className="mt-3 space-y-3">
                  {recommendations.map((r) => (
                    <li key={r.code} className="rounded-lg border border-slate-100 px-3 py-2">
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-medium text-slate-900">{r.title}</p>
                        <span className="text-xs uppercase tracking-wide text-slate-500">
                          {r.priority}
                        </span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600">{r.detail}</p>
                    </li>
                  ))}
                </ul>
              </div>

              <div className="rounded-xl border border-slate-200 bg-white p-4">
                <h2 className="text-sm font-semibold text-slate-800">Ask (monitoring facts only)</h2>
                <form onSubmit={onAsk} className="mt-3 flex flex-col gap-3 sm:flex-row">
                  <input
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
                    placeholder="What failed today?"
                  />
                  <button
                    type="submit"
                    disabled={asking}
                    className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-60"
                  >
                    {asking ? 'Asking…' : 'Ask'}
                  </button>
                </form>
                {answer && (
                  <pre className="mt-4 overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-800">
                    {JSON.stringify(answer, null, 2)}
                  </pre>
                )}
              </div>
            </div>
          )}
        </WorkspaceShell>
      </div>
    </MainLayout>
  );
}
