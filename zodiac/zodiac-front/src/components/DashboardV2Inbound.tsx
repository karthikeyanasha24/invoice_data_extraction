'use client';

import { useState, useEffect } from 'react';
import { dashboardApi } from '@/lib/api';
import { FileText, Merge, Send, Clock, Key, RefreshCw, Building2, ArrowDownCircle } from 'lucide-react';
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

const DOC_TYPE_COLORS: Record<string, string> = {
  CREDIT_NOTE: 'bg-purple-100 text-purple-700',
  INVOICE: 'bg-blue-100 text-blue-700',
  PAYMENT: 'bg-green-100 text-green-700',
};

function formatDate(iso: string | null) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

export default function DashboardV2Inbound() {
  const [days, setDays] = useState(0);
  const [data, setData] = useState<any>(null);
  const [recentDocs, setRecentDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      const [res, recent] = await Promise.all([
        dashboardApi.getV2Inbound(days),
        dashboardApi.getV2InboundRecent(10),
      ]);
      setData(res);
      setRecentDocs(recent?.recent_documents ?? []);
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
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">SAT Documents</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{summary?.total_documents ?? 0}</p>
            </div>
            <div className="bg-blue-50 p-2 rounded-lg">
              <FileText className="h-6 w-6 text-blue-600" />
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Merges</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{summary?.merges_total ?? 0}</p>
            </div>
            <div className="bg-indigo-50 p-2 rounded-lg">
              <Merge className="h-6 w-6 text-indigo-600" />
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Sent to SAP</p>
              <p className="text-3xl font-bold text-green-600 mt-2">{summary?.merges_sent_to_sap ?? 0}</p>
            </div>
            <div className="bg-green-50 p-2 rounded-lg">
              <Send className="h-6 w-6 text-green-600" />
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
          <div className="flex items-start justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Pending</p>
              <p className="text-3xl font-bold text-amber-600 mt-2">{summary?.merges_pending ?? 0}</p>
            </div>
            <div className="bg-amber-50 p-2 rounded-lg">
              <Clock className="h-6 w-6 text-amber-600" />
            </div>
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {docTypeChart.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">By Document Type</h3>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={docTypeChart} margin={{ top: 4, right: 8, left: -16, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} axisLine={false} tickLine={false} />
                  <Tooltip
                    contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb', fontSize: '12px' }}
                    cursor={{ fill: '#f3f4f6' }}
                  />
                  <Bar dataKey="count" fill="#3b82f6" name="Count" radius={[6, 6, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
        {sourceChart.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-4">By Source</h3>
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={sourceChart}
                    dataKey="value"
                    nameKey="name"
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={70}
                    paddingAngle={3}
                    label={({ name, value }) => `${name}: ${value}`}
                    labelLine={false}
                  >
                    {sourceChart.map((_: any, i: number) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: '8px', border: '1px solid #e5e7eb', fontSize: '12px' }} />
                  <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: '12px' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}
      </div>

      {/* Tokens + Top suppliers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Key className="h-4 w-4 text-gray-500" /> Supplier Tokens
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-gray-50 p-3 border border-gray-100">
              <p className="text-xs text-gray-500 font-medium">Total</p>
              <p className="text-xl font-bold text-gray-800 mt-1">{tokens?.total ?? 0}</p>
            </div>
            <div className="rounded-lg bg-green-50 p-3 border border-green-100">
              <p className="text-xs text-green-600 font-medium">Active</p>
              <p className="text-xl font-bold text-green-700 mt-1">{tokens?.active ?? 0}</p>
            </div>
            <div className="rounded-lg bg-amber-50 p-3 border border-amber-100">
              <p className="text-xs text-amber-600 font-medium">Expired</p>
              <p className="text-xl font-bold text-amber-700 mt-1">{tokens?.expired ?? 0}</p>
            </div>
            <div className="rounded-lg bg-blue-50 p-3 border border-blue-100">
              <p className="text-xs text-blue-600 font-medium">Used (7d)</p>
              <p className="text-xl font-bold text-blue-700 mt-1">{tokens?.recently_used ?? 0}</p>
            </div>
          </div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
          <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <Building2 className="h-4 w-4 text-gray-500" /> Top Suppliers
          </h3>
          {(top_suppliers?.length ?? 0) > 0 ? (
            <div className="max-h-48 overflow-y-auto">
              <div className="flex justify-between items-center gap-2 text-xs text-gray-400 font-semibold uppercase tracking-wide pb-2 border-b border-gray-100">
                <span className="flex-1 min-w-0">Supplier</span>
                <span className="flex-shrink-0 w-12 text-right">Docs</span>
                <span className="flex-shrink-0 w-20 text-right">Total</span>
              </div>
              <ul className="divide-y divide-gray-50 mt-1">
                {top_suppliers.map((s: any, i: number) => (
                  <li key={i} className="flex justify-between items-center gap-2 py-2 text-sm">
                    <span className="truncate font-medium text-gray-800 flex-1 min-w-0">{s.supplier_name || s.supplier_rfc}</span>
                    <span className="text-gray-500 flex-shrink-0 w-12 text-right font-medium">{s.count}</span>
                    <span className="text-xs font-semibold text-gray-700 flex-shrink-0 w-20 text-right">
                      {typeof s.total_amount === 'number'
                        ? s.total_amount.toLocaleString(undefined, { minimumFractionDigits: 2 })
                        : s.total_amount ?? '0.00'}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-gray-400 mt-2">No supplier data in this period</p>
          )}
        </div>
      </div>
      {/* Recently Received Documents */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-5">
        <h3 className="text-sm font-semibold text-gray-700 mb-4 flex items-center gap-2">
          <ArrowDownCircle className="h-4 w-4 text-blue-500" />
          Recently Received Documents
          <span className="ml-auto text-xs text-gray-400 font-normal">Sorted by received date</span>
        </h3>
        {recentDocs.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-gray-400 font-semibold uppercase tracking-wide border-b border-gray-100">
                  <th className="text-left pb-2 pr-4">Type</th>
                  <th className="text-left pb-2 pr-4">Supplier</th>
                  <th className="text-left pb-2 pr-4">Amount</th>
                  <th className="text-left pb-2 pr-4">Status</th>
                  <th className="text-left pb-2">Received At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {recentDocs.map((doc: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-50 transition-colors">
                    <td className="py-2.5 pr-4">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${DOC_TYPE_COLORS[doc.doc_type] ?? 'bg-gray-100 text-gray-600'}`}>
                        {doc.doc_type?.replace('_', ' ')}
                      </span>
                    </td>
                    <td className="py-2.5 pr-4">
                      <p className="font-medium text-gray-800 truncate max-w-[160px]">{doc.supplier_name || doc.supplier_rfc}</p>
                      <p className="text-xs text-gray-400">{doc.supplier_rfc}</p>
                    </td>
                    <td className="py-2.5 pr-4 font-medium text-gray-700">
                      {doc.moneda} {doc.total ?? '0.00'}
                    </td>
                    <td className="py-2.5 pr-4">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${doc.status === 'VALIDATED' ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-600'}`}>
                        {doc.status}
                      </span>
                    </td>
                    <td className="py-2.5 text-gray-500 text-xs">{formatDate(doc.received_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-gray-400">No documents received yet.</p>
        )}
      </div>
    </div>
  );
}
