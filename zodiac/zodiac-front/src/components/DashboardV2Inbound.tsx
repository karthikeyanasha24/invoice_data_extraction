'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import { FileText, Merge, Send, Clock, Key, RefreshCw, Building2 } from 'lucide-react';
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

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899'];

export default function DashboardV2Inbound() {
  const [days, setDays] = useState(0);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await dashboardApi.getV2Inbound(days);
      setData(res);
    } catch (err: any) {
      setError(err.message || 'Failed to load inbound data');
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

  const { summary, by_document_type, by_source, top_suppliers, tokens } = data;
  const docTypeChart = (by_document_type || []).map((d: any) => ({ name: d.doc_type, count: d.count, value: d.count }));
  const sourceChart = (by_source || []).map((d: any) => ({ name: d.source, count: d.count, value: d.count }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h2 className="text-xl font-semibold text-gray-900">Inbound Process</h2>
        <div className="flex items-center gap-2">
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="rounded-md border border-gray-300 text-sm py-1.5 px-2"
          >
            <option value={0}>All Time</option>
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

      {/* KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">SAT Documents</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{summary?.total_documents ?? 0}</p>
            </div>
            <FileText className="h-8 w-8 text-blue-500" />
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Merges</p>
              <p className="text-2xl font-bold text-gray-900 mt-1">{summary?.merges_total ?? 0}</p>
            </div>
            <Merge className="h-8 w-8 text-indigo-500" />
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Sent to SAP</p>
              <p className="text-2xl font-bold text-green-700 mt-1">{summary?.merges_sent_to_sap ?? 0}</p>
            </div>
            <Send className="h-8 w-8 text-green-500" />
          </div>
        </div>
        <div className="bg-gray-50 rounded-lg p-4 border border-gray-200">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Pending</p>
              <p className="text-2xl font-bold text-amber-700 mt-1">{summary?.merges_pending ?? 0}</p>
            </div>
            <Clock className="h-8 w-8 text-amber-500" />
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {docTypeChart.length > 0 && (
          <div className="border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">By Document Type</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={docTypeChart} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#3b82f6" name="Count" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        {sourceChart.length > 0 && (
          <div className="border border-gray-200 rounded-lg p-4">
            <h3 className="text-sm font-semibold text-gray-900 mb-3">By Source</h3>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sourceChart}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    outerRadius={60}
                    label={({ name, value }) => `${name}: ${value}`}
                  >
                    {sourceChart.map((_: any, i: number) => (
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
      </div>

      {/* Tokens + Top suppliers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Key className="h-4 w-4" /> Supplier Tokens
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 rounded p-3">
              <p className="text-xs text-gray-500">Total</p>
              <p className="text-lg font-semibold">{tokens?.total ?? 0}</p>
            </div>
            <div className="bg-green-50 rounded p-3">
              <p className="text-xs text-gray-500">Active</p>
              <p className="text-lg font-semibold text-green-700">{tokens?.active ?? 0}</p>
            </div>
            <div className="bg-amber-50 rounded p-3">
              <p className="text-xs text-gray-500">Expired</p>
              <p className="text-lg font-semibold text-amber-700">{tokens?.expired ?? 0}</p>
            </div>
            <div className="bg-blue-50 rounded p-3">
              <p className="text-xs text-gray-500">Used (7d)</p>
              <p className="text-lg font-semibold text-blue-700">{tokens?.recently_used ?? 0}</p>
            </div>
          </div>
        </div>
        <div className="border border-gray-200 rounded-lg p-4">
          <h3 className="text-sm font-semibold text-gray-900 mb-3 flex items-center gap-2">
            <Building2 className="h-4 w-4" /> Top Suppliers
          </h3>
          {(top_suppliers?.length ?? 0) > 0 ? (
            <div className="max-h-48 overflow-y-auto">
              <div className="flex justify-between items-center gap-2 text-xs text-gray-500 font-medium pb-1 border-b border-gray-100">
                <span className="flex-1 min-w-0">Supplier</span>
                <span className="flex-shrink-0 w-14 text-right">Docs</span>
                <span className="flex-shrink-0 w-16 text-right">Total</span>
              </div>
              <ul className="space-y-2 mt-2">
                {top_suppliers.map((s: any, i: number) => (
                  <li key={i} className="flex justify-between items-center gap-2 text-sm">
                    <span className="truncate font-medium text-gray-800 flex-1 min-w-0">{s.supplier_name || s.supplier_rfc}</span>
                    <span className="text-gray-600 flex-shrink-0 w-14 text-right">{s.count}</span>
                    <span className="text-xs font-medium text-gray-800 flex-shrink-0 w-16 text-right">
                      {typeof s.total_amount === 'number'
                        ? s.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })
                        : s.total_amount ?? '0.00'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-gray-500">No supplier data in this period</p>
          )}
        </div>
      </div>
    </div>
  );
}
