'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { dashboardApi } from '@/lib/api';
import { DashboardStatistics, AIInsights } from '@/types';
import DashboardTabs from './DashboardTabs';
import DashboardOperations from './DashboardOperations';
import {
  TrendingUp,
  TrendingDown,
  CheckCircle,
  XCircle,
  FileText,
  Activity,
  Lightbulb,
  RefreshCw,
  AlertTriangle
} from 'lucide-react';
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from 'recharts';
import LoadingSpinner from './LoadingSpinner';

// Color palette
const COLORS = {
  success: '#10b981',
  failed: '#ef4444',
  primary: '#3b82f6',
  secondary: '#8b5cf6',
  warning: '#f59e0b',
  info: '#06b6d4',
};

const CHART_COLORS = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4'];

export default function DashboardNew() {
  const { user, handleAuthError } = useAuth();
  const [activeTab, setActiveTab] = useState('overview');
  const [statistics, setStatistics] = useState<DashboardStatistics | null>(null);
  const [aiInsights, setAIInsights] = useState<AIInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState(30);

  useEffect(() => {
    fetchDashboardData();
  }, [timeRange]);

  const fetchDashboardData = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await dashboardApi.getStatistics(timeRange);
      setStatistics(data);
    } catch (err: any) {
      console.error('Failed to fetch dashboard data:', err);
      setError(err.message || 'Failed to load dashboard data');
      if (err.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  };

  const fetchAIInsights = async () => {
    try {
      setInsightsLoading(true);
      const data = await dashboardApi.getAIInsights();
      setAIInsights(data);
    } catch (err: any) {
      console.error('Failed to fetch AI insights:', err);
      // Don't set error state here, just log it
    } finally {
      setInsightsLoading(false);
    }
  };

  useEffect(() => {
    // Fetch AI insights if we have failed invoices
    if (statistics && statistics.overview.failed > 0 && !aiInsights) {
      fetchAIInsights();
    }
  }, [statistics]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner size="lg" text="Loading dashboard..." />
      </div>
    );
  }

  if (error || !statistics) {
    return (
      <div className="flex items-center justify-center py-20">
        <div className="text-center">
          <AlertTriangle className="h-12 w-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-gray-900 mb-2">Failed to Load Dashboard</h2>
          <p className="text-gray-600 mb-4">{error || 'Unknown error occurred'}</p>
          <button
            onClick={fetchDashboardData}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const { overview, timeline, format_distribution, request_type_distribution } = statistics;

  return (
    <div className="space-y-0">
      {/* Tabs Navigation */}
      <DashboardTabs activeTab={activeTab} onTabChange={setActiveTab} />
      
      {/* Tab Content */}
      <div className="bg-gray-50">
        {activeTab === 'overview' && (
          <div className="space-y-6 p-6">
            {/* Time Range Selector and Refresh */}
            <div className="flex items-center justify-end gap-3">
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
            className="px-4 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <button
            onClick={fetchDashboardData}
            className="p-2 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            title="Refresh"
          >
            <RefreshCw className="h-5 w-5 text-gray-600" />
          </button>
        </div>

        {/* Overview Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
          {/* Total Invoices */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Total Invoices</p>
                <p className="text-3xl font-bold text-gray-900 mt-2">{overview.total}</p>
              </div>
              <div className="p-3 bg-blue-100 rounded-full">
                <FileText className="h-6 w-6 text-blue-600" />
              </div>
            </div>
          </div>

          {/* Successful */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Successful</p>
                <p className="text-3xl font-bold text-green-600 mt-2">{overview.successful}</p>
              </div>
              <div className="p-3 bg-green-100 rounded-full">
                <CheckCircle className="h-6 w-6 text-green-600" />
              </div>
            </div>
          </div>

          {/* Failed */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Failed</p>
                <p className="text-3xl font-bold text-red-600 mt-2">{overview.failed}</p>
              </div>
              <div className="p-3 bg-red-100 rounded-full">
                <XCircle className="h-6 w-6 text-red-600" />
              </div>
            </div>
          </div>

          {/* Success Rate */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Success Rate</p>
                <p className="text-3xl font-bold text-gray-900 mt-2">{overview.success_rate}%</p>
              </div>
              <div className={`p-3 rounded-full ${overview.success_rate >= 80 ? 'bg-green-100' : 'bg-yellow-100'}`}>
                {overview.success_rate >= 80 ? (
                  <TrendingUp className="h-6 w-6 text-green-600" />
                ) : (
                  <TrendingDown className="h-6 w-6 text-yellow-600" />
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Timeline Chart */}
        <div className="bg-white rounded-lg shadow p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4">Invoice Processing Timeline</h2>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={timeline}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="date"
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                />
                <YAxis
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '0.5rem',
                  }}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="successful"
                  stroke={COLORS.success}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                  name="Successful"
                />
                <Line
                  type="monotone"
                  dataKey="failed"
                  stroke={COLORS.failed}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  activeDot={{ r: 6 }}
                  name="Failed"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Charts Row */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Format Distribution */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Format Distribution</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={format_distribution}
                    dataKey="count"
                    nameKey="format"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    label={({ format, count }) => `${format}: ${count}`}
                  >
                    {format_distribution.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Request Source */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Request Source</h2>
            <div className="h-80">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={request_type_distribution}
                    dataKey="count"
                    nameKey="type"
                    cx="50%"
                    cy="50%"
                    outerRadius={100}
                    label={({ type, count }) => `${type === 'api' ? 'API/ERP' : 'Web'}: ${count}`}
                  >
                    {request_type_distribution.map((entry, index) => (
                      <Cell
                        key={`cell-${index}`}
                        fill={entry.type === 'api' ? COLORS.warning : COLORS.primary}
                      />
                    ))}
                  </Pie>
                  <Tooltip 
                    formatter={(value: any, name: string) => [value, name === 'api' ? 'API/ERP' : 'Web Upload']}
                  />
                  <Legend 
                    formatter={(value: string) => value === 'api' ? 'API/ERP' : 'Web Upload'}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* AI Insights - Full Width */}
        <div className="bg-gradient-to-br from-purple-50 to-blue-50 rounded-lg shadow p-6">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Lightbulb className="h-5 w-5 text-purple-600" />
                <h2 className="text-lg font-semibold text-gray-900">AI Insights</h2>
              </div>
              {!aiInsights && !insightsLoading && overview.failed > 0 && (
                <button
                  onClick={fetchAIInsights}
                  className="px-3 py-1 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700"
                >
                  Generate Insights
                </button>
              )}
            </div>

            {insightsLoading ? (
              <div className="flex items-center justify-center py-8">
                <LoadingSpinner size="md" text="Analyzing..." />
              </div>
            ) : aiInsights ? (
              <div className="space-y-4">
                {/* Summary - Full Width */}
                <div className="bg-white rounded-lg p-4">
                  <h3 className="font-semibold text-gray-900 mb-2">📊 Summary</h3>
                  <p className="text-sm text-gray-700">{aiInsights.summary}</p>
                  <div className="mt-3 flex items-center gap-4 text-xs text-gray-500">
                    <span>Total Failed: <strong>{aiInsights.total_failed}</strong></span>
                    <span>•</span>
                    <span>Analyzed: {new Date(aiInsights.analyzed_at).toLocaleString()}</span>
                  </div>
                </div>

                {/* Grid Layout for Insights and Recommendations */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {aiInsights.insights.length > 0 && (
                    <div className="bg-white rounded-lg p-4">
                      <h3 className="font-semibold text-gray-900 mb-3">💡 Key Insights</h3>
                      <ul className="space-y-2">
                        {aiInsights.insights.map((insight, index) => (
                          <li key={index} className="flex items-start gap-2 text-sm text-gray-700">
                            <span className="text-blue-600 font-bold mt-0.5">•</span>
                            <span>{insight}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {aiInsights.recommendations.length > 0 && (
                    <div className="bg-white rounded-lg p-4">
                      <h3 className="font-semibold text-gray-900 mb-3">✅ Recommendations</h3>
                      <ul className="space-y-2">
                        {aiInsights.recommendations.map((rec, index) => (
                          <li key={index} className="flex items-start gap-2 text-sm text-gray-700">
                            <span className="text-green-600 font-bold mt-0.5">✓</span>
                            <span>{rec}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Root Causes - Full Width if available */}
                {aiInsights.root_causes && aiInsights.root_causes.length > 0 && (
                  <div className="bg-white rounded-lg p-4">
                    <h3 className="font-semibold text-gray-900 mb-3">🔍 Root Causes</h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                      {aiInsights.root_causes.map((cause, index) => (
                        <div key={index} className="flex items-start gap-2 text-sm text-gray-700 bg-red-50 rounded p-2">
                          <span className="text-red-600 font-bold mt-0.5">⚠</span>
                          <span>{cause}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Error Patterns */}
                {aiInsights.error_patterns && aiInsights.error_patterns.length > 0 && (
                  <div className="bg-white rounded-lg p-4">
                    <h3 className="font-semibold text-gray-900 mb-3">📈 Error Patterns</h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                      {aiInsights.error_patterns.slice(0, 4).map((pattern, index) => (
                        <div key={index} className="bg-gray-50 rounded-lg p-3 border border-gray-200">
                          <div className="text-xs text-gray-500 mb-1">{pattern.code}</div>
                          <div className="text-2xl font-bold text-gray-900">{pattern.count}</div>
                          <div className="text-xs text-gray-600 mt-1">{pattern.percentage}% of failures</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : overview.failed === 0 ? (
              <div className="text-center py-8">
                <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-3" />
                <p className="text-gray-600">No failed invoices. Everything is running smoothly!</p>
              </div>
            ) : (
              <div className="text-center py-8">
                <Activity className="h-12 w-12 text-gray-400 mx-auto mb-3" />
                <p className="text-gray-600">Click "Generate Insights" to analyze failed invoices</p>
              </div>
            )}
        </div>
          </div>
        )}

        {activeTab === 'operations' && (
          <DashboardOperations />
        )}

        {activeTab === 'business' && (
          <div className="p-6 text-center">
            <div className="bg-white rounded-lg shadow p-12">
              <TrendingUp className="h-16 w-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 mb-2">Business Intelligence</h3>
              <p className="text-gray-600">Revenue, cost analysis, and business metrics coming soon.</p>
            </div>
          </div>
        )}

        {activeTab === 'analytics' && (
          <div className="p-6 text-center">
            <div className="bg-white rounded-lg shadow p-12">
              <Activity className="h-16 w-16 text-gray-400 mx-auto mb-4" />
              <h3 className="text-xl font-semibold text-gray-900 mb-2">Advanced Analytics</h3>
              <p className="text-gray-600">Product, industry, and trend analysis coming soon.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

