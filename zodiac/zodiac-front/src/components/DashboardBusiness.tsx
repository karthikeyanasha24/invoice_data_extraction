'use client';

import { useState, useEffect } from 'react';
import {
  Users,
  Globe,
  Building2,
  Package,
  TrendingUp,
  RefreshCw,
  CheckCircle,
  XCircle,
  ChevronRight
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
import { dashboardApi, adminApi } from '@/lib/api';
import LoadingSpinner from './LoadingSpinner';
import type { BusinessAnalytics } from '@/types';

const COLORS = {
  primary: '#3b82f6',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  purple: '#8b5cf6',
  pink: '#ec4899',
  indigo: '#6366f1',
  teal: '#14b8a6',
};

export default function DashboardBusiness() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<BusinessAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [backfillLoading, setBackfillLoading] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchBusinessData();
  }, []);

  const fetchBusinessData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await dashboardApi.getBusiness(30);
      setData(response);
      setLoading(false);
    } catch (err: any) {
      console.error('Failed to fetch business analytics:', err);
      setError(err.message || 'Failed to load business analytics');
      setLoading(false);
    }
  };

  const handleRunBackfill = async () => {
    try {
      setBackfillLoading(true);
      setBackfillMessage(null);
      
      // Run both legacy and V2 backfill
      const [legacyResult, v2Result] = await Promise.allSettled([
        fetch('/api/v1/admin/backfill-business-intelligence', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        }).then(r => r.json()),
        dashboardApi.backfillInvoiceV2BI()
      ]);

      const messages = [];
      
      if (legacyResult.status === 'fulfilled') {
        messages.push(`Legacy: ${legacyResult.value.message || 'Completed'}`);
      }
      
      if (v2Result.status === 'fulfilled') {
        messages.push(`Invoice V2: ${v2Result.value.message || `Processed ${v2Result.value.processed} invoices`}`);
      }
      
      setBackfillMessage(messages.join(' | '));
      
      // Auto-refresh after 3 seconds
      setTimeout(() => {
        fetchBusinessData();
      }, 3000);
      
    } catch (err: any) {
      setBackfillMessage(`Error: ${err.message || 'Failed to start backfill'}`);
    } finally {
      setBackfillLoading(false);
    }
  };

  // Loading state
  if (loading) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner />
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="space-y-6 p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-red-900 mb-2">Failed to Load Business Analytics</h3>
          <p className="text-red-700">{error}</p>
          <button
            onClick={fetchBusinessData}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  // No data state
  if (!data) {
    return (
      <div className="space-y-6 p-6">
        <div className="text-center py-12 text-gray-500">
          <Building2 className="h-16 w-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium mb-2">No Business Data Available</p>
          <p className="text-sm">Upload some invoices to see business analytics</p>
        </div>
      </div>
    );
  }

  // Check if backfill is needed
  if ((data as any).needs_backfill) {
    const autoBackfillTriggered = (data as any).auto_backfill_triggered;
    const processedCount = (data as any).processed_count || 0;
    const totalInvoices = (data as any).total_invoices || 0;
    
    return (
      <div className="space-y-6 p-6">
        <div className={`${autoBackfillTriggered ? 'bg-blue-50 border-blue-200' : 'bg-yellow-50 border-yellow-200'} border rounded-lg p-8 text-center`}>
          <div className={`${autoBackfillTriggered ? 'bg-blue-100' : 'bg-yellow-100'} rounded-full w-16 h-16 flex items-center justify-center mx-auto mb-4`}>
            {autoBackfillTriggered ? (
              <RefreshCw className={`h-8 w-8 ${autoBackfillTriggered ? 'text-blue-600 animate-spin' : 'text-yellow-600'}`} />
            ) : (
              <Building2 className="h-8 w-8 text-yellow-600" />
            )}
          </div>
          
          {autoBackfillTriggered ? (
            <>
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                🎉 Processing Your Invoices!
              </h3>
              <p className="text-gray-700 mb-4 max-w-2xl mx-auto">
                We're analyzing your invoices to extract business intelligence data. 
                {processedCount > 0 && ` Processed ${processedCount} of ${totalInvoices} invoices so far.`}
              </p>
              <div className="bg-white border border-blue-200 rounded-lg p-4 mb-4 max-w-md mx-auto">
                <p className="text-sm text-gray-600">
                  ⏳ This usually takes 1-3 minutes. Click the refresh button below in a moment to see your analytics.
                </p>
              </div>
            </>
          ) : (
            <>
              <h3 className="text-xl font-semibold text-gray-900 mb-2">
                No Business Data Yet
              </h3>
              <p className="text-gray-700 mb-4 max-w-2xl mx-auto">
                {(data as any).message || 'Upload invoices to see business analytics, or refresh if you just uploaded.'}
              </p>
            </>
          )}

          <button
            onClick={fetchBusinessData}
            className={`px-6 py-3 ${autoBackfillTriggered ? 'bg-blue-600 hover:bg-blue-700' : 'bg-yellow-600 hover:bg-yellow-700'} text-white rounded-md font-medium transition-colors`}
          >
            <RefreshCw className="h-4 w-4 inline mr-2" />
            Refresh to See Data
          </button>
          
          {!autoBackfillTriggered && (
            <p className="text-xs text-gray-500 mt-4">
              Business intelligence data is automatically extracted when you upload invoices.
            </p>
          )}
        </div>
      </div>
    );
  }

  // Prepare funnel data for chart
  const funnelData = [
    {
      stage: 'Received',
      value: data.lifecycle_funnel.RECEIVED.total,
      success: data.lifecycle_funnel.RECEIVED.success,
      failed: data.lifecycle_funnel.RECEIVED.failed
    },
    {
      stage: 'Validated',
      value: data.lifecycle_funnel.VALIDATED.total,
      success: data.lifecycle_funnel.VALIDATED.success,
      failed: data.lifecycle_funnel.VALIDATED.failed
    },
    {
      stage: 'Converted',
      value: data.lifecycle_funnel.CONVERTED.total,
      success: data.lifecycle_funnel.CONVERTED.success,
      failed: data.lifecycle_funnel.CONVERTED.failed
    },
    {
      stage: 'Sent',
      value: data.lifecycle_funnel.SENT.total,
      success: data.lifecycle_funnel.SENT.success,
      failed: data.lifecycle_funnel.SENT.failed
    },
    {
      stage: 'Acknowledged',
      value: data.lifecycle_funnel.ACKNOWLEDGED.total,
      success: data.lifecycle_funnel.ACKNOWLEDGED.success,
      failed: data.lifecycle_funnel.ACKNOWLEDGED.failed
    }
  ].filter(item => item.value > 0);

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Business Intelligence</h2>
          <p className="text-sm text-gray-600 mt-1">Customer analysis, lifecycle tracking, and market insights</p>
        </div>
        <button
          onClick={fetchBusinessData}
          className="p-2 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          title="Refresh Data"
        >
          <RefreshCw className="h-5 w-5 text-gray-600" />
        </button>
      </div>

      {/* E2E Lifecycle Funnel */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">E2E Invoice Lifecycle Funnel</h3>
        <p className="text-sm text-gray-600 mb-6">Track where invoices succeed or fail in the end-to-end process</p>
        
        {funnelData.length > 0 ? (
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={funnelData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis type="number" stroke="#6b7280" tick={{ fill: '#6b7280', fontSize: 12 }} />
                <YAxis 
                  type="category" 
                  dataKey="stage" 
                  stroke="#6b7280" 
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                  width={100}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: 'white',
                    border: '1px solid #e5e7eb',
                    borderRadius: '0.5rem',
                    fontSize: '0.875rem'
                  }}
                />
                <Legend />
                <Bar dataKey="success" name="Success" fill={COLORS.success} radius={[0, 4, 4, 0]} />
                <Bar dataKey="failed" name="Failed" fill={COLORS.danger} radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <p>No lifecycle data available yet</p>
          </div>
        )}
      </div>

      {/* Customer Analysis - Priority #1 */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">Top Customers</h3>
            <p className="text-sm text-gray-600 mt-1">
              {data.customer_analysis.total_customers} total customers • Performance and revenue metrics
            </p>
          </div>
          <div className="p-3 bg-blue-100 rounded-full">
            <Users className="h-6 w-6 text-blue-600" />
          </div>
        </div>

        {data.customer_analysis.top_customers.length > 0 ? (
          <div className="space-y-4">
            {data.customer_analysis.top_customers.map((customer, index) => (
              <div
                key={index}
                className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="text-2xl font-bold text-gray-400">#{index + 1}</span>
                      <div>
                        <h4 className="font-semibold text-gray-900">{customer.customer_name}</h4>
                        <p className="text-sm text-gray-600">
                          {customer.customer_country || 'Unknown Country'}
                        </p>
                      </div>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-gray-900">
                      {customer.total_invoices}
                    </div>
                    <div className="text-xs text-gray-500">Total Invoices</div>
                  </div>
                </div>

                {/* Stats Grid */}
                <div className="grid grid-cols-4 gap-4 mb-3">
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-green-600 mb-1">
                      <CheckCircle className="h-4 w-4" />
                      <span className="font-semibold">{customer.successful}</span>
                    </div>
                    <div className="text-xs text-gray-600">Successful</div>
                  </div>
                  <div className="text-center">
                    <div className="flex items-center justify-center gap-1 text-red-600 mb-1">
                      <XCircle className="h-4 w-4" />
                      <span className="font-semibold">{customer.failed}</span>
                    </div>
                    <div className="text-xs text-gray-600">Failed</div>
                  </div>
                  <div className="text-center">
                    <div className="font-semibold text-blue-600 mb-1">
                      {customer.success_rate}%
                    </div>
                    <div className="text-xs text-gray-600">Success Rate</div>
                  </div>
                  <div className="text-center">
                    <div className="font-semibold text-purple-600 mb-1">
                      ${customer.total_revenue.toLocaleString()}
                    </div>
                    <div className="text-xs text-gray-600">Revenue</div>
                  </div>
                </div>

                {/* Success Rate Bar */}
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div
                    className="bg-gradient-to-r from-green-500 to-blue-500 h-2 rounded-full"
                    style={{ width: `${customer.success_rate}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-gray-500">
            <Users className="h-12 w-12 mx-auto mb-2 text-gray-300" />
            <p>No customer data available yet</p>
          </div>
        )}
      </div>

      {/* Country & Industry Distribution */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Country Distribution */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center gap-2 mb-4">
            <Globe className="h-5 w-5 text-blue-600" />
            <h3 className="text-lg font-semibold text-gray-900">Country Distribution</h3>
          </div>
          
          {data.country_distribution.length > 0 ? (
            <div className="space-y-3">
              {data.country_distribution.slice(0, 10).map((item, index) => (
                <div key={index} className="flex items-center gap-3">
                  <div className="w-12 text-sm font-medium text-gray-600">{item.country}</div>
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-blue-600 h-2 rounded-full"
                          style={{
                            width: `${(item.count / data.country_distribution[0].count) * 100}%`
                          }}
                        />
                      </div>
                      <span className="text-sm font-semibold text-gray-900 w-12 text-right">
                        {item.count}
                      </span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <Globe className="h-12 w-12 mx-auto mb-2 text-gray-300" />
              <p>No country data available yet</p>
            </div>
          )}
        </div>

        {/* Industry Breakdown */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center gap-2 mb-4">
            <Building2 className="h-5 w-5 text-purple-600" />
            <h3 className="text-lg font-semibold text-gray-900">Industry Breakdown</h3>
          </div>
          
          {data.industry_breakdown.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={data.industry_breakdown as unknown as { [key: string]: string | number }[]}
                    dataKey="count"
                    nameKey="industry"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    label={(entry) => entry.industry}
                  >
                    {data.industry_breakdown.map((entry, index) => (
                      <Cell 
                        key={`cell-${index}`} 
                        fill={Object.values(COLORS)[index % Object.values(COLORS).length]} 
                      />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: 'white',
                      border: '1px solid #e5e7eb',
                      borderRadius: '0.5rem',
                      fontSize: '0.875rem'
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <Building2 className="h-12 w-12 mx-auto mb-2 text-gray-300" />
              <p>No industry data available yet</p>
            </div>
          )}
        </div>
      </div>

      {/* Product & Supplier Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Top Products */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center gap-2 mb-4">
            <Package className="h-5 w-5 text-teal-600" />
            <h3 className="text-lg font-semibold text-gray-900">Top Products</h3>
          </div>
          
          {data.product_analysis.top_products.length > 0 ? (
            <div className="space-y-3">
              {data.product_analysis.top_products.map((product, index) => (
                <div key={index} className="border-l-4 border-teal-500 pl-4 py-2">
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-medium text-gray-900">{product.name}</span>
                    <span className="text-sm font-semibold text-teal-600">
                      {product.count} invoices
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm text-gray-600">
                    <span>Qty: {product.total_quantity}</span>
                    <span>•</span>
                    <span>Revenue: ${product.total_revenue.toLocaleString()}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <Package className="h-12 w-12 mx-auto mb-2 text-gray-300" />
              <p>No product data available yet</p>
            </div>
          )}
        </div>

        {/* Top Suppliers */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="h-5 w-5 text-orange-600" />
            <h3 className="text-lg font-semibold text-gray-900">Top Suppliers</h3>
          </div>
          
          {data.supplier_analysis.top_suppliers.length > 0 ? (
            <div className="space-y-3">
              {data.supplier_analysis.top_suppliers.map((supplier, index) => (
                <div key={index} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                  <div className="flex items-center gap-3">
                    <div className="flex items-center justify-center w-8 h-8 rounded-full bg-orange-100 text-orange-600 font-semibold text-sm">
                      {index + 1}
                    </div>
                    <span className="font-medium text-gray-900">{supplier.supplier_name}</span>
                  </div>
                  <span className="text-sm font-semibold text-orange-600">
                    {supplier.count} invoices
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              <TrendingUp className="h-12 w-12 mx-auto mb-2 text-gray-300" />
              <p>No supplier data available yet</p>
            </div>
          )}
        </div>
      </div>

      {/* Key Insights */}
      <div className="bg-gradient-to-r from-blue-50 to-purple-50 rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Business Insights</h3>
        <ul className="space-y-2 text-sm text-gray-700">
          <li className="flex items-start gap-2">
            <ChevronRight className="h-5 w-5 text-blue-600 flex-shrink-0 mt-0.5" />
            <span>
              Serving {data.customer_analysis.total_customers} customers across{' '}
              {data.country_distribution.length} countries
            </span>
          </li>
          {data.customer_analysis.top_customers[0] && (
            <li className="flex items-start gap-2">
              <ChevronRight className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
              <span>
                Top customer: <strong>{data.customer_analysis.top_customers[0].customer_name}</strong> with{' '}
                {data.customer_analysis.top_customers[0].total_invoices} invoices and{' '}
                {data.customer_analysis.top_customers[0].success_rate}% success rate
              </span>
            </li>
          )}
          {data.industry_breakdown.length > 0 && (
            <li className="flex items-start gap-2">
              <ChevronRight className="h-5 w-5 text-purple-600 flex-shrink-0 mt-0.5" />
              <span>
                Primary industry: <strong>{data.industry_breakdown[0].industry}</strong> with{' '}
                {data.industry_breakdown[0].count} invoices
              </span>
            </li>
          )}
          {data.product_analysis.top_products[0] && (
            <li className="flex items-start gap-2">
              <ChevronRight className="h-5 w-5 text-teal-600 flex-shrink-0 mt-0.5" />
              <span>
                Most traded product: <strong>{data.product_analysis.top_products[0].name}</strong> appearing in{' '}
                {data.product_analysis.top_products[0].count} invoices
              </span>
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

