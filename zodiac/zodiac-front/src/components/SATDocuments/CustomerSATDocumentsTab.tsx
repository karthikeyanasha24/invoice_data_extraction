'use client';

import { useState, useEffect } from 'react';
import { satApi } from '@/lib/api';
import {
  RefreshCw,
  FileText,
  Calendar,
  Building2,
  DollarSign,
} from 'lucide-react';
import { format } from 'date-fns';

interface SATDocument {
  id: string;
  doc_type?: string;
  supplier_rfc?: string;
  supplier_name?: string;
  receiver_rfc?: string;
  serie?: string;
  folio?: string;
  fecha?: string;
  total?: string;
  moneda?: string;
  status?: string;
  received_at?: string;
}

export default function CustomerSATDocumentsTab() {
  const [documents, setDocuments] = useState<SATDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [docTypeFilter, setDocTypeFilter] = useState<string>('');

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await satApi.listDocumentsForCustomerUser({
        doc_type: docTypeFilter || undefined,
        limit: 500,
      });
      setDocuments(response.documents || []);
      setTotalCount(response.total ?? 0);
    } catch (err: any) {
      setError(err.message || 'Failed to fetch documents.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [docTypeFilter]);

  const formatCurrency = (amount: string, currency: string = 'MXN') => {
    try {
      const num = parseFloat(amount);
      return new Intl.NumberFormat('es-MX', { style: 'currency', currency }).format(num);
    } catch {
      return amount;
    }
  };

  const getDocTypeBadge = (docType: string) => {
    const styles: Record<string, string> = {
      INVOICE: 'bg-green-100 text-green-800',
      PAYMENT: 'bg-blue-100 text-blue-800',
      CREDIT_NOTE: 'bg-orange-100 text-orange-800',
    };
    return styles[docType] || 'bg-gray-100 text-gray-800';
  };

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      RECEIVED: 'bg-gray-100 text-gray-800',
      VALIDATED: 'bg-blue-100 text-blue-800',
      MERGED: 'bg-purple-100 text-purple-800',
      SAP_SENT: 'bg-green-100 text-green-800',
    };
    return styles[status] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        CFDI documents for your assigned receiver RFC(s). Upload and receive are managed by your administrator.
      </p>
      <div className="flex flex-col sm:flex-row gap-4">
        <label className="block">
          <span className="text-sm font-medium text-gray-700">Document type</span>
          <select
            value={docTypeFilter}
            onChange={(e) => setDocTypeFilter(e.target.value)}
            className="mt-1 block w-full sm:w-auto px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All</option>
            <option value="INVOICE">Invoice</option>
            <option value="PAYMENT">Payment</option>
            <option value="CREDIT_NOTE">Credit Note</option>
          </select>
        </label>
        <div className="flex items-end">
          <button
            type="button"
            onClick={() => fetchDocuments()}
            className="inline-flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            <RefreshCw className="h-4 w-4" />
            Refresh
          </button>
        </div>
      </div>
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-800 text-sm">{error}</div>
      )}
      <div className="bg-white rounded-lg shadow border border-gray-200 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No documents</h3>
            <p className="text-gray-600">No SAT documents found for your assigned customers.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Info</th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Supplier</th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Date</th>
                  <th className="px-4 sm:px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase">Amount</th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Type</th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-4 sm:px-6 py-4">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">{doc.serie || 'N/A'}-{doc.folio || 'N/A'}</div>
                          <div className="text-xs text-gray-500 font-mono truncate max-w-[120px]">{doc.id?.slice(0, 8)}...</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4">
                      <div>
                        <div className="text-sm font-medium text-gray-900">{doc.supplier_rfc}</div>
                        <div className="text-xs text-gray-500">{doc.supplier_name || 'N/A'}</div>
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 text-sm text-gray-900">
                      {doc.fecha ? format(new Date(doc.fecha), 'yyyy-MM-dd') : 'N/A'}
                    </td>
                    <td className="px-4 sm:px-6 py-4 text-sm text-right font-medium text-gray-900">
                      {formatCurrency(doc.total || '0', doc.moneda || 'MXN')}
                    </td>
                    <td className="px-4 sm:px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getDocTypeBadge(doc.doc_type || '')}`}>
                        {doc.doc_type || 'N/A'}
                      </span>
                    </td>
                    <td className="px-4 sm:px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(doc.status || '')}`}>
                        {doc.status || 'N/A'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
