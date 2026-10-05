'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import { publicApiError } from '@/lib/apiErrors';
import { TrendingUp, TrendingDown, Package, RefreshCw, BarChart3, Users, Sparkles, Globe, MapPin, Layers, Banknote } from 'lucide-react';
import LoadingSpinner from './LoadingSpinner';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';

export default function DashboardV2Business() {
  const [days, setDays] = useState(90);
  const [currency, setCurrency] = useState<string>('');
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await dashboardApi.getV2Business(days, currency || undefined);
      setData(res);
    } catch (err: any) {
      setError(publicApiError(err, 'This business dashboard is temporarily unavailable. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [days, currency]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner />
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-6">
        <p className="text-red-700">{error}</p>
        <button
          onClick={fetchData}
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { products_by_industry, industry_breakdown, quantity_price_analysis, revenue_by_customer, revenue_by_country, revenue_by_currency, customers_by_country, trend, ai_insights } = data;
  const qtyData = (quantity_price_analysis || []).filter((r: any) => r.total_quantity > 0).slice(0, 12);
  const priceData = (quantity_price_analysis || []).filter((r: any) => r.avg_price != null && r.avg_price > 0).sort((a: any, b: any) => (b.avg_price || 0) - (a.avg_price || 0)).slice(0, 12);
  const trendPct = trend?.revenue_change_pct ?? 0;

  return (
    <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-semibold text-gray-900">Business Analytics</h2>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-gray-300 text-sm py-1.5 px-2"
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 12 months</option>
          </select>
          <select
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            className="rounded-md border border-gray-300 text-sm py-1.5 px-2"
            title="Filter by currency"
          >
            <option value="">All currencies</option>
            {(revenue_by_currency || []).map((r: any) => (
              <option key={r.currency} value={r.currency}>{r.currency}</option>
            ))}
          </select>
          <button
            onClick={fetchData}
            className="p-2 border border-gray-300 rounded-md hover:bg-gray-50"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4 text-gray-600" />
          </button>
        </div>
      </div>

      {/* Trend / prognosis */}
      {trend && (
        <div className="border border-gray-200 rounded-lg p-4 bg-gray-50">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Revenue Trend</h3>
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-xs text-gray-500">Current period revenue</p>
              <p className="text-lg font-bold text-gray-900">
                {typeof trend.current_period_revenue === 'number'
                  ? trend.current_period_revenue.toLocaleString(undefined, { minimumFractionDigits: 2 })
                  : trend.current_period_revenue}
              </p>
            </div>
            <div>
              <p className="text-xs text-gray-500">Previous period revenue</p>
              <p className="text-lg font-bold text-gray-700">
                {typeof trend.previous_period_revenue === 'number'
                  ? trend.previous_period_revenue.toLocaleString(undefined, { minimumFractionDigits: 2 })
                  : trend.previous_period_revenue}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {trendPct >= 0 ? (
                <TrendingUp className="h-5 w-5 text-green-600" />
              ) : (
                <TrendingDown className="h-5 w-5 text-red-600" />
              )}
              <span className={trendPct >= 0 ? 'text-green-700 font-semibold' : 'text-red-700 font-semibold'}>
                {trendPct >= 0 ? '+' : ''}{trend.revenue_change_pct}% vs previous period
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Revenue by currency */}
      {(revenue_by_currency?.length ?? 0) > 0 && (
        <div className="border border-gray-200 rounded-xl p-4 md:p-5 bg-white shadow-sm">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Banknote className="h-4 w-4 text-amber-600" /> Revenue by Currency
          </h3>
          <div className="h-44 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={revenue_by_currency.slice(0, 10)}
                layout="vertical"
                margin={{ top: 8, right: 20, left: 56, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => v?.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
                <YAxis type="category" dataKey="currency" width={52} tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(value) =>
                    Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })
                  }
                  labelFormatter={(_, payload) => {
                    const p = payload?.[0]?.payload;
                    return p ? `${p.currency} · ${p.invoice_count} invoices` : _;
                  }}
                  contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
                />
                <Bar dataKey="total_revenue" name="Revenue" fill="#b45309" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-gray-500 mt-2">Revenue mix by invoice currency. Use the currency filter above to drill down.</p>
        </div>
      )}

      {/* Revenue by customer (customer_name from successful invoices) */}
      {(revenue_by_customer?.length ?? 0) > 0 && (
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Users className="h-4 w-4" /> Revenue by Customer
          </h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={revenue_by_customer.slice(0, 15)}
                layout="vertical"
                margin={{ top: 8, right: 24, left: 24, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v) => v?.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
                <YAxis type="category" dataKey="customer_name" width={120} tick={{ fontSize: 10 }} />
                <Tooltip
                  formatter={(value) =>
                    Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })
                  }
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.customer_name ?? _}
                />
                <Bar dataKey="total_revenue" name="Revenue" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-gray-500 mt-2">Customer names from successful validated invoices.</p>
        </div>
      )}

      {/* Geographic section: Revenue by Country + Customers by Country */}
      {((revenue_by_country?.length ?? 0) > 0 || (customers_by_country?.length ?? 0) > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 md:gap-6">
          {/* Revenue by country */}
          {(revenue_by_country?.length ?? 0) > 0 && (
            <div className="border border-gray-200 rounded-xl p-4 md:p-5 bg-white shadow-sm hover:shadow-md transition-shadow">
              <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <Globe className="h-4 w-4 text-emerald-600" /> Revenue by Country
              </h3>
              <div className="h-48 sm:h-56 min-h-[12rem] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={revenue_by_country.slice(0, 12)}
                    layout="vertical"
                    margin={{ top: 8, right: 20, left: 80, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => v?.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
                    <YAxis type="category" dataKey="country_name" width={80} tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(value) =>
                    Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })
                  }
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return _;
                        const label = p.country_name || p.country;
                        const extra = p.country !== p.country_name ? ` (${p.country})` : '';
                        return `${label}${extra}`;
                      }}
                      contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
                    />
                    <Bar dataKey="total_revenue" name="Revenue" fill="#059669" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-gray-500 mt-2">Total revenue per customer country.</p>
            </div>
          )}

          {/* Customers by country histogram */}
          {(customers_by_country?.length ?? 0) > 0 && (
            <div className="border border-gray-200 rounded-xl p-4 md:p-5 bg-white shadow-sm hover:shadow-md transition-shadow">
              <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
                <MapPin className="h-4 w-4 text-amber-600" /> Customers by Country
              </h3>
              <div className="h-48 sm:h-56 min-h-[12rem] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart
                    data={customers_by_country.slice(0, 12)}
                    layout="vertical"
                    margin={{ top: 8, right: 20, left: 80, bottom: 8 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                    <XAxis type="number" tick={{ fontSize: 10 }} allowDecimals={false} tickFormatter={(v) => Number(v)?.toLocaleString()} />
                    <YAxis type="category" dataKey="country_name" width={80} tick={{ fontSize: 10 }} />
                    <Tooltip
                      formatter={(value) => [Number(value ?? 0).toLocaleString(), 'Customers']}
                      labelFormatter={(_, payload) => {
                        const p = payload?.[0]?.payload;
                        if (!p) return _;
                        const label = p.country_name || p.country;
                        const extra = p.country !== p.country_name ? ` (${p.country})` : '';
                        return `${label}${extra}`;
                      }}
                      contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
                    />
                    <Bar dataKey="customer_count" name="Customers" fill="#d97706" radius={[0, 4, 4, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="text-xs text-gray-500 mt-2">Distinct customers per country (histogram).</p>
            </div>
          )}
        </div>
      )}

      {/* Industry breakdown chart */}
      {(industry_breakdown?.length ?? 0) > 0 && (
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <BarChart3 className="h-4 w-4" /> Revenue by Industry
          </h3>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={industry_breakdown}
                layout="vertical"
                margin={{ top: 8, right: 24, left: 80, bottom: 8 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" tick={{ fontSize: 12 }} />
                <YAxis type="category" dataKey="industry" width={76} tick={{ fontSize: 11 }} />
                <Tooltip formatter={(value) =>
                    Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })
                  } />
                <Legend />
                <Bar dataKey="total_revenue" name="Revenue" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Quantity & price: two bar charts */}
      {(quantity_price_analysis?.length ?? 0) > 0 && (
        <div className="space-y-6">
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Layers className="h-4 w-4 text-violet-600" /> Quantity & Price Analysis
          </h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Chart 1: Top products by units sold */}
            {qtyData.length > 0 && (
              <div className="border border-gray-200 rounded-xl p-4 md:p-5 bg-white shadow-sm">
                <h4 className="text-xs font-semibold text-gray-700 mb-1">Units sold by product</h4>
                <p className="text-xs text-gray-500 mb-3">Top products by total quantity sold</p>
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={qtyData} layout="vertical" margin={{ top: 8, right: 20, left: 88, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                      <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => Number(v)?.toLocaleString(undefined, { maximumFractionDigits: 0 })} />
                      <YAxis type="category" dataKey="product_name" width={84} tick={{ fontSize: 10 }} />
                      <Tooltip
                        formatter={(value) => [
                          Number(value ?? 0).toLocaleString(undefined, { maximumFractionDigits: 2 }),
                          'Units sold',
                        ]}
                        labelFormatter={(_, payload) => {
                          const p = payload?.[0]?.payload;
                          return p ? `${p.product_name} · ${p.industry}` : _;
                        }}
                        contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
                      />
                      <Bar dataKey="total_quantity" name="Units sold" fill="#0d9488" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
            {/* Chart 2: Top products by average price */}
            {priceData.length > 0 && (
              <div className="border border-gray-200 rounded-xl p-4 md:p-5 bg-white shadow-sm">
                <h4 className="text-xs font-semibold text-gray-700 mb-1">Average price by product</h4>
                <p className="text-xs text-gray-500 mb-3">Products with highest average selling price</p>
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={priceData} layout="vertical" margin={{ top: 8, right: 20, left: 88, bottom: 8 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" vertical={false} />
                      <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => Number(v)?.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })} />
                      <YAxis type="category" dataKey="product_name" width={84} tick={{ fontSize: 10 }} />
                      <Tooltip
                        formatter={(value) => [
                          Number(value ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 }),
                          'Avg price',
                        ]}
                        labelFormatter={(_, payload) => {
                          const p = payload?.[0]?.payload;
                          return p ? `${p.product_name} · ${p.industry}` : _;
                        }}
                        contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb' }}
                      />
                      <Bar dataKey="avg_price" name="Avg price" fill="#6366f1" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Products by industry table */}
      <div className="border border-gray-200 rounded-lg p-4">
        <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
          <Package className="h-4 w-4" /> Products by Industry
        </h3>
        {(products_by_industry?.length ?? 0) > 0 ? (
          <div className="overflow-x-auto max-h-96 overflow-y-auto">
            <table className="min-w-full divide-y divide-gray-200 text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Product</th>
                  <th className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase">Industry</th>
                  <th className="px-3 py-2 text-center text-xs font-medium text-gray-500 uppercase">Unit</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Invoices</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Revenue</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {products_by_industry.slice(0, 50).map((row: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-900 truncate max-w-xs">{row.product_name}</td>
                    <td className="px-3 py-2 text-gray-700">{row.industry}</td>
                    <td className="px-3 py-2 text-center text-gray-600 font-medium">{row.unit_of_measure ?? '—'}</td>
                    <td className="px-3 py-2 text-right text-gray-700">{row.invoice_count}</td>
                    <td className="px-3 py-2 text-right font-medium text-gray-900">
                      {Number(row.revenue).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {products_by_industry.length > 50 && (
              <p className="text-xs text-gray-500 mt-2 px-3">Showing top 50 of {products_by_industry.length} rows</p>
            )}
          </div>
        ) : (
          <p className="text-sm text-gray-500 py-6 text-center">
            No product-by-industry data yet. Validate outbound invoices with product information to see analytics.
          </p>
        )}
      </div>

      {/* AI Insights */}
      {ai_insights && (
        <div className="border border-indigo-200 rounded-lg p-4 bg-indigo-50/50">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-indigo-600" /> AI Insights
          </h3>
          <div className="space-y-4 text-sm">
            {ai_insights.summary && (
              <p className="text-gray-800 font-medium">{ai_insights.summary}</p>
            )}
            {ai_insights.revenue_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Revenue</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.revenue_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.industry_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Industry</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.industry_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.customer_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Customers</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.customer_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.country_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Geographic</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.country_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.currency_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Currency</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.currency_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.product_insights?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Products</p>
                <ul className="list-disc list-inside text-gray-700 space-y-0.5">
                  {ai_insights.product_insights.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {ai_insights.recommendations?.length > 0 && (
              <div>
                <p className="text-xs font-semibold text-indigo-700 uppercase tracking-wide mb-1">Recommendations</p>
                <ul className="list-disc list-inside text-gray-800 space-y-0.5">
                  {ai_insights.recommendations.map((s: string, i: number) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
