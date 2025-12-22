'use client';

import { useState, useEffect } from 'react';
import { 
  ArrowUpCircle, 
  ArrowDownCircle, 
  Zap, 
  Clock,
  CheckCircle,
  XCircle,
  RefreshCw,
  TrendingUp
} from 'lucide-react';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
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

const COLORS = {
  inbound: '#3b82f6',
  outbound: '#10b981',
  autoFixed: '#f59e0b',
  manual: '#6b7280',
};

// Placeholder data - will be replaced with real API data
const mockData = {
  messageFlow: {
    inbound: 89,
    outbound: 156,
    total: 245
  },
  autoFix: {
    total: 45,
    successful: 38,
    failed: 7,
    successRate: 84.4,
    timeSaved: 127 // minutes
  },
  processingTime: {
    average: 2.3, // seconds
    min: 0.5,
    max: 8.2
  },
  externalSystems: {
    success: 142,
    failed: 14,
    successRate: 91.0
  }
};

const autoFixBreakdown = [
  { type: 'Missing Fields', count: 18, saved: 54 },
  { type: 'Date Format', count: 12, saved: 24 },
  { type: 'ID Padding', count: 8, saved: 16 },
  { type: 'Party Info', count: 7, saved: 21 },
];

const processingTimeData = [
  { hour: '00:00', avgTime: 2.1 },
  { hour: '04:00', avgTime: 1.8 },
  { hour: '08:00', avgTime: 2.8 },
  { hour: '12:00', avgTime: 3.2 },
  { hour: '16:00', avgTime: 2.5 },
  { hour: '20:00', avgTime: 2.0 },
];

