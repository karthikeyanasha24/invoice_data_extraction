'use client';

import React, { useState, useEffect } from 'react';
import { satApi } from '@/lib/api';
import { SATDocument, SATProcessingLog } from '@/types';
import { useRouter } from 'next/navigation';
import { 
  ArrowLeft,
  FileText,
  CreditCard,
  Receipt,
  CheckCircle,
  XCircle,
  Clock,
  AlertTriangle,
  Building,
  User,
  Calendar,
  Hash,
  DollarSign,
  Globe,
  FileCheck,
  RefreshCw,
  Download,
  Activity
} from 'lucide-react';

interface SATDocumentDetailProps {
  documentId: string;
}

export default function SATDocumentDetail({ documentId }: SATDocumentDetailProps) {
  const router = useRouter();
  const [document, setDocument] = useState<SATDocument | null>(null);
  const [logs, setLogs] = useState<SATProcessingLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [logsLoading, setLogsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    fetchDocument();
    fetchLogs();
  }, [documentId]);

  const fetchDocument = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await satApi.getDocument(documentId);
      setDocument(data);
    } catch (err: any) {
      console.error('Error fetching document:', err);
      setError(err.message || 'Failed to load document');
    } finally {
      setLoading(false);
    }
  };

  const fetchLogs = async () => {
    try {
      setLogsLoading(true);
      const data = await satApi.getLogs(documentId);
      setLogs(data || []);
    } catch (err: any) {
      console.error('Error fetching logs:', err);
    } finally {
      setLogsLoading(false);
    }
  };

  const handleRetry = async () => {
    try {
      setRetrying(true);
      await satApi.retryProcessing(documentId);
      // Refresh document and logs after a delay
      setTimeout(() => {
        fetchDocument();
        fetchLogs();
      }, 2000);
    } catch (err: any) {
      console.error('Error retrying processing:', err);
      alert(err.message || 'Failed to retry processing');
    } finally {
      setRetrying(false);
    }
  };

  const getDocumentTypeIcon = (type: string) => {
    switch (type) {
      case 'INVOICE':
        return <FileText className="h-6 w-6 text-blue-600" />;
      case 'PAYMENT':
        return <CreditCard className="h-6 w-6 text-green-600" />;
      case 'CREDIT_NOTE':
        return <Receipt className="h-6 w-6 text-orange-600" />;
      default:
        return <FileText className="h-6 w-6 text-gray-600" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const statusConfig: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
      'SAP_CONFIRMED': { 
        bg: 'bg-green-100 text-green-800', 
        text: 'SAP Confirmed', 
        icon: <CheckCircle className="h-5 w-5" /> 
      },
      'READY_FOR_SAP': { 
        bg: 'bg-blue-100 text-blue-800', 
        text: 'Ready for SAP', 
        icon: <Clock className="h-5 w-5" /> 
      },
      'SENT_TO_SAP': { 
        bg: 'bg-purple-100 text-purple-800', 
        text: 'Sent to SAP', 
        icon: <Clock className="h-5 w-5" /> 
      },
      'FAILED': { 
        bg: 'bg-red-100 text-red-800', 
        text: 'Failed', 
        icon: <XCircle className="h-5 w-5" /> 
      },
      'DUPLICATE': { 
        bg: 'bg-yellow-100 text-yellow-800', 
        text: 'Duplicate', 
        icon: <AlertTriangle className="h-5 w-5" /> 
      },
    };

    const config = statusConfig[status] || { 
      bg: 'bg-gray-100 text-gray-800', 
      text: status, 
      icon: <Clock className="h-5 w-5" /> 
    };

    return (
      <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg ${config.bg}`}>
        {config.icon}
        <span className="font-semibold">{config.text}</span>
      </div>
    );
  };

  const getLogStatusIcon = (status: string) => {
    switch (status) {
      case 'SUCCESS':
        return <CheckCircle className="h-5 w-5 text-green-600" />;
      case 'FAILED':
        return <XCircle className="h-5 w-5 text-red-600" />;
      case 'WARNING':
        return <AlertTriangle className="h-5 w-5 text-yellow-600" />;
      default:
        return <Clock className="h-5 w-5 text-blue-600" />;
    }
  };

  const formatDate = (dateString: string | null) => {
    if (!dateString) return 'N/A';
    try {
      return new Date(dateString).toLocaleString();
    } catch {
      return dateString;
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="text-center">
          <RefreshCw className="h-12 w-12 text-blue-600 animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Loading document...</p>
        </div>
      </div>
    );
  }

  if (error || !document) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-8 text-center">
        <XCircle className="h-12 w-12 text-red-600 mx-auto mb-4" />
        <h3 className="text-lg font-semibold text-red-900 mb-2">Error Loading Document</h3>
        <p className="text-red-700">{error || 'Document not found'}</p>
        <button
          onClick={() => router.push('/sat-documents')}
          className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition-colors"
        >
          Back to Documents
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button
          onClick={() => router.push('/sat-documents')}
          className="flex items-center gap-2 text-gray-600 hover:text-gray-900 transition-colors"
        >
          <ArrowLeft className="h-5 w-5" />
          <span>Back to Documents</span>
        </button>

        {document.status === 'FAILED' && (
          <button
            onClick={handleRetry}
            disabled={retrying}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            <RefreshCw className={`h-4 w-4 ${retrying ? 'animate-spin' : ''}`} />
            Retry Processing
          </button>
        )}
      </div>

      {/* Document Overview */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <div className="flex items-start justify-between mb-6">
          <div className="flex items-center gap-4">
            {getDocumentTypeIcon(document.documentType)}
            <div>
              <h1 className="text-2xl font-bold text-gray-900">{document.portalReferenceId}</h1>
              <p className="text-sm text-gray-500 mt-1">{document.documentType.replace('_', ' ')}</p>
            </div>
          </div>
          {getStatusBadge(document.status)}
        </div>

        {/* Key Metrics Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* CFDI UUID */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Hash className="h-4 w-4" />
              <span>CFDI UUID</span>
            </div>
            <p className="text-sm font-mono text-gray-900 break-all">
              {document.cfdiUuid || 'N/A'}
            </p>
          </div>

          {/* SAP Document Number */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <FileCheck className="h-4 w-4" />
              <span>SAP Document #</span>
            </div>
            <p className="text-lg font-bold text-green-700">
              {document.sapDocumentNumber || 'Pending'}
            </p>
          </div>

          {/* Created Date */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Calendar className="h-4 w-4" />
              <span>Created</span>
            </div>
            <p className="text-sm text-gray-900">{formatDate(document.createdAt)}</p>
          </div>

          {/* Updated Date */}
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Calendar className="h-4 w-4" />
              <span>Last Updated</span>
            </div>
            <p className="text-sm text-gray-900">{formatDate(document.updatedAt)}</p>
          </div>
        </div>
      </div>

      {/* Document Details */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* CFDI Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <FileText className="h-5 w-5 text-blue-600" />
            CFDI Information
          </h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Version</dt>
              <dd className="text-sm text-gray-900">{document.cfdiVersion || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Serie</dt>
              <dd className="text-sm text-gray-900">{document.serie || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Folio</dt>
              <dd className="text-sm text-gray-900">{document.folio || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Document Date</dt>
              <dd className="text-sm text-gray-900">{formatDate(document.fecha)}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Document Type</dt>
              <dd className="text-sm text-gray-900">{document.tipoDeComprobante || 'N/A'}</dd>
            </div>
          </dl>
        </div>

        {/* Supplier Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <Building className="h-5 w-5 text-green-600" />
            Supplier Information
          </h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Supplier ID</dt>
              <dd className="text-sm text-gray-900">{document.supplierId}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Supplier Name</dt>
              <dd className="text-sm text-gray-900">{document.supplierName || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">RFC</dt>
              <dd className="text-sm text-gray-900">{document.supplierRfc || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Company Code</dt>
              <dd className="text-sm text-gray-900">{document.companyCode}</dd>
            </div>
          </dl>
        </div>

        {/* Customer Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <User className="h-5 w-5 text-purple-600" />
            Customer Information
          </h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Customer Name</dt>
              <dd className="text-sm text-gray-900">{document.customerName || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Customer RFC</dt>
              <dd className="text-sm text-gray-900">{document.customerRfc || 'N/A'}</dd>
            </div>
          </dl>
        </div>

        {/* Financial Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <DollarSign className="h-5 w-5 text-orange-600" />
            Financial Information
          </h2>
          <dl className="space-y-3">
            <div>
              <dt className="text-sm font-medium text-gray-500">Subtotal</dt>
              <dd className="text-sm text-gray-900">{document.subtotal || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Total</dt>
              <dd className="text-lg font-bold text-gray-900">{document.total || 'N/A'}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-gray-500">Currency</dt>
              <dd className="text-sm text-gray-900">{document.moneda || 'N/A'}</dd>
            </div>
          </dl>
        </div>
      </div>

      {/* SAP Information */}
      {(document.sapDocumentNumber || document.sapFiscalYear || document.sapPostingDate) && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-green-900 mb-4 flex items-center gap-2">
            <CheckCircle className="h-5 w-5 text-green-600" />
            SAP ECC Information
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <div>
              <dt className="text-sm font-medium text-green-700">SAP Document Number</dt>
              <dd className="text-lg font-bold text-green-900 mt-1">{document.sapDocumentNumber}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-green-700">Fiscal Year</dt>
              <dd className="text-lg font-bold text-green-900 mt-1">{document.sapFiscalYear}</dd>
            </div>
            <div>
              <dt className="text-sm font-medium text-green-700">Posting Date</dt>
              <dd className="text-lg font-bold text-green-900 mt-1">{formatDate(document.sapPostingDate)}</dd>
            </div>
          </div>
        </div>
      )}

      {/* Error Information */}
      {document.errorMessage && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <h2 className="text-lg font-semibold text-red-900 mb-4 flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-red-600" />
            Error Information
          </h2>
          <div className="space-y-2">
            {document.errorCode && (
              <div>
                <span className="text-sm font-medium text-red-700">Error Code:</span>
                <span className="ml-2 text-sm text-red-900 font-mono">{document.errorCode}</span>
              </div>
            )}
            <div>
              <span className="text-sm font-medium text-red-700">Error Message:</span>
              <p className="mt-1 text-sm text-red-900 whitespace-pre-wrap">{document.errorMessage}</p>
            </div>
          </div>
        </div>
      )}

      {/* Processing Logs */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
        <h2 className="text-lg font-semibold text-gray-900 mb-4 flex items-center gap-2">
          <Activity className="h-5 w-5 text-blue-600" />
          Processing Timeline
          {logsLoading && <RefreshCw className="h-4 w-4 text-blue-600 animate-spin ml-2" />}
        </h2>

        {!logsLoading && logs.length === 0 ? (
          <p className="text-sm text-gray-500">No processing logs available.</p>
        ) : (
          <div className="space-y-4">
            {logs.map((log, index) => (
              <div key={`${log.id}-${index}`} className="flex gap-4">
                {/* Timeline dot */}
                <div className="flex flex-col items-center">
                  <div className="flex-shrink-0">
                    {getLogStatusIcon(log.stepStatus)}
                  </div>
                  {index < logs.length - 1 && (
                    <div className="w-0.5 h-full bg-gray-200 mt-2"></div>
                  )}
                </div>

                {/* Log content */}
                <div className="flex-1 pb-8">
                  <div className="flex items-center gap-3 mb-1">
                    <h3 className="text-sm font-semibold text-gray-900">{log.stepName}</h3>
                    <span className={`text-xs font-medium px-2 py-0.5 rounded ${
                      log.stepStatus === 'SUCCESS' ? 'bg-green-100 text-green-800' :
                      log.stepStatus === 'FAILED' ? 'bg-red-100 text-red-800' :
                      log.stepStatus === 'WARNING' ? 'bg-yellow-100 text-yellow-800' :
                      'bg-blue-100 text-blue-800'
                    }`}>
                      {log.stepStatus}
                    </span>
                  </div>
                  {log.message && (
                    <p className="text-sm text-gray-600 mt-1">{log.message}</p>
                  )}
                  {log.timestamp && (
                    <p className="text-xs text-gray-400 mt-1">{formatDate(log.timestamp)}</p>
                  )}
                  {log.details && Object.keys(log.details).length > 0 && (
                    <details className="mt-2">
                      <summary className="text-xs text-blue-600 cursor-pointer hover:text-blue-800">
                        View details
                      </summary>
                      <pre className="mt-2 text-xs bg-gray-50 p-3 rounded border border-gray-200 overflow-x-auto">
                        {JSON.stringify(log.details, null, 2)}
                      </pre>
                    </details>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

