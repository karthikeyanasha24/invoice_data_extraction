'use client';

import { useState, useEffect, useCallback } from 'react';
import { dashboardApi } from '@/lib/api';
import { Users, RefreshCw, GitCompare, Globe, MessageCircle, Send, X } from 'lucide-react';
import LoadingSpinner from './LoadingSpinner';
import {
  Treemap,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';

type Customer = {
  customer_id: string | null;
  customer_name: string;
  customer_country: string | null;
  industry?: string | null;
  currencies?: { currency: string; revenue: number }[];
  invoice_count: number;
  total_revenue: number;
  products: { product_name: string; revenue: number; quantity: number; unit: string }[];
};

const MAP_COLORS = [
  '#6366f1', '#8b5cf6', '#a78bfa',
  '#3b82f6', '#60a5fa', '#93c5fd',
  '#06b6d4', '#22d3ee', '#67e8f9',
  '#10b981', '#34d399',
];

export default function DashboardV2CustomerComparison() {
  const [days, setDays] = useState(90);
  const [currency, setCurrency] = useState<string>('');
  const [compareMode, setCompareMode] = useState(false);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [compareA, setCompareA] = useState<Customer | null>(null);
  const [compareB, setCompareB] = useState<Customer | null>(null);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [chatMessages, setChatMessages] = useState<{ role: 'user' | 'assistant'; content: string }[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatLoading, setChatLoading] = useState(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await dashboardApi.getV2CustomerComparison(days, currency || undefined);
      setData(res);
      setSelectedCustomer(null);
      setCompareA(null);
      setCompareB(null);
      setChatMessages([]);
    } catch (err: any) {
      setError(err.message || 'Failed to load customer comparison data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchData(); }, [days, currency]);

  const fetchAiSummary = useCallback(async () => {
    if (!compareA || !compareB) return;
    setAiLoading(true);
    try {
      const res = await dashboardApi.postCustomerComparisonChat(
        'Provide a 2-3 sentence summary comparing these two customers: their revenue, geography, industry, and product mix.',
        compareA, compareB, []
      );
      setChatMessages([{ role: 'assistant', content: res.reply || '' }]);
    } catch {
      setChatMessages([{ role: 'assistant', content: 'Unable to generate summary.' }]);
    } finally {
      setAiLoading(false);
    }
  }, [compareA, compareB]);

  useEffect(() => {
    if (compareA && compareB && compareA !== compareB) {
      setChatMessages([]);
      fetchAiSummary();
    } else {
      setChatMessages([]);
    }
  }, [compareA, compareB]);

  const sendChatMessage = async () => {
    const msg = chatInput.trim();
    if (!msg || !compareA || !compareB) return;
    setChatInput('');
    const newMessages = [...chatMessages, { role: 'user' as const, content: msg }];
    setChatMessages(newMessages);
    setChatLoading(true);
    try {
      const res = await dashboardApi.postCustomerComparisonChat(msg, compareA, compareB, chatMessages);
      setChatMessages([...newMessages, { role: 'assistant', content: res.reply || '' }]);
    } catch {
      setChatMessages([...newMessages, { role: 'assistant', content: 'Sorry, I could not process your question.' }]);
    } finally {
      setChatLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-2xl bg-red-50 border border-red-200 p-8 text-center">
        <p className="text-red-700 mb-4">{error}</p>
        <button onClick={fetchData} className="px-5 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors text-sm font-medium">
          Try Again
        </button>
      </div>
    );
  }

  if (!data) return null;

  const customers: Customer[] = data.customers || [];
  const revenueByCurrency = data.revenue_by_currency || [];
  const revenueByCountry = data.revenue_by_country || [];

  const mapData = revenueByCountry
    .filter((r: any) => r.country && r.country !== 'Unknown')
    .map((r: any, i: number) => ({
      name: r.country_name || r.country,
      size: r.total_revenue || 0,
      value: r.total_revenue || 0,
      country: r.country,
      invoices: r.invoice_count,
      fill: MAP_COLORS[i % MAP_COLORS.length],
    }))
    .filter((d: any) => d.size > 0);

  const treemapData = mapData.length > 0 ? [{ name: 'Countries', children: mapData }] : [];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">Customer Comparison</h2>
          <p className="text-xs text-gray-500 mt-0.5">Analyze and compare customer revenue, products, and geography</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-gray-200 bg-white text-sm py-1.5 px-3 text-gray-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 12 months</option>
          </select>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="rounded-lg border border-gray-200 bg-white text-sm py-1.5 px-3 text-gray-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">All currencies</option>
            {revenueByCurrency.map((r: any) => (
              <option key={r.currency} value={r.currency}>{r.currency}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => { setCompareMode(!compareMode); setSelectedCustomer(null); }}
            className={`flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-all ${
              compareMode
                ? 'border-indigo-500 bg-indigo-600 text-white shadow-sm'
                : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50 shadow-sm'
            }`}
          >
            <GitCompare className="h-3.5 w-3.5" /> Compare
          </button>
          <button
            onClick={fetchData}
            className="p-1.5 border border-gray-200 bg-white rounded-lg hover:bg-gray-50 shadow-sm transition-colors"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4 text-gray-500" />
          </button>
        </div>
      </div>

      {customers.length === 0 ? (
        <div className="rounded-2xl border border-gray-200 bg-gray-50 p-16 text-center">
          <Users className="h-10 w-10 mx-auto mb-3 text-gray-300" />
          <p className="text-gray-500 text-sm">No customer data yet. Validate invoices with customer and product information to see comparisons.</p>
        </div>
      ) : (
        <>
          {/* Revenue by Country Treemap */}
          <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="p-1.5 bg-indigo-50 rounded-lg">
                  <Globe className="h-4 w-4 text-indigo-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">Revenue by Country</h3>
                  <p className="text-xs text-gray-400">Area size represents revenue — hover for details</p>
                </div>
              </div>
            </div>
            <div className="p-4">
              {treemapData.length > 0 ? (
                <div className="h-56 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <Treemap data={treemapData} dataKey="size" stroke="#fff" content={<CustomContent />}>
                      <Tooltip content={<MapTooltip />} />
                    </Treemap>
                  </ResponsiveContainer>
                </div>
              ) : (
                <div className="h-56 flex items-center justify-center">
                  <p className="text-sm text-gray-400">No country data available</p>
                </div>
              )}
            </div>
          </div>

          {/* Customer Cards Grid */}
          {!compareMode && (
            <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center gap-2">
                <div className="p-1.5 bg-blue-50 rounded-lg">
                  <Users className="h-4 w-4 text-blue-600" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">Customers</h3>
                  <p className="text-xs text-gray-400">Click a customer to view product breakdown</p>
                </div>
              </div>
              <div className="p-4">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
                  {customers.map((c, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => setSelectedCustomer(selectedCustomer?.customer_name === c.customer_name ? null : c)}
                      className={`text-left rounded-xl border p-3.5 transition-all hover:shadow-md group ${
                        selectedCustomer?.customer_name === c.customer_name
                          ? 'border-indigo-400 bg-indigo-50 shadow-sm'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      <div className="flex items-start justify-between mb-2">
                        <div
                          className="w-7 h-7 rounded-lg flex items-center justify-center text-white text-xs font-bold flex-shrink-0"
                          style={{ backgroundColor: MAP_COLORS[i % MAP_COLORS.length] }}
                        >
                          {c.customer_name.charAt(0).toUpperCase()}
                        </div>
                        {c.customer_country && (
                          <span className="text-xs text-gray-400 font-medium">{c.customer_country}</span>
                        )}
                      </div>
                      <p className="text-sm font-semibold text-gray-900 leading-tight mb-1 line-clamp-2">{c.customer_name}</p>
                      {c.industry && <p className="text-xs text-gray-400 mb-2 truncate">{c.industry}</p>}
                      <div className="flex items-center justify-between mt-auto">
                        <span className="text-sm font-bold text-gray-900">
                          {c.total_revenue.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </span>
                        <span className="text-xs text-gray-400">{c.invoice_count} inv.</span>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Single customer product breakdown */}
          {!compareMode && selectedCustomer && (
            <div className="rounded-2xl border border-indigo-200 bg-white shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-indigo-100 flex items-center justify-between bg-indigo-50/40">
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">
                    {selectedCustomer.customer_name} — Product Breakdown
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {selectedCustomer.total_revenue.toLocaleString(undefined, { minimumFractionDigits: 2 })} total
                    · {selectedCustomer.invoice_count} invoice(s)
                    {selectedCustomer.customer_country && ` · ${selectedCustomer.customer_country}`}
                    {selectedCustomer.industry && ` · ${selectedCustomer.industry}`}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setSelectedCustomer(null)}
                  className="p-1.5 rounded-lg hover:bg-indigo-100 transition-colors text-gray-400 hover:text-gray-600"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="p-4 overflow-x-auto">
                <table className="w-full text-sm min-w-[400px]">
                  <thead>
                    <tr className="border-b border-gray-100">
                      <th className="pb-2 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Product</th>
                      <th className="pb-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Qty</th>
                      <th className="pb-2 text-center text-xs font-semibold text-gray-400 uppercase tracking-wide">Unit</th>
                      <th className="pb-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Revenue</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {selectedCustomer.products.map((p, i) => (
                      <tr key={i} className="hover:bg-gray-50 transition-colors">
                        <td className="py-2.5 text-gray-800 font-medium">{p.product_name}</td>
                        <td className="py-2.5 text-right text-gray-600">{Number(p.quantity).toLocaleString(undefined, { maximumFractionDigits: 2 })}</td>
                        <td className="py-2.5 text-center text-gray-500 text-xs">{p.unit}</td>
                        <td className="py-2.5 text-right font-semibold text-gray-900">{Number(p.revenue).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Compare Mode */}
          {compareMode && (
            <div className="space-y-5">
              {/* Selectors */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Customer A */}
                <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60">
                    <h3 className="text-sm font-semibold text-gray-700">Customer A</h3>
                  </div>
                  <div className="p-4 space-y-3">
                    <select
                      value={compareA ? customers.indexOf(compareA) : ''}
                      onChange={(e) => {
                        const idx = parseInt(e.target.value, 10);
                        setCompareA(idx >= 0 && customers[idx] ? customers[idx] : null);
                      }}
                      className="w-full rounded-lg border border-gray-200 text-sm py-2 px-3 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      <option value="">Select customer...</option>
                      {customers.map((c, i) => (
                        <option key={i} value={i}>{c.customer_name}</option>
                      ))}
                    </select>
                    {compareA && <ComparisonCard customer={compareA} color={MAP_COLORS[0]} />}
                  </div>
                </div>

                {/* Customer B */}
                <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100 bg-gray-50/60">
                    <h3 className="text-sm font-semibold text-gray-700">Customer B</h3>
                  </div>
                  <div className="p-4 space-y-3">
                    <select
                      value={compareB ? customers.indexOf(compareB) : ''}
                      onChange={(e) => {
                        const idx = parseInt(e.target.value, 10);
                        setCompareB(idx >= 0 && customers[idx] ? customers[idx] : null);
                      }}
                      className="w-full rounded-lg border border-gray-200 text-sm py-2 px-3 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      <option value="">Select customer...</option>
                      {customers.map((c, i) => (
                        <option key={i} value={i}>{c.customer_name}</option>
                      ))}
                    </select>
                    {compareB && <ComparisonCard customer={compareB} color={MAP_COLORS[3]} />}
                  </div>
                </div>
              </div>

              {/* AI Chat */}
              {compareA && compareB && (
                <div className="rounded-2xl border border-indigo-200 bg-white shadow-sm overflow-hidden">
                  <div className="px-5 py-4 border-b border-indigo-100 bg-gradient-to-r from-indigo-50 to-purple-50 flex items-center gap-2">
                    <div className="p-1.5 bg-indigo-100 rounded-lg">
                      <MessageCircle className="h-4 w-4 text-indigo-600" />
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-gray-900">AI Comparison Assistant</h3>
                      <p className="text-xs text-gray-500">Ask anything about these two customers</p>
                    </div>
                  </div>
                  <div className="p-4">
                    {aiLoading ? (
                      <div className="flex items-center gap-2 py-4 text-sm text-gray-500">
                        <div className="h-4 w-4 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
                        Generating analysis...
                      </div>
                    ) : (
                      <div className="space-y-3">
                        {/* Messages */}
                        <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                          {chatMessages.map((m, i) => (
                            <div
                              key={i}
                              className={`text-sm rounded-xl px-4 py-3 ${
                                m.role === 'user'
                                  ? 'bg-gray-100 ml-8 text-gray-800'
                                  : 'bg-indigo-50 border border-indigo-100 mr-8 text-gray-800'
                              }`}
                            >
                              <p className="text-xs font-semibold mb-1 text-gray-400">
                                {m.role === 'user' ? 'You' : '✦ AI'}
                              </p>
                              <p className="leading-relaxed">{m.content}</p>
                            </div>
                          ))}
                        </div>
                        {/* Input */}
                        <div className="flex gap-2 pt-1">
                          <input
                            type="text"
                            value={chatInput}
                            onChange={(e) => setChatInput(e.target.value)}
                            onKeyDown={(e) => e.key === 'Enter' && !chatLoading && sendChatMessage()}
                            placeholder="Ask about revenue, products, geography..."
                            className="flex-1 min-w-0 rounded-lg border border-gray-200 text-sm py-2 px-3 focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-60"
                            disabled={chatLoading}
                          />
                          <button
                            onClick={sendChatMessage}
                            disabled={chatLoading || !chatInput.trim()}
                            className="flex-shrink-0 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 transition-colors flex items-center gap-1.5 text-sm font-medium"
                          >
                            {chatLoading ? (
                              <div className="h-4 w-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                            ) : (
                              <Send className="h-3.5 w-3.5" />
                            )}
                            Send
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Product Tables */}
              {(compareA || compareB) && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {compareA && (
                    <ProductTable customer={compareA} label="Customer A — Products" color={MAP_COLORS[0]} />
                  )}
                  {compareB && (
                    <ProductTable customer={compareB} label="Customer B — Products" color={MAP_COLORS[3]} />
                  )}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function ComparisonCard({ customer, color }: { customer: Customer; color: string }) {
  return (
    <div className="rounded-xl border border-gray-100 bg-gray-50 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-white text-sm font-bold flex-shrink-0"
          style={{ backgroundColor: color }}
        >
          {customer.customer_name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">{customer.customer_name}</p>
          {customer.industry && <p className="text-xs text-gray-400 truncate">{customer.industry}</p>}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Revenue" value={customer.total_revenue.toLocaleString(undefined, { minimumFractionDigits: 2 })} />
        <Stat label="Invoices" value={String(customer.invoice_count)} />
        <Stat label="Country" value={customer.customer_country || '—'} />
        <Stat label="Currencies" value={(customer.currencies || []).map(c => c.currency).join(', ') || '—'} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-white rounded-lg px-3 py-2 border border-gray-100">
      <p className="text-xs text-gray-400 mb-0.5">{label}</p>
      <p className="text-sm font-semibold text-gray-900 truncate">{value}</p>
    </div>
  );
}

function ProductTable({ customer, label, color }: { customer: Customer; label: string; color: string }) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center gap-2">
        <div className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: color }} />
        <h4 className="text-xs font-semibold text-gray-700">{label}</h4>
      </div>
      <div className="overflow-x-auto">
        <div className="max-h-52 overflow-y-auto">
          <table className="w-full text-sm min-w-[260px]">
            <thead className="sticky top-0 bg-gray-50 z-10">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">Product</th>
                <th className="px-4 py-2 text-right text-xs font-semibold text-gray-400 uppercase tracking-wide">Revenue</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {customer.products.map((p, i) => (
                <tr key={i} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-2.5 text-gray-800 font-medium truncate max-w-[180px]">{p.product_name}</td>
                  <td className="px-4 py-2.5 text-right text-gray-900 font-semibold">{Number(p.revenue).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function CustomContent(props: any) {
  const { x, y, width, height, name, fill, size, value } = props;
  if (!width || width < 30 || !height || height < 25) return null;
  const val = size ?? value ?? 0;
  const showLabel = width > 60 && height > 40;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill || '#6366f1'} stroke="#fff" strokeWidth={2} rx={4} />
      {showLabel && (
        <>
          <text x={x + width / 2} y={y + height / 2 - 6} textAnchor="middle" fill="#fff" fontSize={11} fontWeight={600}>{name}</text>
          <text x={x + width / 2} y={y + height / 2 + 9} textAnchor="middle" fill="rgba(255,255,255,0.8)" fontSize={10}>
            {Number(val).toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </text>
        </>
      )}
    </g>
  );
}

function MapTooltip(props: any) {
  const { active, payload } = props;
  if (!active || !payload?.length) return null;
  const p = payload[0]?.payload;
  if (!p) return null;
  return (
    <div className="bg-white px-3 py-2 shadow-lg rounded-xl border border-gray-200 text-sm">
      <p className="font-semibold text-gray-900">{p.name}</p>
      <p className="text-gray-600 text-xs mt-0.5">Revenue: {Number(p.size).toLocaleString(undefined, { minimumFractionDigits: 2 })}</p>
      <p className="text-gray-600 text-xs">Invoices: {p.invoices ?? 0}</p>
    </div>
  );
}