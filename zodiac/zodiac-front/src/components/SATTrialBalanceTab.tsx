'use client';

import React, { useState, useEffect } from 'react';
import { satTrialBalanceApi } from '@/lib/api';
import { 
  TrendingUp, 
  RefreshCw, 
  Send, 
  CheckCircle, 
  XCircle, 
  Clock,
  FileText,
  AlertCircle
} from 'lucide-react';

interface TrialBalance {
  id: string;
  company_code: string;
  fiscal_year: number;
  fiscal_period: number;
  vendor_rfc: string;
  vendor_name: string | null;
  total_invoices: string;
  total_credits: string;
  total_payments: string;
  net_balance: string;
  currency: string;
  document_count: number;
  status: string;
  sap_document_number: string | null;
  merged_at: string | null;
  sent_to_sap_at: string | null;
}

export default function SATTrialBalanceTab() {
  const [trialBalances, setTrialBalances] = useState<TrialBalance[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [merging, setMerging] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);

  // Filters
  const [yearFilter, setYearFilter] = useState<number>(new Date().getFullYear());
  const [periodFilter, setPeriodFilter] = useState<number>(new Date().getMonth() + 1);

  useEffect(() => {
    fetchTrialBalances();
  }, [yearFilter, periodFilter]);

  const fetchTrialBalances = async () => {
    try {
      setLoading(true);
      setError(null);

      const response = await satTrialBalanceApi.list({
        fiscal_year: yearFilter,
        fiscal_period: periodFilter
      });

      setTrialBalances(response.trial_balances || []);
      setTotalCount(response.total || 0);
    } catch (err: any) {
      console.error('Error fetching trial balances:', err);
      setError(err.message || 'Failed to load trial balances');
    } finally {
      setLoading(false);
    }
  };

  const handleMerge = async () => {
    try {
      setMerging(true);
      setError(null);

      await satTrialBalanceApi.merge({
        company_code: 'MX01',
        fiscal_year: yearFilter,
        fiscal_period: periodFilter
      });

      // Refresh data
      await fetchTrialBalances();
    } catch (err: any) {
      console.error('Error merging documents:', err);
      setError(err.message || 'Failed to merge documents');
    } finally {
      setMerging(false);
    }
  };

  const handleSendToSAP = async (trialBalanceId: string) => {
    try {
      setSendingId(trialBalanceId);
      setError(null);

      await satTrialBalanceApi.sendToSAP(trialBalanceId);

      // Refresh data
      await fetchTrialBalances();
    } catch (err: any) {
      console.error('Error sending to SAP:', err);
      setError(err.message || 'Failed to send to SAP');
    } finally {
      setSendingId(null);
    }
  };

  const getStatusBadge = (status: string) => {
    const config: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
      'CONFIRMED': { bg: 'bg-green-100 text-green-800', text: 'SAP Confirmed', icon: <CheckCircle className="h-4 w-4" /> },
      'SENT': { bg: 'bg-blue-100 text-blue-800', text: 'Sent to SAP', icon: <Clock className="h-4 w-4" /> },
      'READY': { bg: 'bg-purple-100 text-purple-800', text: 'Ready', icon: <CheckCircle className="h-4 w-4" /> },
      'DRAFT': { bg: 'bg-gray-100 text-gray-800', text: 'Draft', icon: <FileText className="h-4 w-4" /> },
      'FAILED': { bg: 'bg-red-100 text-red-800', text: 'Failed', icon: <XCircle className="h-4 w-4" /> }
    };

    const { bg, text, icon } = config[status] || config['DRAFT'];

    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${bg}`}>
        {icon}
        {text}
      </span>
    );
  };

  const formatAmount = (amount: string, currency: string) => {
    const num = parseFloat(amount);
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency,
      minimumFractionDigits: 2
    }).format(num);
  };

  return (
    <div className="space-y-6">
      {/* Header with actions */}
      <div className="bg-white p-6 rounded-lg shadow-sm border border-gray-200">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
              <TrendingUp className="h-6 w-6 text-blue-600" />
              SAT Trial Balance
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              Merged view by Vendor + Period (following SAT requirements)
            </p>
          </div>

          <button
            onClick={handleMerge}
            disabled={merging}
            className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${merging ? 'animate-spin' : ''}`} />
            {merging ? 'Merging...' : 'Generate Trial Balance'}
          </button>
        </div>

        {/* Filters */}
        <div className="flex gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Year</label>
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(parseInt(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {[2024, 2025, 2026].map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Period (Month)</label>
            <select
              value={periodFilter}
              onChange={(e) => setPeriodFilter(parseInt(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map(month => (
                <option key={month} value={month}>
                  {new Date(2000, month - 1).toLocaleString('default', { month: 'long' })}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="text-sm font-medium text-red-800">Error</h3>
            <p className="text-sm text-red-700 mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="h-8 w-8 text-blue-600 animate-spin" />
        </div>
      )}

      {/* No data */}
      {!loading && trialBalances.length === 0 && (
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <TrendingUp className="h-12 w-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No Trial Balance Data</h3>
          <p className="text-gray-600 mb-4">
            Click "Generate Trial Balance" to merge documents for {yearFilter}-{periodFilter.toString().padStart(2, '0')}
          </p>
        </div>
      )}

      {/* Trial Balance Table */}
      {!loading && trialBalances.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Vendor
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Period
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Invoices
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Credits
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Payments
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Net Balance
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {trialBalances.map((tb) => (
                  <tr key={tb.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div>
                        <div className="text-sm font-medium text-gray-900">{tb.vendor_rfc}</div>
                        <div className="text-sm text-gray-500">{tb.vendor_name || 'N/A'}</div>
                        <div className="text-xs text-gray-400">{tb.document_count} documents</div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {tb.fiscal_year}-{tb.fiscal_period.toString().padStart(2, '0')}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-green-600 font-medium">
                      {formatAmount(tb.total_invoices, tb.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-orange-600 font-medium">
                      {formatAmount(tb.total_credits, tb.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-blue-600 font-medium">
                      {formatAmount(tb.total_payments, tb.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-right font-bold">
                      <span className={parseFloat(tb.net_balance) >= 0 ? 'text-green-600' : 'text-red-600'}>
                        {formatAmount(tb.net_balance, tb.currency)}
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(tb.status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm">
                      {tb.status === 'READY' && (
                        <button
                          onClick={() => handleSendToSAP(tb.id)}
                          disabled={sendingId === tb.id}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                        >
                          <Send className={`h-3.5 w-3.5 ${sendingId === tb.id ? 'animate-pulse' : ''}`} />
                          {sendingId === tb.id ? 'Sending...' : 'Send to SAP'}
                        </button>
                      )}
                      {tb.status === 'CONFIRMED' && tb.sap_document_number && (
                        <span className="text-xs text-gray-600">
                          SAP Doc: {tb.sap_document_number}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Summary footer */}
          <div className="bg-gray-50 px-6 py-4 border-t border-gray-200">
            <div className="text-sm text-gray-600">
              Showing <span className="font-medium text-gray-900">{trialBalances.length}</span> vendor trial balances for {yearFilter}-{periodFilter.toString().padStart(2, '0')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

