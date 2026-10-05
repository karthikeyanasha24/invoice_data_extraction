'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Invoice } from '@/types';
import { 
  FileText, 
  TrendingUp, 
  CheckCircle, 
  XCircle
} from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';

export default function DashboardLanding() {
  const { user, isAuthenticated, handleAuthError } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [deletedInvoices, setDeletedInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (isAuthenticated) {
      fetchData();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated]);

  const fetchData = async () => {
    try {
      const [invoicesData, deletedData] = await Promise.all([
        fileApi.getFiles(),
        fileApi.getDeletedFiles()
      ]);
      
      setInvoices(invoicesData);
      setDeletedInvoices(deletedData);
    } catch (error: any) {
      console.error('Failed to fetch dashboard data:', error);
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  };

  const stats = {
    totalFiles: invoices.filter(inv => inv.status !== 'deleted').length,
    completed: invoices.filter(inv => inv.status && (inv.status.toLowerCase() === 'successful' || inv.status.toLowerCase() === 'completed')).length,
    processing: invoices.filter(inv => inv.status && inv.status.toLowerCase() === 'processing').length,
    failed: invoices.filter(inv => inv.status && (inv.status.toLowerCase() === 'failed' || inv.status.toLowerCase() === 'error')).length,
    deleted: deletedInvoices.length,
  };

  const recentInvoices = invoices.filter(inv => inv.status !== 'deleted').slice(0, 5);

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Authentication Required</h3>
          <p className="text-gray-500">Please log in to view your dashboard.</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" text="Loading dashboard..." />
      </div>
    );
  }

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Welcome Section */}
      <div className="bg-gradient-to-r from-blue-600 to-purple-600 rounded-lg p-4 sm:p-6 text-white">
        <h1 className="text-xl sm:text-2xl font-bold mb-2">Welcome back, {user?.username}!</h1>
        <p className="text-sm sm:text-base text-blue-100">Here's what's happening with your invoices today.</p>
      </div>

      {/* Combined Analytics and Performance Overview */}
      <div className="bg-white rounded-lg shadow p-4 sm:p-6">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 sm:mb-6 space-y-2 sm:space-y-0">
          <h3 className="text-base sm:text-lg font-semibold text-gray-900">Performance Overview</h3>
          <div className="flex items-center space-x-2">
            <TrendingUp className="h-4 w-4 sm:h-5 sm:w-5 text-blue-500" />
            <span className="text-xs sm:text-sm text-gray-500">Real-time data</span>
          </div>
        </div>

        {/* Performance Metrics */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3 sm:gap-4 lg:gap-6">
          <div className="text-center bg-gradient-to-br from-green-50 to-green-100 rounded-lg p-4 sm:p-6 border border-green-200">
            <div className="text-3xl sm:text-4xl font-bold text-green-600 mb-2">{stats.completed}</div>
            <div className="text-base sm:text-lg font-medium text-green-700 mb-1">Success Rate</div>
            <div className="text-xs sm:text-sm text-green-600">
              {stats.totalFiles > 0 ? Math.round((stats.completed / stats.totalFiles) * 100) : 0}% of total files
            </div>
          </div>
          <div className="text-center bg-gradient-to-br from-red-50 to-red-100 rounded-lg p-4 sm:p-6 border border-red-200">
            <div className="text-3xl sm:text-4xl font-bold text-red-600 mb-2">{stats.failed}</div>
            <div className="text-base sm:text-lg font-medium text-red-700 mb-1">Failed Files</div>
            <div className="text-xs sm:text-sm text-red-600">
              {stats.totalFiles > 0 ? Math.round((stats.failed / stats.totalFiles) * 100) : 0}% of total files
            </div>
          </div>
          <div className="text-center bg-gradient-to-br from-blue-50 to-blue-100 rounded-lg p-4 sm:p-6 border border-blue-200 sm:col-span-2 lg:col-span-1">
            <div className="text-3xl sm:text-4xl font-bold text-blue-600 mb-2">{stats.processing}</div>
            <div className="text-base sm:text-lg font-medium text-blue-700 mb-1">In Progress</div>
            <div className="text-xs sm:text-sm text-blue-600">Currently processing</div>
          </div>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="bg-white rounded-lg shadow p-4 sm:p-6">
        <h3 className="text-base sm:text-lg font-semibold text-gray-900 mb-4">Recent Activity</h3>
        {recentInvoices.length === 0 ? (
          <div className="text-center py-8 text-gray-500">
            <FileText className="mx-auto h-10 w-10 sm:h-12 sm:w-12 text-gray-400 mb-4" />
            <p className="text-sm sm:text-base">No recent activity</p>
            <p className="text-xs sm:text-sm">Upload your first document to get started</p>
          </div>
        ) : (
          <div className="space-y-3">
            {recentInvoices.map((invoice, index) => (
              <div key={invoice.id || `recent-${index}`} className="flex flex-col sm:flex-row sm:items-center sm:justify-between py-2 border-b border-gray-200 last:border-b-0 space-y-2 sm:space-y-0">
                <div className="flex items-center space-x-3 min-w-0 flex-1">
                  <FileText className="h-5 w-5 text-gray-400 flex-shrink-0" />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-medium text-gray-900 truncate">{invoice.filename}</p>
                    <p className="text-xs text-gray-500 truncate">{invoice.customerName || 'No customer'}</p>
                  </div>
                </div>
                <span className={cn(
                  "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium self-start sm:self-auto flex-shrink-0",
                  invoice.status === 'successful' || invoice.status === 'completed' 
                    ? "bg-green-100 text-green-800"
                    : invoice.status === 'processing'
                    ? "bg-yellow-100 text-yellow-800"
                    : invoice.status === 'failed' || invoice.status === 'error'
                    ? "bg-red-100 text-red-800"
                    : "bg-gray-100 text-gray-800"
                )}>
                  {invoice.status || 'Unknown'}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
