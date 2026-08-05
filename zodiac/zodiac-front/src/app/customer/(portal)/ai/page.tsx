'use client';

import { FormEvent, useEffect, useState } from 'react';
import { Loader } from 'lucide-react';
import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import { aiOpsApi } from '@/lib/api';

export default function CustomerAiOpsPortalPage() {
  const { customerId } = useCustomerPortal();
  const [summary, setSummary] = useState<any>(null);
  const [recommendations, setRecommendations] = useState<any[]>([]);
  const [question, setQuestion] = useState('What failed today?');
  const [answer, setAnswer] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!customerId) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [sum, rec] = await Promise.all([
          aiOpsApi.getSummary(customerId),
          aiOpsApi.getRecommendations(customerId),
        ]);
        if (!cancelled) {
          setSummary(sum);
          setRecommendations(rec?.recommendations || []);
          setError(null);
        }
      } catch (e: any) {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || 'Failed to load AI Ops');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [customerId]);

  async function onAsk(e: FormEvent) {
    e.preventDefault();
    if (!customerId || !question.trim()) return;
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

  if (!customerId) {
    return <p className="text-sm text-slate-600">No workspace assigned.</p>;
  }
  if (loading) {
    return (
      <div className="flex justify-center py-16">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" />
      </div>
    );
  }

  const counts = summary?.counts || {};

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      <p className="text-sm text-slate-600">
        Operational intelligence from <strong>monitoring data only</strong> for your workspace. AI
        never joins invoice processing.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Completed</p>
          <p className="mt-1 text-2xl font-semibold">{counts.completed ?? 0}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Failed</p>
          <p className="mt-1 text-2xl font-semibold">{counts.failed ?? 0}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-xs uppercase text-slate-500">Running</p>
          <p className="mt-1 text-2xl font-semibold">{counts.running ?? 0}</p>
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Recommendations</h2>
        <ul className="mt-3 space-y-2 text-sm text-slate-600">
          {recommendations.length === 0 && <li className="text-slate-400">No recommendations.</li>}
          {recommendations.map((r: any, i: number) => (
            <li key={r.code || i} className="rounded-lg border border-slate-100 px-3 py-2">
              <p className="font-medium text-slate-800">{r.title || r.code || 'Recommendation'}</p>
              {r.detail && <p className="mt-1 text-xs text-slate-500">{r.detail}</p>}
            </li>
          ))}
        </ul>
      </div>

      <form onSubmit={onAsk} className="rounded-xl border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Ask AI Ops</h2>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            placeholder="Ask about failures, latency, alerts…"
          />
          <button
            type="submit"
            disabled={asking}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 disabled:opacity-60"
          >
            {asking ? 'Asking…' : 'Ask'}
          </button>
        </div>
        {answer && (
          <pre className="mt-3 overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">
            {typeof answer === 'string' ? answer : JSON.stringify(answer, null, 2)}
          </pre>
        )}
      </form>
    </div>
  );
}
