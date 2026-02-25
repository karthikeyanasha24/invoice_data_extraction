'use client';

import { useState, useEffect } from 'react';
import { convertedInvoicesApi } from '@/lib/api';
import {
  Download,
  FileText,
  AlertCircle,
  CheckCircle,
  XCircle,
  Loader,
  RefreshCw,
  Calendar,
  FileType,
  Trash2,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface ConvertedInvoice {
  id: number;
  validated_invoice_id: number;
  customer_id: string | null;
  target_format: string;
  conversion_status: string;
  conversion_notes: string | null;
  validation_overridden: boolean;
  converted_at: string;
}

const FORMAT_COLORS: Record<string, { bg: string; text: string }> = {
  X12: { bg: 'bg-orange-100', text: 'text-orange-800' },
  EDIFACT: { bg: 'bg-purple-100', text: 'text-purple-800' },
  PDF: { bg: 'bg-red-100', text: 'text-red-800' },
  XML: { bg: 'bg-blue-100', text: 'text-blue-800' },
  UBL: { bg: 'bg-green-100', text: 'text-green-800' },
  PIDX: { bg: 'bg-yellow-100', text: 'text-yellow-800' },
  CFDI: { bg: 'bg-pink-100', text: 'text-pink-800' },
};

interface ConvertedInvoicesTabProps {
  customerUserMode?: boolean;
}

export default function ConvertedInvoicesTab({ customerUserMode }: ConvertedInvoicesTabProps = {}) {
  const [convertedInvoices, setConvertedInvoices] = useState<ConvertedInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [downloading, setDownloading] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<number | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>('');

  useEffect(() => {
    fetchConvertedInvoices();
  }, [statusFilter, customerUserMode]);

  const fetchConvertedInvoices = async () => {
    setLoading(true);
    setError('');

    try {
      const response = customerUserMode
        ? await convertedInvoicesApi.getConvertedForCustomerUser(0, 100, statusFilter || undefined)
        : await convertedInvoicesApi.getConverted(0, 100, statusFilter || undefined);
      setConvertedInvoices(response.converted_invoices || []);
    } catch (err: any) {
      setError(err.message || 'Failed to load converted invoices');
      setConvertedInvoices([]);
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async (convertedId: number) => {
    setDownloading(convertedId);
    setError('');

    try {
      await convertedInvoicesApi.downloadConverted(convertedId);
    } catch (err: any) {
      setError(`Download failed: ${err.message}`);
    } finally {
      setDownloading(null);
    }
  };

  const handleDelete = async (convertedId: number) => {
    if (!confirm('Are you sure you want to delete this converted invoice? This action cannot be undone.')) {
      return;
    }

    setDeleting(convertedId);
    setError('');

    try {
      await convertedInvoicesApi.deleteConverted(convertedId);
      // Refresh the list after successful deletion
      await fetchConvertedInvoices();
    } catch (err: any) {
      setError(`Delete failed: ${err.message}`);
    } finally {
      setDeleting(null);
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Converted Invoices</h2>
          <p className="text-gray-600 mt-1">
            Download converted invoices in customer-specific formats
          </p>
        </div>

        <button
          onClick={fetchConvertedInvoices}
          disabled={loading}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          <RefreshCw className={cn('w-4 h-4', loading && 'animate-spin')} />
          Refresh
        </button>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-semibold text-red-900">Error</p>
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Status Filter */}
      <div className="flex items-center gap-4">
        <label className="text-sm font-medium text-gray-700">Filter by status:</label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All</option>
          <option value="success">Success</option>
          <option value="failed">Failed</option>
        </select>
      </div>

      {/* Table */}
      {loading ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 flex items-center justify-center">
          <Loader className="w-8 h-8 text-blue-600 animate-spin" />
        </div>
      ) : convertedInvoices.length === 0 ? (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12 text-center">
          <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <p className="text-gray-600 text-lg font-medium mb-2">No Converted Invoices</p>
          <p className="text-gray-500 text-sm">
            Converted invoices will appear here after successful processing
          </p>
        </div>
      ) : (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Customer ID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Target Format
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Converted Date
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {convertedInvoices.map((invoice) => {
                  const formatColor = FORMAT_COLORS[invoice.target_format] || FORMAT_COLORS.XML;

                  return (
                    <tr key={invoice.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        #{invoice.id}
                      </td>

                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                        {invoice.customer_id || '—'}
                      </td>

                      <td className="px-6 py-4 whitespace-nowrap">
                        <span
                          className={cn(
                            'inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium',
                            formatColor.bg,
                            formatColor.text
                          )}
                        >
                          <FileType className="w-3 h-3" />
                          {invoice.target_format}
                        </span>
                      </td>

                      <td className="px-6 py-4 whitespace-nowrap">
                        {invoice.conversion_status === 'success' ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                            <CheckCircle className="w-3 h-3" />
                            Success
                          </span>
                        ) : invoice.conversion_status === 'failed' ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-red-100 text-red-800">
                            <XCircle className="w-3 h-3" />
                            Failed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                            <Loader className="w-3 h-3" />
                            {invoice.conversion_status}
                          </span>
                        )}
                      </td>

                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-700">
                        <div className="flex items-center gap-1">
                          <Calendar className="w-4 h-4 text-gray-400" />
                          {formatDate(invoice.converted_at)}
                        </div>
                      </td>

                      <td className="px-6 py-4 whitespace-nowrap text-sm">
                        <div className="flex items-center gap-2">
                          {invoice.conversion_status === 'success' && (
                            <>
                              <button
                                onClick={() => handleDownload(invoice.id)}
                                disabled={downloading === invoice.id || deleting === invoice.id}
                                className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium"
                              >
                                {downloading === invoice.id ? (
                                  <>
                                    <Loader className="w-3 h-3 animate-spin" />
                                    Downloading...
                                  </>
                                ) : (
                                  <>
                                    <Download className="w-3 h-3" />
                                    Download
                                  </>
                                )}
                              </button>
                              
                              <button
                                onClick={() => handleDelete(invoice.id)}
                                disabled={deleting === invoice.id || downloading === invoice.id}
                                className="flex items-center gap-1 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium"
                                title="Delete converted invoice"
                              >
                                {deleting === invoice.id ? (
                                  <>
                                    <Loader className="w-3 h-3 animate-spin" />
                                    Deleting...
                                  </>
                                ) : (
                                  <>
                                    <Trash2 className="w-3 h-3" />
                                    Delete
                                  </>
                                )}
                              </button>
                            </>
                          )}

                          {invoice.conversion_status === 'failed' && (
                            <>
                              {invoice.conversion_notes && (
                                <div className="text-xs text-red-600" title={invoice.conversion_notes}>
                                  Error: {invoice.conversion_notes.substring(0, 30)}...
                                </div>
                              )}
                              
                              <button
                                onClick={() => handleDelete(invoice.id)}
                                disabled={deleting === invoice.id}
                                className="flex items-center gap-1 px-3 py-1.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium"
                                title="Delete failed conversion"
                              >
                                {deleting === invoice.id ? (
                                  <>
                                    <Loader className="w-3 h-3 animate-spin" />
                                    Deleting...
                                  </>
                                ) : (
                                  <>
                                    <Trash2 className="w-3 h-3" />
                                    Delete
                                  </>
                                )}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Summary Footer */}
          <div className="bg-gray-50 px-6 py-4 border-t border-gray-200">
            <p className="text-sm text-gray-700">
              Total: <span className="font-semibold">{convertedInvoices.length}</span> converted invoice(s)
              {statusFilter && ` with status "${statusFilter}"`}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
