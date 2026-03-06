'use client';

import { useState, useRef, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import {
  Sparkles,
  Send,
  ArrowDownToLine,
  ArrowUpFromLine,
  TrendingUp,
  GitBranch,
  ChevronDown,
  ChevronRight,
  RefreshCw,
} from 'lucide-react';

const DEFAULT_DAYS = 30;
const AI_CONTEXT_KEYS = [
  'stats',
  'failed_summary',
  'top_customers',
  'inbound_summary',
  'business_summary',
  'process_flow',
];

const SUGGESTED_PROMPTS = [
  { label: 'Top customers with currency and invoice count', query: 'Show top customers we have with currency and number of invoices (outbound process)' },
  { label: 'Outbound process flow', query: 'Show the outbound process flow and current document counts at each step' },
  { label: 'Inbound SAT status', query: 'Summarize inbound SAT documents: merges, sent to SAP vs pending, and top suppliers' },
  { label: 'Revenue by customer', query: 'Summarize revenue by customer and by country' },
  { label: 'Failed invoices summary', query: 'Summarize failed invoices and main failure reasons' },
  { label: 'Flow deviation', query: 'How does my current document flow deviate from the standard process?' },
];

type AiAnalysisMeta = {
  action?: string;
  reason?: string;
  sql?: string;
  rows_preview?: Record<string, unknown>[];
  compare?: unknown;
};

type Message = { role: 'user' | 'assistant'; content: string; meta?: AiAnalysisMeta };

type OutboundData = {
  summary?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
  top_customers?: { customer_id: string; customer_name: string; currency: string; count: number }[];
  funnel?: { documents_received: number; validated_success: number; validated_failed: number; converted_success: number; converted_failed: number; converted_pending: number };
};

type InboundData = {
  summary?: { total_documents: number; merges_total: number; merges_sent_to_sap: number; merges_pending: number };
  top_suppliers?: { supplier_rfc: string; supplier_name: string; count: number; total_amount: number }[];
};

type BusinessData = {
  revenue_by_customer?: { customer_id: string; customer_name: string; invoice_count: number; total_revenue: number }[];
  revenue_by_country?: { country: string; country_name?: string; invoice_count: number; total_revenue: number }[];
  trend?: { current_period_revenue: number; previous_period_revenue: number; revenue_change_pct: number };
};

export default function DashboardAIAnalysis() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [useContext, setUseContext] = useState(true);
  const [days, setDays] = useState(DEFAULT_DAYS);
  const [outboundData, setOutboundData] = useState<OutboundData | null>(null);
  const [inboundData, setInboundData] = useState<InboundData | null>(null);
  const [businessData, setBusinessData] = useState<BusinessData | null>(null);
  const [dataLoading, setDataLoading] = useState(true);
  const [dataPanelTab, setDataPanelTab] = useState<'sales' | 'finance' | 'logistics' | 'flow'>('sales');
  const [flowExpanded, setFlowExpanded] = useState<'outbound' | 'inbound' | null>(null);
  const answerEndRef = useRef<HTMLDivElement>(null);

  const scrollToAnswer = () => {
    answerEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToAnswer();
  }, [messages]);

  const fetchDashboardData = async () => {
    setDataLoading(true);
    try {
      const [outbound, inbound, business] = await Promise.all([
        dashboardApi.getV2Outbound(days),
        dashboardApi.getV2Inbound(days),
        dashboardApi.getV2Business(days),
      ]);
      setOutboundData(outbound || null);
      setInboundData(inbound || null);
      setBusinessData(business || null);
    } catch {
      setOutboundData(null);
      setInboundData(null);
      setBusinessData(null);
    } finally {
      setDataLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
  }, [days]);

  const sendMessage = async (text?: string) => {
    const msg = (text ?? input).trim();
    if (!msg || loading) return;

    if (!text) setInput('');
    setError(null);
    setMessages((prev) => [...prev, { role: 'user', content: msg }]);
    setLoading(true);

    const contextKeys = useContext ? AI_CONTEXT_KEYS : [];
    const conversationHistory = messages.map((m) => ({ role: m.role, content: m.content }));

    try {
      const res = await dashboardApi.postAIAnalysisChat(msg, conversationHistory, contextKeys, days);
      const reply = (res as { reply?: string })?.reply ?? 'No response received.';
      const meta: AiAnalysisMeta = {
        action: (res as any)?.action,
        reason: (res as any)?.reason,
        sql: (res as any)?.sql,
        rows_preview: (res as any)?.rows_preview,
        compare: (res as any)?.compare,
      };
      const hasMeta = Boolean(meta.action || meta.sql || (meta.rows_preview && meta.rows_preview.length));
      setMessages((prev) => [...prev, { role: 'assistant', content: reply, meta: hasMeta ? meta : undefined }]);
    } catch (err: unknown) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to get AI response.';
      setError(errorMessage);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Sorry, something went wrong: ${errorMessage}` },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Query area */}
      <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={useContext}
                onChange={(e) => setUseContext(e.target.checked)}
                className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                aria-label="Use dashboard context"
              />
              <span className="text-sm font-medium text-gray-700">Use dashboard context</span>
            </label>
            <label className="flex items-center gap-2 text-sm text-gray-600">
              <span>Period:</span>
              <select
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                className="rounded-md border border-gray-300 text-sm py-1 px-2 focus:ring-indigo-500 focus:border-indigo-500"
              >
                <option value={7}>7 days</option>
                <option value={30}>30 days</option>
                <option value={90}>90 days</option>
              </select>
            </label>
          </div>
        </div>
        <div className="p-4">
          <p className="text-xs text-gray-500 mb-2">Suggested questions</p>
          <div className="flex flex-wrap gap-2 mb-4">
            {SUGGESTED_PROMPTS.map((p) => (
              <button
                key={p.label}
                type="button"
                onClick={() => {
                  setInput(p.query);
                  sendMessage(p.query);
                }}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 hover:bg-indigo-50 hover:border-indigo-200 hover:text-indigo-800 transition-colors"
              >
                <Sparkles className="h-3.5 w-3.5 text-indigo-500" />
                {p.label}
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
              placeholder="Ask about sales, finance, logistics, or process flows..."
              className="flex-1 min-w-0 rounded-lg border border-gray-200 text-sm py-2.5 px-3 text-gray-900 placeholder:text-gray-400 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:opacity-60"
              disabled={loading}
              aria-label="Message input"
            />
            <button
              type="button"
              onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
              className="flex-shrink-0 px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center gap-1.5 text-sm font-medium"
              aria-label="Send message"
            >
              {loading ? (
                <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
              ) : (
                <Send className="h-3.5 w-3.5" />
              )}
              Send
            </button>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Answer area */}
        <div className="xl:col-span-2 space-y-4">
          {messages.length === 0 && !loading && (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm p-8 text-center text-gray-500">
              <Sparkles className="h-12 w-12 text-indigo-200 mx-auto mb-3" />
              <p className="text-sm font-medium text-gray-600">Ask a question or pick a suggested prompt above</p>
              <p className="text-xs mt-1 max-w-md mx-auto">
                Use dashboard context for answers based on your outbound invoices, inbound SAT documents, revenue, and process flows.
              </p>
            </div>
          )}
          {messages.length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80">
                <h3 className="text-sm font-semibold text-gray-900">Analysis</h3>
              </div>
              <div className="p-4 space-y-4 max-h-[420px] overflow-y-auto">
                {messages.map((m, i) => (
                  <div
                    key={i}
                    className={m.role === 'user' ? 'text-sm text-gray-600' : ''}
                  >
                    {m.role === 'user' && <p className="font-medium text-gray-500 mb-0.5">You</p>}
                    {m.role === 'assistant' && <p className="font-medium text-indigo-600 mb-0.5">AI</p>}
                    <div className="leading-relaxed whitespace-pre-wrap break-words text-gray-800">{m.content}</div>
                    {/* {m.role === 'assistant' && m.meta && (m.meta.action || m.meta.reason) && (
                      <div className="mt-1 text-xs text-gray-500">
                        <span className="font-semibold">Action</span>{' '}
                        <span className="font-mono">
                          {m.meta.action ?? 'unknown'}
                          {m.meta.reason ? ` — ${m.meta.reason}` : ''}
                        </span>
                      </div>
                    )} */}
                    {/* {m.role === 'assistant' && m.meta && (
                      <div className="mt-2 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs text-gray-700 space-y-2">
                        {m.meta.action && (
                          <div>
                            <span className="font-semibold text-gray-600">Action</span>{' '}
                            <span className="font-mono">
                              {m.meta.action}
                              {m.meta.reason ? ` — ${m.meta.reason}` : ''}
                            </span>
                          </div>
                        )}
                        {m.meta.sql && (
                          <div>
                            <div className="text-gray-500">-- SQL query used</div>
                            <pre className="whitespace-pre-wrap break-words rounded bg-white border border-gray-200 p-2 font-mono text-[11px] text-gray-900">
                              {m.meta.sql}
                            </pre>
                          </div>
                        )}
                        {m.meta.rows_preview?.length ? (
                          <div>
                            <div className="text-gray-500">-- Rows preview</div>
                            <pre className="whitespace-pre-wrap break-words rounded bg-white border border-gray-200 p-2 font-mono text-[11px] text-gray-900">
                              {JSON.stringify(m.meta.rows_preview.slice(0, 10), null, 2)}
                            </pre>
                          </div>
                        ) : null}
                      </div>
                    )} */}
                  </div>
                ))}
                {loading && (
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <div className="h-4 w-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                    Generating analysis...
                  </div>
                )}
              </div>
              <div ref={answerEndRef} />
            </div>
          )}

          {error && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        {/* Data panels */}
        <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden flex flex-col min-h-[320px]">
          <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/80 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-900">Data &amp; flows</h3>
            <button
              type="button"
              onClick={fetchDashboardData}
              disabled={dataLoading}
              className="p-1.5 rounded-md text-gray-500 hover:bg-gray-200 hover:text-gray-700 disabled:opacity-50"
              title="Refresh data"
              aria-label="Refresh data"
            >
              <RefreshCw className={`h-4 w-4 ${dataLoading ? 'animate-spin' : ''}`} />
            </button>
          </div>
          <div className="flex border-b border-gray-100">
            {(['sales', 'finance', 'logistics', 'flow'] as const).map((tab) => (
              <button
                key={tab}
                type="button"
                onClick={() => setDataPanelTab(tab)}
                className={`flex-1 px-3 py-2 text-xs font-medium capitalize transition-colors ${
                  dataPanelTab === tab
                    ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                    : 'text-gray-500 hover:text-gray-700'
                }`}
              >
                {tab === 'sales' && <span className="hidden sm:inline">Sales</span>}
                {tab === 'finance' && <span className="hidden sm:inline">Finance</span>}
                {tab === 'logistics' && <span className="hidden sm:inline">Logistics</span>}
                {tab === 'flow' && <span className="hidden sm:inline">Flow</span>}
              </button>
            ))}
          </div>
          <div className="flex-1 overflow-y-auto p-4 min-h-0">
            {dataLoading ? (
              <div className="flex items-center justify-center py-8 text-gray-400 text-sm">
                <RefreshCw className="h-6 w-6 animate-spin mr-2" />
                Loading...
              </div>
            ) : (
              <>
                {dataPanelTab === 'sales' && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
                      <ArrowDownToLine className="h-3.5 w-3.5" />
                      Top customers (outbound)
                    </h4>
                    {outboundData?.top_customers?.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-gray-500 border-b border-gray-100">
                              <th className="pb-2 pr-2 font-medium">Customer</th>
                              <th className="pb-2 pr-2 font-medium">Currency</th>
                              <th className="pb-2 font-medium">Invoices</th>
                            </tr>
                          </thead>
                          <tbody>
                            {outboundData.top_customers.map((c, i) => (
                              <tr key={i} className="border-b border-gray-50">
                                <td className="py-2 pr-2 text-gray-900">{c.customer_name || c.customer_id}</td>
                                <td className="py-2 pr-2 text-gray-600">{c.currency}</td>
                                <td className="py-2 text-gray-600">{c.count}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400">No outbound customer data in the period.</p>
                    )}
                  </div>
                )}
                {dataPanelTab === 'finance' && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
                      <TrendingUp className="h-3.5 w-3.5" />
                      Revenue
                    </h4>
                    {businessData?.trend && (
                      <div className="rounded-lg bg-gray-50 p-3 text-sm">
                        <p className="text-gray-600">
                          Current period: <span className="font-medium text-gray-900">{Number(businessData.trend.current_period_revenue).toLocaleString()}</span>
                        </p>
                        <p className="text-gray-600">
                          Change: <span className={businessData.trend.revenue_change_pct >= 0 ? 'text-green-600' : 'text-red-600'}>
                            {businessData.trend.revenue_change_pct >= 0 ? '+' : ''}{businessData.trend.revenue_change_pct}%
                          </span>
                        </p>
                      </div>
                    )}
                    {businessData?.revenue_by_customer?.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-gray-500 border-b border-gray-100">
                              <th className="pb-2 pr-2 font-medium">Customer</th>
                              <th className="pb-2 font-medium">Revenue</th>
                            </tr>
                          </thead>
                          <tbody>
                            {businessData.revenue_by_customer.slice(0, 10).map((c, i) => (
                              <tr key={i} className="border-b border-gray-50">
                                <td className="py-2 pr-2 text-gray-900">{c.customer_name || c.customer_id}</td>
                                <td className="py-2 text-gray-600">{Number(c.total_revenue).toLocaleString()}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400">No revenue data in the period.</p>
                    )}
                  </div>
                )}
                {dataPanelTab === 'logistics' && (
                  <div className="space-y-3">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
                      <ArrowUpFromLine className="h-3.5 w-3.5" />
                      Inbound (SAT)
                    </h4>
                    {inboundData?.summary && (
                      <div className="rounded-lg bg-gray-50 p-3 text-sm space-y-1">
                        <p className="text-gray-600">Documents: <span className="font-medium text-gray-900">{inboundData.summary.total_documents}</span></p>
                        <p className="text-gray-600">Merges: <span className="font-medium text-gray-900">{inboundData.summary.merges_total}</span> ({inboundData.summary.merges_sent_to_sap} sent to SAP, {inboundData.summary.merges_pending} pending)</p>
                      </div>
                    )}
                    {inboundData?.top_suppliers?.length ? (
                      <div className="overflow-x-auto">
                        <table className="w-full text-sm">
                          <thead>
                            <tr className="text-left text-gray-500 border-b border-gray-100">
                              <th className="pb-2 pr-2 font-medium">Supplier</th>
                              <th className="pb-2 font-medium">Count</th>
                            </tr>
                          </thead>
                          <tbody>
                            {inboundData.top_suppliers.map((s, i) => (
                              <tr key={i} className="border-b border-gray-50">
                                <td className="py-2 pr-2 text-gray-900">{s.supplier_name || s.supplier_rfc}</td>
                                <td className="py-2 text-gray-600">{s.count}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <p className="text-sm text-gray-400">No inbound supplier data in the period.</p>
                    )}
                  </div>
                )}
                {dataPanelTab === 'flow' && (
                  <div className="space-y-4">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
                      <GitBranch className="h-3.5 w-3.5" />
                      Process flow
                    </h4>
                    {/* Outbound flow */}
                    <div className="border border-gray-200 rounded-lg overflow-hidden">
                      <button
                        type="button"
                        onClick={() => setFlowExpanded(flowExpanded === 'outbound' ? null : 'outbound')}
                        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left text-sm font-medium text-gray-700"
                      >
                        <span className="flex items-center gap-2">
                          <ArrowDownToLine className="h-4 w-4 text-indigo-500" />
                          Outbound
                        </span>
                        {flowExpanded === 'outbound' ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                      {flowExpanded === 'outbound' && outboundData?.funnel && (
                        <div className="px-3 py-3 border-t border-gray-100 space-y-2 text-sm">
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">1</span>
                            <span>Received: <strong>{outboundData.funnel.documents_received}</strong></span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">2</span>
                            <span>Validated: <strong>{outboundData.funnel.validated_success}</strong> ok, <strong>{outboundData.funnel.validated_failed}</strong> failed</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">3</span>
                            <span>Converted: <strong>{outboundData.funnel.converted_success}</strong> ok, <strong>{outboundData.funnel.converted_failed}</strong> failed, <strong>{outboundData.funnel.converted_pending}</strong> pending</span>
                          </div>
                        </div>
                      )}
                    </div>
                    {/* Inbound flow */}
                    <div className="border border-gray-200 rounded-lg overflow-hidden">
                      <button
                        type="button"
                        onClick={() => setFlowExpanded(flowExpanded === 'inbound' ? null : 'inbound')}
                        className="w-full flex items-center justify-between px-3 py-2 bg-gray-50 hover:bg-gray-100 text-left text-sm font-medium text-gray-700"
                      >
                        <span className="flex items-center gap-2">
                          <ArrowUpFromLine className="h-4 w-4 text-indigo-500" />
                          Inbound (SAT)
                        </span>
                        {flowExpanded === 'inbound' ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                      </button>
                      {flowExpanded === 'inbound' && inboundData?.summary && (
                        <div className="px-3 py-3 border-t border-gray-100 space-y-2 text-sm">
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">1</span>
                            <span>SAT documents: <strong>{inboundData.summary.total_documents}</strong></span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">2</span>
                            <span>Merged: <strong>{inboundData.summary.merges_total}</strong></span>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">3</span>
                            <span>Sent to SAP: <strong>{inboundData.summary.merges_sent_to_sap}</strong>, Pending: <strong>{inboundData.summary.merges_pending}</strong></span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
