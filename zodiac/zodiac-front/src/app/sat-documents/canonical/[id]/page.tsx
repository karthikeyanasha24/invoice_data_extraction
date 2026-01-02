'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import { satCanonicalApi } from '@/lib/api';
import {
  FileCode,
  ArrowLeft,
  Building2,
  Calendar,
  DollarSign,
  Hash,
  CheckCircle,
  Clock,
  Send,
  FileText,
  Eye
} from 'lucide-react';
import { format } from 'date-fns';

interface CanonicalDocumentDetail {
  id: string;
  vendor_rfc: string;
  vendor_name: string;
  company_code: string;
  fiscal_year: number;
  fiscal_period: number;
  total_invoices: number;
  total_credits: number;
  total_payments: number;
  net_amount: number;
  currency: string;
  payment_method: string | null;
  cfdi_uuids: string[];
  related_cfdi_uuids: string[];
  linked_document_ids: string[];
  sap_gl_account: string | null;
  status: string;
  sap_document_number: string | null;
  sent_to_sap_at: string | null;
  created_at: string;
}

export default function CanonicalDocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const [document, setDocument] = useState<CanonicalDocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [previewJson, setPreviewJson] = useState<any>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  useEffect(() => {
    if (user && params.id) {
      fetchDocument();
    }
  }, [user, params.id]);

  const fetchDocument = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await satCanonicalApi.get(params.id as string);
      setDocument(data);
    } catch (err: any) {
      console.error('Error fetching canonical document:', err);
      setError(err.message || 'Failed to fetch document details');
    } finally {
      setLoading(false);
    }
  };

  const handlePreview = async () => {
    try {
      setLoadingPreview(true);
      const preview = await satCanonicalApi.preview(params.id as string);
      setPreviewJson(preview.json_payload);
      setShowPreview(true);
    } catch (err: any) {
      console.error('Error fetching preview:', err);
      alert('Failed to generate preview: ' + err.message);
    } finally {
      setLoadingPreview(false);
    }
  };

  const formatCurrency = (amount: number, currency: string = 'MXN') => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency,
    }).format(amount);
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      MERGED: { bg: 'bg-purple-100', text: 'text-purple-800', icon: FileCode },
      SAP_SENT: { bg: 'bg-green-100', text: 'text-green-800', icon: Send },
      SAP_CONFIRMED: { bg: 'bg-green-600', text: 'text-white', icon: CheckCircle },
    };
    const style = styles[status as keyof typeof styles] || { bg: 'bg-gray-100', text: 'text-gray-800', icon: FileText };
    const Icon = style.icon;
    return (
      <span className={`px-3 py-1 ${style.bg} ${style.text} rounded-full text-sm font-medium inline-flex items-center gap-2`}>
        <Icon className="w-4 h-4" />
        {status}
      </span>
    );
  };

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingSpinner />
      </div>
    );
  }

  if (loading) {
    return (
      <MainLayout topSection={null}>
        <div className="flex items-center justify-center min-h-[400px]">
          <LoadingSpinner />
        </div>
      </MainLayout>
    );
  }

  if (error || !document) {
    return (
      <MainLayout topSection={null}>
        <div className="max-w-4xl mx-auto px-4 py-8">
          <button
            onClick={() => router.push('/sat-documents')}
            className="mb-4 inline-flex items-center gap-2 text-blue-600 hover:text-blue-700"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Documents
          </button>
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <p className="text-red-800">{error || 'Document not found'}</p>
          </div>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout topSection={null}>
      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="mb-6">
          <button
            onClick={() => router.push('/sat-documents?tab=canonical')}
            className="mb-4 inline-flex items-center gap-2 text-blue-600 hover:text-blue-700 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Canonical Documents
          </button>
          
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <FileCode className="w-8 h-8 text-purple-600" />
                <h1 className="text-3xl font-bold text-gray-900">Canonical Merged Document</h1>
              </div>
              <p className="text-gray-600">Vendor: {document.vendor_rfc} - {document.vendor_name}</p>
            </div>
            <button
              onClick={handlePreview}
              disabled={loadingPreview}
              className="inline-flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              <Eye className="w-4 h-4" />
              {loadingPreview ? 'Loading...' : 'Preview SAP JSON'}
            </button>
          </div>
        </div>

        {/* Status */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="flex items-center gap-4">
            <div>
              <p className="text-sm text-gray-600 mb-1">Status</p>
              {getStatusBadge(document.status)}
            </div>
            {document.sap_gl_account && (
              <>
                <div className="border-l border-gray-300 h-12"></div>
                <div>
                  <p className="text-sm text-gray-600 mb-1">SAP G/L Account</p>
                  <span className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-mono font-medium">
                    {document.sap_gl_account}
                  </span>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Vendor Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Vendor Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">RFC</p>
                <p className="font-mono text-gray-900">{document.vendor_rfc}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Name</p>
                <p className="text-gray-900">{document.vendor_name || 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Company Code</p>
                <p className="font-mono text-gray-900">{document.company_code}</p>
              </div>
            </div>
          </div>

          {/* Period Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Calendar className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Period Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">Fiscal Year</p>
                <p className="text-2xl font-bold text-gray-900">{document.fiscal_year}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Fiscal Period</p>
                <p className="text-2xl font-bold text-gray-900">{document.fiscal_period}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Created At</p>
                <p className="text-gray-900">
                  {document.created_at ? format(new Date(document.created_at), 'PPP p') : 'N/A'}
                </p>
              </div>
            </div>
          </div>

          {/* Financial Summary */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 lg:col-span-2">
            <div className="flex items-center gap-2 mb-4">
              <DollarSign className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Financial Summary</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="bg-green-50 rounded-lg p-4">
                <p className="text-sm text-gray-600 mb-1">Total Invoices</p>
                <p className="text-2xl font-bold text-green-700">
                  {formatCurrency(document.total_invoices, document.currency)}
                </p>
              </div>
              <div className="bg-orange-50 rounded-lg p-4">
                <p className="text-sm text-gray-600 mb-1">Total Credits</p>
                <p className="text-2xl font-bold text-orange-700">
                  {formatCurrency(document.total_credits, document.currency)}
                </p>
              </div>
              <div className="bg-blue-50 rounded-lg p-4">
                <p className="text-sm text-gray-600 mb-1">Total Payments</p>
                <p className="text-2xl font-bold text-blue-700">
                  {formatCurrency(document.total_payments, document.currency)}
                </p>
              </div>
              <div className="bg-purple-50 rounded-lg p-4">
                <p className="text-sm text-gray-600 mb-1">Net Amount</p>
                <p className="text-2xl font-bold text-purple-700">
                  {formatCurrency(document.net_amount, document.currency)}
                </p>
              </div>
            </div>
            {document.payment_method && (
              <div className="mt-4">
                <p className="text-sm text-gray-600">Payment Method</p>
                <p className="text-gray-900">{document.payment_method}</p>
              </div>
            )}
          </div>
        </div>

        {/* Linked Documents */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mt-6">
          <div className="flex items-center gap-2 mb-4">
            <Hash className="w-5 h-5 text-gray-600" />
            <h2 className="text-xl font-semibold text-gray-900">Linked Documents</h2>
          </div>
          <div className="space-y-4">
            <div>
              <p className="text-sm text-gray-600 mb-2">CFDI UUIDs ({document.cfdi_uuids.length})</p>
              <div className="bg-gray-50 rounded-lg p-4 max-h-40 overflow-y-auto">
                {document.cfdi_uuids.length > 0 ? (
                  <ul className="space-y-2">
                    {document.cfdi_uuids.map((uuid, index) => (
                      <li key={index} className="font-mono text-xs text-gray-700 break-all">
                        {uuid}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-gray-500 text-sm">No UUIDs</p>
                )}
              </div>
            </div>
            
            {document.linked_document_ids && document.linked_document_ids.length > 0 && (
              <div>
                <p className="text-sm text-gray-600 mb-2">Linked Document IDs ({document.linked_document_ids.length})</p>
                <div className="bg-gray-50 rounded-lg p-4 max-h-40 overflow-y-auto">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                    {document.linked_document_ids.map((docId, index) => (
                      <button
                        key={index}
                        onClick={() => router.push(`/sat-documents/${docId}`)}
                        className="text-left px-3 py-2 bg-white rounded border border-gray-200 hover:border-blue-400 hover:bg-blue-50 transition-colors text-xs font-mono text-blue-600 hover:text-blue-700"
                      >
                        {docId.substring(0, 8)}...
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* SAP Information */}
        {(document.sap_document_number || document.sent_to_sap_at) && (
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mt-6">
            <div className="flex items-center gap-2 mb-4">
              <Send className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">SAP Information</h2>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {document.sap_document_number && (
                <div>
                  <p className="text-sm text-gray-600">SAP Document Number</p>
                  <p className="font-mono text-lg font-semibold text-gray-900">{document.sap_document_number}</p>
                </div>
              )}
              {document.sent_to_sap_at && (
                <div>
                  <p className="text-sm text-gray-600">Sent to SAP At</p>
                  <p className="text-gray-900">{format(new Date(document.sent_to_sap_at), 'PPP p')}</p>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Preview Modal */}
      {showPreview && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[80vh] flex flex-col">
            <div className="p-6 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <h3 className="text-xl font-semibold text-gray-900">SAP JSON Preview</h3>
                <button
                  onClick={() => setShowPreview(false)}
                  className="text-gray-400 hover:text-gray-600"
                >
                  <span className="text-2xl">&times;</span>
                </button>
              </div>
              <p className="text-sm text-gray-600 mt-1">
                This is the format that will be sent to SAP
              </p>
            </div>
            <div className="flex-1 overflow-y-auto p-6">
              <pre className="bg-gray-50 rounded-lg p-4 text-xs font-mono text-gray-800 overflow-x-auto">
                {JSON.stringify(previewJson, null, 2)}
              </pre>
            </div>
            <div className="p-6 border-t border-gray-200 flex justify-end">
              <button
                onClick={() => setShowPreview(false)}
                className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </MainLayout>
  );
}

