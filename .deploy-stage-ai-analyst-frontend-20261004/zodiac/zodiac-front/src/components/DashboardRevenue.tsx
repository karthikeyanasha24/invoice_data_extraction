'use client';

import { useState, useEffect } from 'react';
import {
  DollarSign,
  Globe,
  Calendar,
  TrendingUp,
  RefreshCw,
  Loader2
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
import { dashboardApi } from '@/lib/api';
import LoadingSpinner from './LoadingSpinner';

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899'];
const SEASON_COLORS: Record<string, string> = {
  'Spring': '#10b981',
  'Summer': '#f59e0b',
  'Fall': '#ef4444',
  'Winter': '#3b82f6'
};

/** Recharts `Pie` `data` rows must be indexable by string */
interface SeasonBreakdownRow {
  season: string;
  revenue: number;
  invoice_count: number;
  [key: string]: string | number;
}

interface RevenueData {
  by_country: Array<{
    country: string;
    revenue: number;
    invoice_count: number;
  }>;
  by_season: SeasonBreakdownRow[];
  by_quarter: Array<{
    quarter: string;
    year: number;
    revenue: number;
    invoice_count: number;
  }>;
  period_days: number;
}

interface ProductDemandData {
  trending_products: Array<{
    name: string;
    trend: string;
    monthly_growth: number;
    total_quantity: number;
    total_revenue: number;
    order_count: number;
    customer_count: number;
    top_customers: string[];
    top_countries: string[];
  }>;
  customer_preferences: Array<{
    customer_name: string;
    favorite_products: string[];
    purchase_frequency: string;
    total_purchases: number;
  }>;
  period_days: number;
}

export default function DashboardRevenue() {
  const [loading, setLoading] = useState(true);
  const [revenueData, setRevenueData] = useState<RevenueData | null>(null);
  const [productDemand, setProductDemand] = useState<ProductDemandData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState(90);

  useEffect(() => {
    fetchRevenueData();
  }, [timeRange]);

  const fetchRevenueData = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const [revenue, demand] = await Promise.all([
        dashboardApi.getRevenueAnalysis(timeRange),
        dashboardApi.getProductDemand(timeRange)
      ]);
      
      setRevenueData(revenue);
      setProductDemand(demand);
    } catch (err: any) {
      console.error('Failed to fetch revenue data:', err);
      setError(err.message || 'Failed to load revenue analytics');
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <LoadingSpinner size="lg" text="Loading revenue analytics..." />
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6">
        <h3 className="text-lg font-semibold text-red-900 mb-2">Error Loading Revenue Analytics</h3>
        <p className="text-red-700">{error}</p>
        <button
          onClick={fetchRevenueData}
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!revenueData || !productDemand) {
    return (
      <div className="text-center py-12 text-gray-500">
        <DollarSign className="h-16 w-16 mx-auto mb-4 text-gray-300" />
        <p className="text-lg font-medium mb-2">No Revenue Data Available</p>
        <p className="text-sm">Process Invoice V2 invoices to see revenue analytics</p>
      </div>
    );
  }

  const totalRevenue = revenueData.by_country.reduce((sum, c) => sum + c.revenue, 0);
  const totalInvoices = revenueData.by_country.reduce((sum, c) => sum + c.invoice_count, 0);
  const avgRevenuePerInvoice = totalInvoices > 0 ? totalRevenue / totalInvoices : 0;

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Revenue Analytics</h2>
          <p className="text-sm text-gray-600 mt-1">
            Track revenue by country, season, and product trends
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={timeRange}
            onChange={(e) => setTimeRange(Number(e.target.value))}
            className="px-3 py-2 border border-gray-300 rounded-md bg-white text-sm"
          >
            <option value={30}>Last 30 Days</option>
            <option value={60}>Last 60 Days</option>
            <option value={90}>Last 90 Days</option>
            <option value={180}>Last 6 Months</option>
            <option value={365}>Last Year</option>
          </select>
          <button
            onClick={fetchRevenueData}
            className="p-2 bg-white border border-gray-300 rounded-md hover:bg-gray-50"
          >
            <RefreshCw className="h-5 w-5 text-gray-600" />
          </button>
        </div>
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Total Revenue</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">
                ${totalRevenue.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </p>
            </div>
            <div className="p-3 bg-green-100 rounded-full">
              <DollarSign className="h-6 w-6 text-green-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Total Invoices</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">{totalInvoices}</p>
            </div>
            <div className="p-3 bg-blue-100 rounded-full">
              <Calendar className="h-6 w-6 text-blue-600" />
            </div>
          </div>
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm font-medium text-gray-600">Avg per Invoice</p>
              <p className="text-3xl font-bold text-gray-900 mt-2">
                ${avgRevenuePerInvoice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </p>
            </div>
            <div className="p-3 bg-purple-100 rounded-full">
              <TrendingUp className="h-6 w-6 text-purple-600" />
            </div>
          </div>
        </div>
      </div>

      {/* Revenue by Country */}
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Globe className="h-5 w-5 text-blue-600" />
          Revenue by Country
        </h3>
        <div className="h-80">
          {revenueData.by_country.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={revenueData.by_country}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="country"
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                />
                <YAxis
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                  tickFormatter={(value) => `$${value.toLocaleString()}`}
                />
                <Tooltip
                  formatter={(value: any) => [`$${value.toLocaleString()}`, 'Revenue']}
                  contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb' }}
                />
                <Bar dataKey="revenue" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-full text-gray-500">
              No country data available
            </div>
          )}
        </div>
      </div>

      {/* Revenue by Season */}
      {revenueData.by_season.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Revenue by Season
          </h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={revenueData.by_season}
                  dataKey="revenue"
                  nameKey="season"
                  cx="50%"
                  cy="50%"
                  outerRadius={100}
                  label={(props: { payload?: SeasonBreakdownRow }) => {
                    const p = props.payload;
                    return p ? `${p.season}: $${p.revenue.toLocaleString()}` : '';
                  }}
                >
                  {revenueData.by_season.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={SEASON_COLORS[entry.season] || CHART_COLORS[index % CHART_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(value: any) => `$${value.toLocaleString()}`} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Revenue by Quarter */}
      {revenueData.by_quarter.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Revenue by Fiscal Quarter
          </h3>
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={revenueData.by_quarter}>
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis
                  dataKey="quarter"
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                  tickFormatter={(value, index) => {
                    const item = revenueData.by_quarter[index];
                    return `${value} ${item.year}`;
                  }}
                />
                <YAxis
                  stroke="#6b7280"
                  tick={{ fill: '#6b7280', fontSize: 12 }}
                  tickFormatter={(value) => `$${value.toLocaleString()}`}
                />
                <Tooltip
                  formatter={(value: any) => [`$${value.toLocaleString()}`, 'Revenue']}
                  contentStyle={{ backgroundColor: '#fff', border: '1px solid #e5e7eb' }}
                />
                <Line type="monotone" dataKey="revenue" stroke="#8b5cf6" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Trending Products */}
      {productDemand.trending_products.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Top Trending Products
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {productDemand.trending_products.slice(0, 6).map((product, index) => (
              <div key={index} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-gray-900 truncate">{product.name}</h4>
                  <span className={`text-xs px-2 py-1 rounded ${
                    product.trend === 'increasing' ? 'bg-green-100 text-green-700' :
                    product.trend === 'decreasing' ? 'bg-red-100 text-red-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {product.trend}
                  </span>
                </div>
                <div className="space-y-1 text-sm text-gray-600">
                  <p>Revenue: ${product.total_revenue.toLocaleString()}</p>
                  <p>Orders: {product.order_count}</p>
                  <p>Customers: {product.customer_count}</p>
                  {product.monthly_growth !== 0 && (
                    <p className={product.monthly_growth > 0 ? 'text-green-600' : 'text-red-600'}>
                      Growth: {product.monthly_growth > 0 ? '+' : ''}{product.monthly_growth.toFixed(1)}%
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Customer Preferences */}
      {productDemand.customer_preferences.length > 0 && (
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            Top Customer Preferences
          </h3>
          <div className="space-y-3">
            {productDemand.customer_preferences.slice(0, 10).map((customer, index) => (
              <div key={index} className="border border-gray-200 rounded-lg p-4">
                <div className="flex items-center justify-between mb-2">
                  <h4 className="font-semibold text-gray-900">{customer.customer_name}</h4>
                  <span className="text-xs px-2 py-1 bg-blue-100 text-blue-700 rounded">
                    {customer.purchase_frequency}
                  </span>
                </div>
                <div className="text-sm text-gray-600">
                  <p className="mb-1">Favorite Products:</p>
                  <div className="flex flex-wrap gap-1">
                    {customer.favorite_products.map((product, i) => (
                      <span key={i} className="px-2 py-1 bg-gray-100 text-gray-700 rounded text-xs">
                        {product}
                      </span>
                    ))}
                  </div>
                  <p className="mt-2">Total Purchases: {customer.total_purchases}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
