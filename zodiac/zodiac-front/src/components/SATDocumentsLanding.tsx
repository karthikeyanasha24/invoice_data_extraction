'use client';

import React, { useState, useEffect } from 'react';
import { satApi } from '@/lib/api';
import { SATDocument, SATDocumentListResponse } from '@/types';
import { useRouter } from 'next/navigation';
import { 
  FileText, 
  CreditCard, 
  Receipt, 
  CheckCircle, 
  XCircle, 
  Clock, 
  AlertTriangle,
  Filter,
  RefreshCw,
  Eye
} from 'lucide-react';

export default function SATDocumentsLanding() {
  const router = useRouter();
  const [documents, setDocuments] = useState<SATDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  
  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [typeFilter, setTypeFilter] = useState<string>('');

  useEffect(() => {
    fetchDocuments();
  }, [statusFilter, typeFilter]);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const filters: any = {};
      if (statusFilter) filters.status = statusFilter;
      if (typeFilter) filters.documentType = typeFilter;
      
      const response: SATDocumentListResponse = await satApi.getDocuments(filters);
      
      if (response.documents && Array.isArray(response.documents)) {
        setDocuments(response.documents);
        setTotalCount(response.total || response.documents.length);
      } else {
        setDocuments([]);
        setTotalCount(0);
      }
    } catch (err: any) {
      console.error('Error fetching SAT documents:', err);
      setError(err.message || 'Failed to load SAT documents');
    } finally {
      setLoading(false);
    }
  };

  const getDocumentTypeIcon = (type: string) => {
    switch (type) {
      case 'INVOICE':
        return <FileText className="h-5 w-5 text-blue-600" />;
      case 'PAYMENT':
        return <CreditCard className="h-5 w-5 text-green-600" />;
      case 'CREDIT_NOTE':
        return <Receipt className="h-5 w-5 text-orange-600" />;
      default:
        return <FileText className="h-5 w-5 text-gray-600" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const statusConfig: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
      'SAP_CONFIRMED': { 
        bg: 'bg-green-100 text-green-800', 
        text: 'SAP Confirmed', 
        icon: <CheckCircle className="h-4 w-4" /> 
      },
      'READY_FOR_SAP': { 
        bg: 'bg-blue-100 text-blue-800', 
        text: 'Ready for SAP', 
        icon: <Clock className="h-4 w-4" /> 
      },
      'SENT_TO_SAP': { 
        bg: 'bg-purple-100 text-purple-800', 
        text: 'Sent to SAP', 
        icon: <Clock className="h-4 w-4" /> 
      },
      'FAILED': { 
        bg: 'bg-red-100 text-red-800', 
        text: 'Failed', 
        icon: <XCircle className="h-4 w-4" /> 
      },
      'DUPLICATE': { 
        bg: 'bg-yellow-100 text-yellow-800', 
        text: 'Duplicate', 
        icon: <AlertTriangle className="h-4 w-4" /> 
      },
      'RECEIVED': { 
        bg: 'bg-gray-100 text-gray-800', 
        text: 'Received', 
        icon: <Clock className="h-4 w-4" /> 
      },
      'VALIDATING': { 
        bg: 'bg-blue-100 text-blue-800', 
        text: 'Validating', 
        icon: <Clock className="h-4 w-4" /> 
      },
      'VALIDATED': { 
        bg: 'bg-green-100 text-green-800', 
        text: 'Validated', 
        icon: <CheckCircle className="h-4 w-4" /> 
      },
    };

    const config = statusConfig[status] || { 
      bg: 'bg-gray-100 text-gray-800', 
      text: status, 
      icon: <Clock className="h-4 w-4" /> 
    };

    return (
      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${config.bg}`}>
        {config.icon}
        {config.text}
      </span>
    );
  };

  const getDocumentTypeBadge = (type: string) => {
    const typeConfig: Record<string, { bg: string; text: string }> = {
      'INVOICE': { bg: 'bg-blue-50 text-blue-700 border-blue-200', text: 'Invoice' },
      'PAYMENT': { bg: 'bg-green-50 text-green-700 border-green-200', text: 'Payment' },
      'CREDIT_NOTE': { bg: 'bg-orange-50 text-orange-700 border-orange-200', text: 'Credit Note' },
    };

    const config = typeConfig[type] || { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: type };

    return (
      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${config.bg}`}>
        {getDocumentTypeIcon(type)}
        {config.text}
      </span>
    );
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return dateString;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header with Stats */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold text-gray-900">SAT Documents</h2>
            <p className="mt-1 text-sm text-gray-500">
              Total: {totalCount} document{totalCount !== 1 ? 's' : ''}
            </p>
          </div>
          <button
            onClick={fetchDocuments}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-4">
        <div className="flex items-center gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Filter className="h-5 w-5 text-gray-400" />
            <span className="text-sm font-medium text-gray-700">Filters:</span>
          </div>
          
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">All Statuses</option>
            <option value="SAP_CONFIRMED">SAP Confirmed</option>
            <option value="READY_FOR_SAP">Ready for SAP</option>
            <option value="SENT_TO_SAP">Sent to SAP</option>
            <option value="FAILED">Failed</option>
            <option value="DUPLICATE">Duplicate</option>
          </select>

          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option value="">All Types</option>
            <option value="INVOICE">Invoice</option>
            <option value="PAYMENT">Payment</option>
            <option value="CREDIT_NOTE">Credit Note</option>
          </select>

          {(statusFilter || typeFilter) && (
            <button
              onClick={() => {
                setStatusFilter('');
                setTypeFilter('');
              }}
              className="text-sm text-blue-600 hover:text-blue-700 font-medium"
            >
              Clear Filters
            </button>
          )}
        </div>
      </div>

      {/* Error State */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <div className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-600" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12">
          <div className="flex flex-col items-center justify-center">
            <RefreshCw className="h-8 w-8 text-blue-600 animate-spin mb-4" />
            <p className="text-gray-600">Loading SAT documents...</p>
          </div>
        </div>
      )}

      {/* Empty State */}
      {!loading && !error && documents.length === 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-12">
          <div className="flex flex-col items-center justify-center text-center">
            <FileText className="h-16 w-16 text-gray-300 mb-4" />
            <h3 className="text-lg font-semibold text-gray-900 mb-2">No SAT Documents Found</h3>
            <p className="text-gray-600 max-w-md">
              {statusFilter || typeFilter
                ? 'No documents match your current filters. Try adjusting them.'
                : 'No SAT documents have been uploaded yet. Upload your first CFDI document to get started.'}
            </p>
          </div>
        </div>
      )}

      {/* Documents Table */}
      {!loading && !error && documents.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Portal Reference
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Supplier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    CFDI UUID
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    SAP Doc #
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm font-medium text-gray-900">{doc.portalReferenceId}</div>
                      {doc.folio && (
                        <div className="text-xs text-gray-500">Folio: {doc.folio}</div>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getDocumentTypeBadge(doc.documentType)}
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-sm text-gray-900">{doc.supplierName || doc.supplierId}</div>
                      {doc.supplierRfc && (
                        <div className="text-xs text-gray-500">RFC: {doc.supplierRfc}</div>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <div className="text-xs font-mono text-gray-600 max-w-xs truncate" title={doc.cfdiUuid || ''}>
                        {doc.cfdiUuid || 'N/A'}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(doc.status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {doc.sapDocumentNumber ? (
                        <div className="text-sm font-medium text-green-700">{doc.sapDocumentNumber}</div>
                      ) : (
                        <span className="text-xs text-gray-400">Pending</span>
                      )}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {formatDate(doc.createdAt)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => router.push(`/sat-documents/${doc.id}`)}
                        className="inline-flex items-center gap-1.5 text-blue-600 hover:text-blue-900 transition-colors"
                      >
                        <Eye className="h-4 w-4" />
                        View
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

