'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import { TrendingUp, TrendingDown, Package, RefreshCw, BarChart3, Users, Sparkles } from 'lucide-react';
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
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await dashboardApi.getV2Business(days);
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to load business data');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [days]);

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

  const { products_by_industry, industry_breakdown, revenue_by_customer, trend, ai_insights } = data;
  const trendPct = trend?.revenue_change_pct ?? 0;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-semibold text-gray-900">Business Analytics</h2>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-gray-300 text-sm py-1.5 px-2"
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={365}>Last 12 months</option>
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

      {/* Revenue by customer (customer_id = RFC) */}
      {(revenue_by_customer?.length ?? 0) > 0 && (
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Users className="h-4 w-4" /> Revenue by Customer (RFC)
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
                <YAxis type="category" dataKey="customer_id" width={120} tick={{ fontSize: 10 }} />
                <Tooltip
                  formatter={(value: number) => value?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                  labelFormatter={(_, payload) => payload?.[0]?.payload?.customer_name ?? _}
                />
                <Bar dataKey="total_revenue" name="Revenue" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-gray-500 mt-2">Customer ID is RFC (tax id). From successful validated invoices.</p>
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
                <Tooltip formatter={(value: number) => value?.toLocaleString(undefined, { minimumFractionDigits: 2 })} />
                <Legend />
                <Bar dataKey="total_revenue" name="Revenue" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
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
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Invoices</th>
                  <th className="px-3 py-2 text-right text-xs font-medium text-gray-500 uppercase">Revenue</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {products_by_industry.slice(0, 50).map((row: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="px-3 py-2 text-gray-900 truncate max-w-xs">{row.product_name}</td>
                    <td className="px-3 py-2 text-gray-700">{row.industry}</td>
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
