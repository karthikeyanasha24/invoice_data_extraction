'use client';

import { useState, useEffect, useCallback } from 'react';
import { dashboardApi } from '@/lib/api';
import { FileInput, CheckCircle, XCircle, FileOutput, RefreshCw, Users, AlertTriangle, Sparkles, TrendingUp, Package } from 'lucide-react';
import LoadingSpinner from './LoadingSpinner';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  Legend,
  LineChart,
  Line,
  Area,
  AreaChart,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from 'recharts';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];
const FAILED_COLORS = {
  oneTime: '#3b82f6',
  repetitive: '#ef4444',
  primary: '#f59e0b',
  secondary: '#fb923c',
};

export default function DashboardV2Outbound() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [failedAnalysis, setFailedAnalysis] = useState<any>(null);
  const [failedAiInsights, setFailedAiInsights] = useState<any>(null);
  const [failedLoading, setFailedLoading] = useState(false);
  const [failedError, setFailedError] = useState<string | null>(null);
  const [useDemoFailed, setUseDemoFailed] = useState(false);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await dashboardApi.getV2Outbound(days);
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to load outbound data');
    } finally {
      setLoading(false);
    }
  };

  const fetchFailedSection = useCallback(async (demo?: boolean) => {
    setFailedLoading(true);
    setFailedError(null);
    try {
      const [analysis, aiInsights] = await Promise.all([
        dashboardApi.getV2FailedInvoicesAnalysis(days, demo),
        dashboardApi.getV2FailedInvoicesAiInsights(days, demo),
      ]);
      setFailedAnalysis(analysis);
      setFailedAiInsights(aiInsights);
    } catch (err: any) {
      setFailedError(err.message || 'Failed to load failed invoices analysis');
    } finally {
      setFailedLoading(false);
    }
  }, [days]);

  useEffect(() => {
    fetchData();
  }, [days]);

  useEffect(() => {
    if (!loading && data) {
      fetchFailedSection(useDemoFailed);
    }
  }, [loading, data, useDemoFailed, fetchFailedSection]);

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
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { summary, funnel, by_format, top_customers, timeline } = data;
  const formatChart = (by_format || []).map((f: any) => ({ name: f.format, count: f.count, value: f.count }));

  return (
    <div className="space-y-8 pb-8">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Outbound Process</h2>
          <p className="text-sm text-gray-600 mt-1">Document processing and conversion analytics</p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-lg border border-gray-300 text-sm py-2 px-3 bg-white focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button
            onClick={fetchData}
            className="p-2 border border-gray-300 rounded-lg hover:bg-gray-50 hover:border-gray-400 transition-all"
            title="Refresh"
          >
            <RefreshCw className="h-4 w-4 text-gray-600" />
          </button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-white rounded-xl p-5 border-2 border-gray-200 hover:border-blue-300 transition-all shadow-sm hover:shadow-md">
          <div className="flex items-start justify-between mb-3">
            <div className="p-2 bg-blue-50 rounded-lg">
              <FileInput className="h-6 w-6 text-blue-600" />
            </div>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">Received</p>
          <p className="text-3xl font-bold text-gray-900">{funnel?.documents_received ?? 0}</p>
          <p className="text-xs text-gray-500 mt-2">Documents from SAP</p>
        </div>

        <div className="bg-white rounded-xl p-5 border-2 border-gray-200 hover:border-indigo-300 transition-all shadow-sm hover:shadow-md">
          <div className="flex items-start justify-between mb-3">
            <div className="p-2 bg-indigo-50 rounded-lg">
              <Package className="h-6 w-6 text-indigo-600" />
            </div>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">Validated</p>
          <p className="text-3xl font-bold text-gray-900">{summary?.validated_total ?? 0}</p>
          <div className="flex items-center gap-2 mt-2 text-xs">
            <span className="text-green-600 font-medium">{summary?.validated_success ?? 0} ok</span>
            <span className="text-gray-400">•</span>
            <span className="text-red-600 font-medium">{summary?.validated_failed ?? 0} failed</span>
          </div>
        </div>

        <div className="bg-white rounded-xl p-5 border-2 border-green-200 hover:border-green-300 transition-all shadow-sm hover:shadow-md">
          <div className="flex items-start justify-between mb-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <CheckCircle className="h-6 w-6 text-green-600" />
            </div>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">Validation Rate</p>
          <p className="text-3xl font-bold text-green-600">{summary?.validation_success_rate_pct ?? 0}%</p>
          <p className="text-xs text-gray-500 mt-2">Success rate</p>
        </div>

        <div className="bg-white rounded-xl p-5 border-2 border-gray-200 hover:border-purple-300 transition-all shadow-sm hover:shadow-md">
          <div className="flex items-start justify-between mb-3">
            <div className="p-2 bg-purple-50 rounded-lg">
              <FileOutput className="h-6 w-6 text-purple-600" />
            </div>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">Converted</p>
          <p className="text-3xl font-bold text-gray-900">{summary?.converted_success ?? 0}</p>
          <div className="flex items-center gap-2 mt-2 text-xs">
            <span className="text-red-600 font-medium">{summary?.converted_failed ?? 0} failed</span>
            <span className="text-gray-400">•</span>
            <span className="text-amber-600 font-medium">{summary?.converted_pending ?? 0} pending</span>
          </div>
        </div>

        <div className="bg-white rounded-xl p-5 border-2 border-green-200 hover:border-green-300 transition-all shadow-sm hover:shadow-md">
          <div className="flex items-start justify-between mb-3">
            <div className="p-2 bg-green-50 rounded-lg">
              <TrendingUp className="h-6 w-6 text-green-600" />
            </div>
          </div>
          <p className="text-sm font-medium text-gray-600 mb-1">Conversion Rate</p>
          <p className="text-3xl font-bold text-green-600">{summary?.conversion_success_rate_pct ?? 0}%</p>
          <p className="text-xs text-gray-500 mt-2">Success rate</p>
        </div>
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Format Distribution */}
        {formatChart.length > 0 && (
          <div className="bg-white border-2 border-gray-200 rounded-xl p-6 shadow-sm">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Target Format Distribution</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={formatChart}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label={({ name, value, percent }) =>
                      `${name}: ${value} (${((percent ?? 0) * 100).toFixed(0)}%)`}
                    labelLine={{ stroke: '#9ca3af', strokeWidth: 1 }}
                  >
                    {formatChart.map((_: any, i: number) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: '13px' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {/* Top Customers */}
        <div className="bg-white border-2 border-gray-200 rounded-xl p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Users className="h-5 w-5 text-blue-600" /> 
            Top Customers
          </h3>
          {(top_customers?.length ?? 0) > 0 ? (
            <div className="space-y-2 max-h-64 overflow-y-auto pr-2 custom-scrollbar">
              {top_customers.map((c: any, i: number) => (
                <div 
                  key={i} 
                  className="flex items-center justify-between p-3 rounded-lg border border-gray-200 hover:border-blue-300 hover:bg-blue-50 transition-all"
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-gray-900 truncate" title={c.customer_name ?? c.customer_id}>
                      {c.customer_name ?? c.customer_id}
                    </p>
                    <div className="flex items-center gap-2 mt-1">
                      {c.customer_id !== (c.customer_name || c.customer_id) && (
                        <span className="text-xs text-gray-500 font-mono truncate" title={c.customer_id}>
                          {c.customer_id}
                        </span>
                      )}
                      {c.currency && c.currency !== '—' && (
                        <span className="text-xs text-gray-600 bg-gray-100 px-2 py-0.5 rounded">
                          {c.currency}
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="ml-4 text-right">
                    <div className="text-xl font-bold text-blue-600">{c.count}</div>
                    <div className="text-xs text-gray-500">invoices</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center py-12 text-gray-400">
              <Users className="h-12 w-12 mb-2 opacity-50" />
              <p className="text-sm">No customer data in this period</p>
            </div>
          )}
        </div>
      </div>

      {/* Timeline Chart */}
      {timeline?.length > 0 && (
        <div className="bg-white border-2 border-gray-200 rounded-xl p-6 shadow-sm">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Documents Received Over Time</h3>
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={timeline} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorDocs" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis 
                  dataKey="date" 
                  tick={{ fontSize: 12, fill: '#6b7280' }}
                  tickLine={{ stroke: '#e5e7eb' }}
                />
                <YAxis 
                  tick={{ fontSize: 12, fill: '#6b7280' }}
                  tickLine={{ stroke: '#e5e7eb' }}
                />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: 'white', 
                    border: '2px solid #e5e7eb',
                    borderRadius: '8px',
                    padding: '8px 12px'
                  }}
                />
                <Area 
                  type="monotone" 
                  dataKey="documents" 
                  stroke="#3b82f6" 
                  strokeWidth={2}
                  fillOpacity={1} 
                  fill="url(#colorDocs)" 
                  name="Documents"
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Failed Invoices Analysis Section */}
      <div className="bg-white border-2 border-amber-300 rounded-xl p-6 shadow-md">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-6">
          <h3 className="text-xl font-bold text-gray-900 flex items-center gap-3">
            <div className="p-2 bg-amber-100 rounded-lg">
              <AlertTriangle className="h-6 w-6 text-amber-600" />
            </div>
            Failed Invoices Analysis
          </h3>
        </div>

        {failedLoading && (
          <div className="flex items-center justify-center py-12">
            <LoadingSpinner />
          </div>
        )}

        {!failedLoading && failedError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-sm text-red-700">{failedError}</p>
          </div>
        )}

        {!failedLoading && !failedError && failedAnalysis && failedAnalysis.total_failed === 0 && !useDemoFailed && (
          <div className="py-12 text-center">
            <div className="inline-flex items-center justify-center w-16 h-16 bg-green-100 rounded-full mb-4">
              <CheckCircle className="h-8 w-8 text-green-600" />
            </div>
            <p className="text-gray-700 font-medium mb-2">No failed invoices in this period</p>
            <p className="text-sm text-gray-500 mb-6">All invoices processed successfully!</p>
            <button
              type="button"
              onClick={() => setUseDemoFailed(true)}
              className="px-6 py-2.5 bg-amber-500 text-white rounded-lg hover:bg-amber-600 transition-colors font-medium"
            >
              View Sample Analysis
            </button>
          </div>
        )}

        {!failedLoading && !failedError && failedAnalysis && (failedAnalysis.total_failed > 0 || useDemoFailed) && (
          <div className="space-y-6">
            {useDemoFailed && (
              <div className="inline-flex items-center gap-2 bg-amber-100 border border-amber-300 rounded-lg px-3 py-2">
                <Sparkles className="h-4 w-4 text-amber-700" />
                <span className="text-sm font-medium text-amber-800">Viewing sample data (demo mode)</span>
              </div>
            )}

            {/* Stats Grid */}
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              <div className="bg-amber-50 rounded-xl p-4 border-2 border-amber-200">
                <p className="text-sm font-medium text-amber-800 mb-2">Total Failed</p>
                <p className="text-3xl font-bold text-amber-900">{failedAnalysis.total_failed ?? 0}</p>
              </div>
              <div className="bg-blue-50 rounded-xl p-4 border-2 border-blue-200">
                <p className="text-sm font-medium text-blue-800 mb-2">One-Time Failures</p>
                <p className="text-3xl font-bold text-blue-900">{failedAnalysis.one_time_count ?? 0}</p>
              </div>
              <div className="bg-red-50 rounded-xl p-4 border-2 border-red-200">
                <p className="text-sm font-medium text-red-800 mb-2">Repetitive Failures</p>
                <p className="text-3xl font-bold text-red-900">{failedAnalysis.repetitive_count ?? 0}</p>
              </div>
              <div className="bg-purple-50 rounded-xl p-4 border-2 border-purple-200">
                <p className="text-sm font-medium text-purple-800 mb-2">Revenue at Risk</p>
                <div className="text-sm font-bold text-purple-900 space-y-1">
                  {failedAnalysis.revenue_loss_by_currency && Object.keys(failedAnalysis.revenue_loss_by_currency).length > 0
                    ? Object.entries(failedAnalysis.revenue_loss_by_currency).map(([cur, amt]: [string, any]) => (
                        <div key={cur} className="text-lg">
                          {cur} {Number(amt).toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                      ))
                    : <div className="text-2xl">—</div>}
                </div>
              </div>
            </div>

            {/* Charts Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Failure Reasons Chart */}
              {failedAnalysis.failure_reasons?.length > 0 && (
                <div className="bg-white rounded-xl p-5 border-2 border-gray-200 shadow-sm">
                  <h4 className="text-base font-semibold text-gray-900 mb-4">Top Failure Reasons</h4>
                  <div className="h-80">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={failedAnalysis.failure_reasons.slice(0, 8)}
                        layout="horizontal"
                        margin={{ top: 5, right: 20, left: 10, bottom: 60 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                        <XAxis 
                          type="category" 
                          dataKey="reason" 
                          angle={-45}
                          textAnchor="end"
                          height={100}
                          tick={{ fontSize: 11, fill: '#6b7280' }}
                          interval={0}
                        />
                        <YAxis 
                          type="number" 
                          tick={{ fontSize: 12, fill: '#6b7280' }}
                        />
                        <Tooltip 
                          contentStyle={{ 
                            backgroundColor: 'white', 
                            border: '2px solid #e5e7eb',
                            borderRadius: '8px'
                          }}
                        />
                        <Bar 
                          dataKey="count" 
                          fill="#f59e0b" 
                          name="Failures" 
                          radius={[8, 8, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              )}

              {/* One-time vs Repetitive */}
              <div className="bg-white rounded-xl p-5 border-2 border-gray-200 shadow-sm">
                <h4 className="text-base font-semibold text-gray-900 mb-4">Failure Classification</h4>
                <div className="h-80">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={[
                          { name: 'One-time', value: failedAnalysis.one_time_count ?? 0 },
                          { name: 'Repetitive', value: failedAnalysis.repetitive_count ?? 0 },
                        ]}
                        dataKey="value"
                        nameKey="name"
                        cx="50%"
                        cy="50%"
                        outerRadius={100}
                        label={({ name, value, percent }) =>
                      `${name}: ${value} (${((percent ?? 0) * 100).toFixed(0)}%)`}
                        labelLine={{ stroke: '#9ca3af', strokeWidth: 1 }}
                      >
                        <Cell fill={FAILED_COLORS.oneTime} />
                        <Cell fill={FAILED_COLORS.repetitive} />
                      </Pie>
                      <Tooltip />
                      <Legend wrapperStyle={{ fontSize: '14px' }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </div>
            </div>

            {/* Revenue Loss by Currency */}
            {failedAnalysis.revenue_loss_by_currency && Object.keys(failedAnalysis.revenue_loss_by_currency).length > 0 && (
              <div className="bg-white rounded-xl p-5 border-2 border-gray-200 shadow-sm">
                <h4 className="text-base font-semibold text-gray-900 mb-4">Revenue at Risk by Currency</h4>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={Object.entries(failedAnalysis.revenue_loss_by_currency).map(([currency, amount]) => ({
                        currency,
                        amount: Number(amount),
                      }))}
                      margin={{ top: 10, right: 20, left: 10, bottom: 10 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis 
                        dataKey="currency" 
                        tick={{ fontSize: 13, fill: '#6b7280', fontWeight: 600 }}
                      />
                      <YAxis 
                        tick={{ fontSize: 12, fill: '#6b7280' }}
                      />
                      <Tooltip 
                        formatter={(v) =>
                          Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2 })
                        }
                        contentStyle={{ 
                          backgroundColor: 'white', 
                          border: '2px solid #e5e7eb',
                          borderRadius: '8px'
                        }}
                      />
                      <Bar 
                        dataKey="amount" 
                        fill="#f59e0b" 
                        name="Amount at Risk" 
                        radius={[8, 8, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}

            {/* AI Insights */}
            {failedAiInsights && (
              <div className="bg-indigo-50 border-2 border-indigo-300 rounded-xl p-6 shadow-sm">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-5">
                  <h4 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                    <Sparkles className="h-5 w-5 text-indigo-600" /> 
                    AI-Powered Insights
                  </h4>
                  <button
                    type="button"
                    onClick={() => fetchFailedSection(useDemoFailed)}
                    className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors text-sm font-medium"
                    title="Refresh insights"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Refresh
                  </button>
                </div>
                
                <div className="space-y-5">
                  {failedAiInsights.summary && (
                    <div className="bg-white rounded-lg p-4 border border-indigo-200">
                      <p className="text-gray-800 font-medium leading-relaxed">{failedAiInsights.summary}</p>
                    </div>
                  )}

                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
                    {failedAiInsights.insights?.length > 0 && (
                      <div className="bg-white rounded-lg p-5 border border-indigo-200">
                        <p className="text-xs font-bold text-indigo-700 uppercase tracking-wider mb-3">Key Insights</p>
                        <ul className="space-y-2">
                          {failedAiInsights.insights.map((s: string, i: number) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                              <span className="text-indigo-500 mt-1">•</span>
                              <span>{s}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {failedAiInsights.recommendations?.length > 0 && (
                      <div className="bg-white rounded-lg p-5 border border-indigo-200">
                        <p className="text-xs font-bold text-indigo-700 uppercase tracking-wider mb-3">Recommendations</p>
                        <ul className="space-y-2">
                          {failedAiInsights.recommendations.map((s: string, i: number) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-800">
                              <span className="text-green-600 mt-1">✓</span>
                              <span>{s}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  {failedAiInsights.root_causes?.length > 0 && (
                    <div className="bg-white rounded-lg p-5 border border-indigo-200">
                      <p className="text-xs font-bold text-gray-700 uppercase tracking-wider mb-3">Root Causes</p>
                      <ul className="space-y-2">
                        {failedAiInsights.root_causes.map((s: string, i: number) => (
                          <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                            <span className="text-amber-500 mt-1">⚠</span>
                            <span>{s}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {failedAiInsights.revenue_impact_note && (
                    <div className="bg-purple-50 rounded-lg p-4 border border-purple-200">
                      <p className="text-sm text-purple-900 italic">{failedAiInsights.revenue_impact_note}</p>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      <style jsx>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: #f3f4f6;
          border-radius: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: #d1d5db;
          border-radius: 3px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: #9ca3af;
        }
      `}</style>
    </div>
  );
}