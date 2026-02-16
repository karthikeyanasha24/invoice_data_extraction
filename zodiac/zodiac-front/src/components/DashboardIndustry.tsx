'use client';

import { useState, useEffect } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Minus,
  AlertTriangle,
  CheckCircle,
  Target,
  DollarSign,
  Package,
  BarChart3,
  Lightbulb,
  RefreshCw,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { dashboardApi } from '@/lib/api';
import LoadingSpinner from './LoadingSpinner';
import type { IndustryIntelligence, ProductPerformance } from '@/types';

const PERFORMANCE_COLORS = {
  underperforming: {
    bg: 'bg-red-50',
    border: 'border-red-200',
    text: 'text-red-700',
    icon: 'text-red-600',
    badge: 'bg-red-100 text-red-800'
  },
  optimal: {
    bg: 'bg-blue-50',
    border: 'border-blue-200',
    text: 'text-blue-700',
    icon: 'text-blue-600',
    badge: 'bg-blue-100 text-blue-800'
  },
  outperforming: {
    bg: 'bg-green-50',
    border: 'border-green-200',
    text: 'text-green-700',
    icon: 'text-green-600',
    badge: 'bg-green-100 text-green-800'
  }
};

export default function DashboardIndustry() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState<IndustryIntelligence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedProduct, setExpandedProduct] = useState<string | null>(null);
  const [backfillLoading, setBackfillLoading] = useState(false);
  const [backfillMessage, setBackfillMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchIndustryData();
  }, []);

  const fetchIndustryData = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await dashboardApi.getIndustryIntelligence(30);
      setData(response);
      setLoading(false);
    } catch (err: any) {
      console.error('Failed to fetch industry intelligence:', err);
      setError(err.message || 'Failed to load industry intelligence');
      setLoading(false);
    }
  };

  const handleBackfill = async () => {
    try {
      setBackfillLoading(true);
      setBackfillMessage(null);
      
      const result = await dashboardApi.backfillInvoiceV2BI();
      setBackfillMessage(`✅ ${result.message || `Processed ${result.processed} invoices`}`);
      
      // Auto-refresh after 3 seconds
      setTimeout(() => {
        fetchIndustryData();
        setBackfillMessage(null);
      }, 3000);
      
    } catch (err: any) {
      setBackfillMessage(`❌ Error: ${err.message || 'Failed to backfill data'}`);
    } finally {
      setBackfillLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6 p-6">
        <div className="flex items-center justify-center py-12">
          <LoadingSpinner />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="space-y-6 p-6">
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h3 className="text-lg font-semibold text-red-900 mb-2">Failed to Load Industry Intelligence</h3>
          <p className="text-red-700">{error}</p>
          <button
            onClick={fetchIndustryData}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
          >
            Try Again
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.products.length === 0) {
    return (
      <div className="space-y-6 p-6">
        <div className="text-center py-12 text-gray-500">
          <Package className="h-16 w-16 mx-auto mb-4 text-gray-300" />
          <p className="text-lg font-medium mb-2">No Product Data Available</p>
          <p className="text-sm">Upload invoices with product information to see industry intelligence</p>
        </div>
      </div>
    );
  }

  const getPerformanceIcon = (status: string) => {
    switch (status) {
      case 'outperforming':
        return <TrendingUp className="h-5 w-5" />;
      case 'underperforming':
        return <TrendingDown className="h-5 w-5" />;
      default:
        return <Minus className="h-5 w-5" />;
    }
  };

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'increasing':
        return <TrendingUp className="h-4 w-4 text-green-600" />;
      case 'declining':
        return <TrendingDown className="h-4 w-4 text-red-600" />;
      default:
        return <Minus className="h-4 w-4 text-gray-600" />;
    }
  };

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Product Performance & Industry Intelligence</h2>
          <p className="text-sm text-gray-600 mt-1">
            AI-powered insights, benchmarking, and recommendations
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!data || data.products.length === 0 ? (
            <button
              onClick={handleBackfill}
              disabled={backfillLoading}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              {backfillLoading ? (
                <>
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  Processing...
                </>
              ) : (
                <>
                  <Package className="h-4 w-4" />
                  Backfill Invoice V2 Data
                </>
              )}
            </button>
          ) : null}
          <button
            onClick={fetchIndustryData}
            className="p-2 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
            title="Refresh Data"
          >
            <RefreshCw className="h-5 w-5 text-gray-600" />
          </button>
        </div>
      </div>
      
      {/* Backfill Message */}
      {backfillMessage && (
        <div className={`p-4 rounded-lg ${backfillMessage.includes('❌') ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'}`}>
          {backfillMessage}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-white rounded-lg shadow p-4">
          <div className="flex items-center gap-2 mb-2">
            <Package className="h-5 w-5 text-blue-600" />
            <span className="text-sm font-medium text-gray-600">Total Products</span>
          </div>
          <div className="text-2xl font-bold text-gray-900">{data.summary.total_products}</div>
        </div>

        <div className="bg-red-50 rounded-lg shadow p-4 border border-red-100">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="h-5 w-5 text-red-600" />
            <span className="text-sm font-medium text-red-700">Underperforming</span>
          </div>
          <div className="text-2xl font-bold text-red-900">{data.summary.underperforming}</div>
          <div className="text-xs text-red-600 mt-1">Need attention</div>
        </div>

        <div className="bg-blue-50 rounded-lg shadow p-4 border border-blue-100">
          <div className="flex items-center gap-2 mb-2">
            <Target className="h-5 w-5 text-blue-600" />
            <span className="text-sm font-medium text-blue-700">Optimal</span>
          </div>
          <div className="text-2xl font-bold text-blue-900">{data.summary.optimal}</div>
          <div className="text-xs text-blue-600 mt-1">Performing well</div>
        </div>

        <div className="bg-green-50 rounded-lg shadow p-4 border border-green-100">
          <div className="flex items-center gap-2 mb-2">
            <CheckCircle className="h-5 w-5 text-green-600" />
            <span className="text-sm font-medium text-green-700">Outperforming</span>
          </div>
          <div className="text-2xl font-bold text-green-900">{data.summary.outperforming}</div>
          <div className="text-xs text-green-600 mt-1">Exceeding targets</div>
        </div>

        <div className="bg-purple-50 rounded-lg shadow p-4 border border-purple-100">
          <div className="flex items-center gap-2 mb-2">
            <DollarSign className="h-5 w-5 text-purple-600" />
            <span className="text-sm font-medium text-purple-700">Total Revenue</span>
          </div>
          <div className="text-2xl font-bold text-purple-900">
            ${data.summary.total_revenue.toLocaleString()}
          </div>
        </div>
      </div>

      {/* AI Insights Panel */}
      {data.ai_insights && (data.ai_insights.overall_insights || data.ai_insights.industry_trends) && (
        <div className="bg-gradient-to-r from-purple-50 to-blue-50 rounded-lg shadow-lg p-6 border border-purple-100">
          <div className="flex items-center gap-2 mb-4">
            <Lightbulb className="h-6 w-6 text-purple-600" />
            <h3 className="text-lg font-semibold text-gray-900">AI-Powered Insights</h3>
          </div>
          
          {data.ai_insights.overall_insights && data.ai_insights.overall_insights.length > 0 && (
            <div className="mb-4">
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Key Findings:</h4>
              <ul className="space-y-2">
                {data.ai_insights.overall_insights.map((insight, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                    <span className="text-purple-600 mt-1">•</span>
                    <span>{insight}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.ai_insights.industry_trends && data.ai_insights.industry_trends.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-2">Industry Trends:</h4>
              <ul className="space-y-2">
                {data.ai_insights.industry_trends.map((trend, idx) => (
                  <li key={idx} className="flex items-start gap-2 text-sm text-gray-700">
                    <BarChart3 className="h-4 w-4 text-blue-600 mt-0.5" />
                    <span>{trend}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Product Performance List */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b border-gray-200">
          <h3 className="text-lg font-semibold text-gray-900">Product Performance Analysis</h3>
          <p className="text-sm text-gray-600 mt-1">
            Detailed performance metrics with industry benchmarks
          </p>
        </div>

        <div className="p-6 space-y-4">
          {data.products.map((product, index) => {
            const colors = PERFORMANCE_COLORS[product.performance_status];
            const isExpanded = expandedProduct === product.product_name;
            const recommendation = data.ai_insights?.product_recommendations?.find(
              r => r.product_name === product.product_name
            );

            return (
              <div
                key={index}
                className={`border-2 rounded-lg p-5 transition-all ${colors.border} ${colors.bg}`}
              >
                {/* Product Header */}
                <div className="flex items-start justify-between mb-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <h4 className="text-lg font-bold text-gray-900">{product.product_name}</h4>
                      <span className={`px-3 py-1 rounded-full text-xs font-semibold ${colors.badge}`}>
                        {product.performance_status.toUpperCase()}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-sm text-gray-600">
                      <span className="flex items-center gap-1">
                        <Package className="h-4 w-4" />
                        {product.industry}
                      </span>
                      <span className="flex items-center gap-1">
                        {getTrendIcon(product.trend)}
                        {product.trend}
                      </span>
                      <span className="font-medium">{product.metrics.price_position} Pricing</span>
                    </div>
                  </div>
                  <button
                    onClick={() => setExpandedProduct(isExpanded ? null : product.product_name)}
                    className="p-2 hover:bg-white rounded-md transition-colors"
                  >
                    {isExpanded ? (
                      <ChevronUp className="h-5 w-5 text-gray-600" />
                    ) : (
                      <ChevronDown className="h-5 w-5 text-gray-600" />
                    )}
                  </button>
                </div>

                {/* Key Metrics Grid */}
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-4">
                  <div>
                    <div className="text-xs text-gray-600 mb-1">Avg Price</div>
                    <div className="text-lg font-bold text-gray-900">
                      ${product.metrics.avg_price.toFixed(2)}
                    </div>
                    <div className={`text-xs ${product.benchmarks.price_diff_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {product.benchmarks.price_diff_pct > 0 ? '+' : ''}
                      {product.benchmarks.price_diff_pct.toFixed(1)}% vs industry
                    </div>
                  </div>

                  <div>
                    <div className="text-xs text-gray-600 mb-1">Order Count</div>
                    <div className="text-lg font-bold text-gray-900">{product.metrics.order_count}</div>
                    <div className="text-xs text-gray-600">invoices</div>
                  </div>

                  <div>
                    <div className="text-xs text-gray-600 mb-1">Total Quantity</div>
                    <div className="text-lg font-bold text-gray-900">
                      {product.metrics.total_quantity.toFixed(0)}
                    </div>
                    <div className="text-xs text-gray-600">units sold</div>
                  </div>

                  <div>
                    <div className="text-xs text-gray-600 mb-1">Total Revenue</div>
                    <div className="text-lg font-bold text-gray-900">
                      ${product.metrics.total_revenue.toLocaleString()}
                    </div>
                    <div className={`text-xs ${product.benchmarks.revenue_diff_pct >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                      {product.benchmarks.revenue_diff_pct > 0 ? '+' : ''}
                      {product.benchmarks.revenue_diff_pct.toFixed(1)}% vs industry
                    </div>
                  </div>
                </div>

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="border-t-2 border-gray-200 pt-4 mt-4 space-y-4">
                    {/* Industry Benchmark Comparison */}
                    <div>
                      <h5 className="text-sm font-semibold text-gray-700 mb-3">Industry Benchmark Comparison</h5>
                      <div className="grid grid-cols-2 gap-4 bg-white bg-opacity-70 rounded-lg p-4">
                        <div>
                          <div className="text-xs text-gray-600 mb-1">Your Avg Price</div>
                          <div className="text-xl font-bold text-gray-900">
                            ${product.metrics.avg_price.toFixed(2)}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs text-gray-600 mb-1">Industry Avg Price</div>
                          <div className="text-xl font-bold text-gray-900">
                            ${product.benchmarks.industry_avg_price.toFixed(2)}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* AI Recommendation */}
                    {recommendation && (
                      <div className="bg-white bg-opacity-70 rounded-lg p-4 border-l-4 border-purple-500">
                        <div className="flex items-start gap-3">
                          <Lightbulb className="h-5 w-5 text-purple-600 mt-0.5" />
                          <div className="flex-1">
                            <h5 className="text-sm font-semibold text-gray-900 mb-2">AI Recommendation</h5>
                            <div className="space-y-2 text-sm">
                              <div>
                                <span className="font-medium text-gray-700">Issue:</span>{' '}
                                <span className="text-gray-600">{recommendation.issue}</span>
                              </div>
                              <div>
                                <span className="font-medium text-gray-700">Recommendation:</span>{' '}
                                <span className="text-gray-600">{recommendation.recommendation}</span>
                              </div>
                              <div>
                                <span className="font-medium text-gray-700">Expected Impact:</span>{' '}
                                <span className="text-gray-600">{recommendation.expected_impact}</span>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

