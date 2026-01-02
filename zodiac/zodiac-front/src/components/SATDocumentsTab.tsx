'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { satApi } from '@/lib/api';
import {
  RefreshCw,
  FileText,
  Calendar,
  Building2,
  DollarSign,
  CheckCircle,
  XCircle,
  Eye
} from 'lucide-react';
import { format } from 'date-fns';

interface SATDocument {
  id: string;
  portal_ref_id: string;
  cfdi_uuid: string;
  doc_type: string;
  supplier_rfc: string;
  supplier_name: string;
  receiver_rfc: string;
  receiver_name: string;
  serie: string;
  folio: string;
  fecha: string;
  total: string;
  moneda: string;
  status: string;
  fiscal_year: number;
  fiscal_period: number;
  received_at: string;
}

export default function SATDocumentsTab() {
  const router = useRouter();
  const [documents, setDocuments] = useState<SATDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);

  // Filters
  const [docTypeFilter, setDocTypeFilter] = useState<string>('');

  useEffect(() => {
    fetchDocuments();
  }, [docTypeFilter]);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await satApi.list(
        undefined,
        undefined,
        docTypeFilter || undefined,
        undefined
      );
      
      setDocuments(response.documents || []);
      setTotalCount(response.total || 0);
    } catch (err: any) {
      console.error('Error fetching documents:', err);
      setError(err.message || 'Failed to fetch documents.');
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount: string, currency: string = 'MXN') => {
    try {
      const num = parseFloat(amount);
      return new Intl.NumberFormat('es-MX', {
        style: 'currency',
        currency: currency,
      }).format(num);
    } catch {
      return amount;
    }
  };

  const getDocTypeBadge = (docType: string) => {
    const styles = {
      INVOICE: 'bg-green-100 text-green-800',
      PAYMENT: 'bg-blue-100 text-blue-800',
      CREDIT_NOTE: 'bg-orange-100 text-orange-800',
    };
    return styles[docType as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      RECEIVED: 'bg-gray-100 text-gray-800',
      VALIDATED: 'bg-blue-100 text-blue-800',
      MERGED: 'bg-purple-100 text-purple-800',
      SAP_SENT: 'bg-green-100 text-green-800',
    };
    return styles[status as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Filters</h2>
          <button
            onClick={fetchDocuments}
            className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Document Type
            </label>
            <select
              value={docTypeFilter}
              onChange={(e) => setDocTypeFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Types</option>
              <option value="INVOICE">Invoice</option>
              <option value="PAYMENT">Payment</option>
              <option value="CREDIT_NOTE">Credit Note</option>
            </select>
          </div>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Documents List */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-xl font-semibold text-gray-900">
            SAT Documents ({totalCount})
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Individual CFDI documents received from suppliers
          </p>
        </div>

        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Documents</h3>
            <p className="text-gray-600">
              No SAT documents found. Upload CFDI documents to get started.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Document Info
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Supplier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Date
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.serie || 'N/A'}-{doc.folio || 'N/A'}
                          </div>
                          <div className="text-xs text-gray-500 font-mono">
                            {doc.cfdi_uuid.substring(0, 8)}...
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Building2 className="w-4 h-4 text-gray-400" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.supplier_rfc}
                          </div>
                          <div className="text-xs text-gray-500">
                            {doc.supplier_name || 'N/A'}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4 text-gray-400" />
                        {doc.fecha ? format(new Date(doc.fecha), 'yyyy-MM-dd') : 'N/A'}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-right font-medium text-gray-900">
                      {formatCurrency(doc.total, doc.moneda)}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getDocTypeBadge(doc.doc_type)}`}>
                        {doc.doc_type}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(doc.status)}`}>
                        {doc.status}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <button
                        onClick={() => router.push(`/sat-documents/${doc.id}`)}
                        className="inline-flex items-center gap-1 px-3 py-1 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors"
                      >
                        <Eye className="w-4 h-4" />
                        Details
                      </button>
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