export default function DashboardOperations() {
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState(mockData);

  // TODO: Replace with real API call
  // useEffect(() => {
  //   fetchOperationsData();
  // }, []);

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Operations Intelligence</h2>
          <p className="text-sm text-gray-600 mt-1">Message flow, auto-fix analytics, and performance metrics</p>
        </div>
        <button
          className="p-2 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          title="Refresh Data"
        >
          <RefreshCw className="h-5 w-5 text-gray-600" />
        </button>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Inbound Messages */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Inbound</p>
              <p className="text-3xl font-bold text-blue-600 mt-2">{data.messageFlow.inbound}</p>
              <p className="text-xs text-gray-500 mt-1">Received from systems</p>
            </div>
            <div className="p-3 bg-blue-100 rounded-full">
              <ArrowDownCircle className="h-6 w-6 text-blue-600" />
            </div>
          </div>
        </div>

        {/* Outbound Messages */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Outbound</p>
              <p className="text-3xl font-bold text-green-600 mt-2">{data.messageFlow.outbound}</p>
              <p className="text-xs text-gray-500 mt-1">Sent to systems</p>
            </div>
            <div className="p-3 bg-green-100 rounded-full">
              <ArrowUpCircle className="h-6 w-6 text-green-600" />
            </div>
          </div>
        </div>

        {/* Auto-Fixed */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Auto-Fixed</p>
              <p className="text-3xl font-bold text-orange-600 mt-2">{data.autoFix.total}</p>
              <p className="text-xs text-gray-500 mt-1">{data.autoFix.successRate}% success rate</p>
            </div>
            <div className="p-3 bg-orange-100 rounded-full">
              <Zap className="h-6 w-6 text-orange-600" />
            </div>
          </div>
        </div>

        {/* Avg Processing Time */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Avg Time</p>
              <p className="text-3xl font-bold text-purple-600 mt-2">{data.processingTime.average}s</p>
              <p className="text-xs text-gray-500 mt-1">Per invoice</p>
            </div>
            <div className="p-3 bg-purple-100 rounded-full">
              <Clock className="h-6 w-6 text-purple-600" />
            </div>
          </div>
        </div>
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Auto-Fix Breakdown */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Auto-Fix Breakdown</h3>
          <div className="space-y-3">
            {autoFixBreakdown.map((item, index) => (
              <div key={index} className="flex items-center justify-between">
                <div className="flex-1">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-sm font-medium text-gray-700">{item.type}</span>
                    <span className="text-sm text-gray-500">{item.count} fixes</span>
                  </div>
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <div
                      className="bg-orange-600 h-2 rounded-full"
                      style={{ width: `${(item.count / data.autoFix.total) * 100}%` }}
                    />
                  </div>
                </div>
                <div className="ml-4 text-xs text-green-600 font-medium">
                  {item.saved}m saved
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 pt-4 border-t border-gray-200">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600">Total Time Saved</span>
              <span className="font-bold text-green-600">{data.autoFix.timeSaved} minutes</span>
            </div>
          </div>
        </div>

        {/* Processing Time Trend */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Processing Time Trend</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={processingTimeData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="hour"
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                />
                <YAxis
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                  label={{ value: 'Seconds', angle: -90, position: 'insideLeft' }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '0.5rem',
                  }}
                />
                <Line
                  type="monotone"
                  dataKey="avgTime"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                  name="Avg Time (s)"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* External System Status */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">External Systems</h3>
          <div className="flex items-center justify-center">
            <div className="relative">
              <svg className="w-32 h-32">
                <circle
                  cx="64"
                  cy="64"
                  r="56"
                  fill="none"
                  stroke="#e5e7eb"
                  strokeWidth="12"
                />
                <circle
                  cx="64"
                  cy="64"
                  r="56"
                  fill="none"
                  stroke="#10b981"
                  strokeWidth="12"
                  strokeDasharray={`${2 * Math.PI * 56 * (data.externalSystems.successRate / 100)} ${2 * Math.PI * 56}`}
                  strokeLinecap="round"
                  transform="rotate(-90 64 64)"
                />
              </svg>
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900">{data.externalSystems.successRate}%</div>
                  <div className="text-xs text-gray-500">Success</div>
                </div>
              </div>
            </div>
          </div>
          <div className="mt-4 space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600 flex items-center gap-1">
                <CheckCircle className="h-4 w-4 text-green-600" />
                Successful
              </span>
              <span className="font-medium">{data.externalSystems.success}</span>
            </div>
            <div className="flex items-center justify-between text-sm">
              <span className="text-gray-600 flex items-center gap-1">
                <XCircle className="h-4 w-4 text-red-600" />
                Failed
              </span>
              <span className="font-medium">{data.externalSystems.failed}</span>
            </div>
          </div>
        </div>

        {/* Performance Summary */}
        <div className="lg:col-span-2 bg-gradient-to-br from-blue-50 to-purple-50 rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-blue-600" />
            Performance Summary
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div className="bg-white rounded-lg p-4">
              <div className="text-2xl font-bold text-gray-900">{data.messageFlow.total}</div>
              <div className="text-sm text-gray-600 mt-1">Total Messages</div>
              <div className="text-xs text-green-600 mt-2">↑ 12% from last period</div>
            </div>
            <div className="bg-white rounded-lg p-4">
              <div className="text-2xl font-bold text-gray-900">{data.autoFix.successRate}%</div>
              <div className="text-sm text-gray-600 mt-1">Auto-Fix Rate</div>
              <div className="text-xs text-green-600 mt-2">↑ 5% improvement</div>
            </div>
            <div className="bg-white rounded-lg p-4">
              <div className="text-2xl font-bold text-gray-900">{data.autoFix.timeSaved}m</div>
              <div className="text-sm text-gray-600 mt-1">Time Saved</div>
              <div className="text-xs text-green-600 mt-2">≈ 2.1 hours</div>
            </div>
          </div>
          <div className="mt-4 bg-white rounded-lg p-4">
            <h4 className="text-sm font-semibold text-gray-900 mb-2">Key Insights</h4>
            <ul className="space-y-2 text-sm text-gray-700">
              <li className="flex items-start gap-2">
                <span className="text-green-600 mt-0.5">✓</span>
                <span>Auto-fix feature saved approximately 2.1 hours of manual work</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-blue-600 mt-0.5">•</span>
                <span>Peak processing time occurs around 12:00 (lunch hour)</span>
              </li>
              <li className="flex items-start gap-2">
                <span className="text-orange-600 mt-0.5">⚠</span>
                <span>External system success rate can be improved ({data.externalSystems.failed} failures)</span>
              </li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

