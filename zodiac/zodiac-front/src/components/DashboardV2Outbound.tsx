'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import { FileInput, CheckCircle, XCircle, FileOutput, RefreshCw, Users } from 'lucide-react';
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
} from 'recharts';

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16'];

export default function DashboardV2Outbound() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  const { summary, funnel, by_format, top_customers, timeline } = data;
  const formatChart = (by_format || []).map((f: any) => ({ name: f.format, count: f.count, value: f.count }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-semibold text-gray-900">Outbound Process</h2>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-gray-300 text-sm py-1.5 px-2"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
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

      {/* Funnel / KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Received</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{funnel?.documents_received ?? 0}</p>
            </div>
            <FileInput className="h-8 w-8 text-blue-500" />
          </div>
          <p className="text-xs text-gray-500 mt-1">Documents from SAP</p>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Validated</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{summary?.validated_total ?? 0}</p>
            </div>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {summary?.validated_success ?? 0} ok, {summary?.validated_failed ?? 0} failed
          </p>
        </div>
        <div className="bg-green-50 rounded-lg p-4 border border-green-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Validation Rate</p>
              <p className="text-2xl font-bold text-green-700 mt-1">{summary?.validation_success_rate_pct ?? 0}%</p>
            </div>
            <CheckCircle className="h-8 w-8 text-green-500" />
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Converted</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{summary?.converted_success ?? 0}</p>
            </div>
            <FileOutput className="h-8 w-8 text-indigo-500" />
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {summary?.converted_failed ?? 0} failed, {summary?.converted_pending ?? 0} pending
          </p>
        </div>
        <div className="bg-green-50 rounded-lg p-4 border border-green-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Conversion Rate</p>
              <p className="text-2xl font-bold text-green-700 mt-1">{summary?.conversion_success_rate_pct ?? 0}%</p>
            </div>
            <CheckCircle className="h-8 w-8 text-green-500" />
          </div>
        </div>
      </div>

      {/* By format + Top customers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {formatChart.length > 0 && (
          <div className="border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">By Target Format</h3>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={formatChart}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={70}
                    label={({ name, value }) => `${name}: ${value}`}
                  >
                    {formatChart.map((_: any, i: number) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Users className="h-4 w-4" /> Top Customers (converted)
          </h3>
          {(top_customers?.length ?? 0) > 0 ? (
            <ul className="space-y-2 max-h-52 overflow-y-auto">
              {top_customers.map((c: any, i: number) => (
                <li key={i} className="flex justify-between text-sm">
                  <span className="truncate font-medium text-gray-800">{c.customer_id}</span>
                  <span className="text-gray-600">{c.count}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-gray-500">No customer data in this period</p>
          )}
        </div>
      </div>

      {/* Timeline */}
      {timeline?.length > 0 && (
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3">Documents Received Over Time</h3>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={timeline} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="documents" fill="#3b82f6" name="Documents" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}
