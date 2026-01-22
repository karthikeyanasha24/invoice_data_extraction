'use client';

import { useState, useEffect } from 'react';
import { use } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { satCanonicalApi } from '@/lib/api';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import { 
  ArrowLeft, 
  Download, 
  FileText, 
  Building2, 
  Calendar,
  DollarSign,
  Package,
  CheckCircle,
  TrendingUp,
  TrendingDown,
  Send
} from 'lucide-react';
import { format } from 'date-fns';

interface CanonicalDocument {
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
  payment_method: string;
  cfdi_uuids: string[];
  related_cfdi_uuids: string[];
  linked_document_ids: string[];
  sap_gl_account: string;
  status: string;
  sap_document_number: string;
  sent_to_sap_at: string;
  created_at: string;
}

export default function CanonicalMergedDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const router = useRouter();
  const { user } = useAuth();
  const [document, setDocument] = useState<CanonicalDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewJson, setPreviewJson] = useState<any | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);

  useEffect(() => {
    if (user && resolvedParams.id) {
      fetchDocument();
    }
  }, [user, resolvedParams.id]);

  const fetchDocument = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await satCanonicalApi.get(resolvedParams.id as string);
      setDocument(data);
    } catch (err: any) {
      console.error('Error fetching canonical document:', err);
      setError(err.message || 'Failed to fetch document details.');
    } finally {
      setLoading(false);
    }
  };

  const handleShowPreview = async () => {
    if (!document) return;
    
    try {
      setLoadingPreview(true);
      const response = await satCanonicalApi.preview(document.id);
      setPreviewJson(response.json_payload);
      setShowPreviewModal(true);
    } catch (err: any) {
      console.error('Error loading preview:', err);
      alert('Failed to load preview: ' + (err.message || 'Unknown error'));
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleDownloadXml = async () => {
    if (!document) return;
    
    try {
      setDownloading(true);
      const xmlBlob = await satCanonicalApi.downloadXml(document.id);
      const filename = `canonical_merged_${document.vendor_rfc}_${document.fiscal_year}_${document.fiscal_period.toString().padStart(2, '0')}.xml`;

      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as any).MSStream;

      if (isIOS) {
        // For iOS, open in a new tab as direct download is often blocked
        const reader = new FileReader();
        reader.onload = function() {
          const dataUrl = reader.result as string;
          const newWindow = window.open(dataUrl, '_blank');
          if (!newWindow) {
            alert('Please allow pop-ups for this website to download the XML.');
          }
        };
        reader.readAsDataURL(xmlBlob);
      } else {
        // For other browsers, use the standard download method
        const url = window.URL.createObjectURL(xmlBlob);
        const link = window.document.createElement('a');
        link.href = url;
        link.download = filename;
        window.document.body.appendChild(link);
        link.click();
        // Clean up after a short delay to ensure the download starts
        setTimeout(() => {
          window.document.body.removeChild(link);
          window.URL.revokeObjectURL(url);
        }, 100);
      }
    } catch (err: any) {
      console.error('Error downloading XML:', err);
      alert('Failed to download XML: ' + (err.message || 'Unknown error'));
    } finally {
      setDownloading(false);
    }
  };

  const formatCurrency = (amount: number, currency: string = 'MXN') => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency || 'MXN'
    }).format(amount);
  };

  const getMonthName = (month: number) => {
    return new Date(2000, month - 1, 1).toLocaleString('default', { month: 'long' });
  };

  const getStatusBadge = (status: string) => {
    const badges = {
      'MERGED': 'bg-blue-100 text-blue-800',
      'SAP_SENT': 'bg-green-100 text-green-800',
      'FAILED': 'bg-red-100 text-red-800',
    };
    return badges[status as keyof typeof badges] || 'bg-gray-100 text-gray-800';
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingSpinner size="lg" text="Loading document details..." />
      </div>
    );
  }

  if (error || !document) {
    return (
      <MainLayout
        topSection={
          <div className="px-4 sm:px-6 lg:px-8">
            <button
              onClick={() => router.push('/sat-documents')}
              className="flex items-center text-blue-600 hover:text-blue-700 mb-4"
            >
              <ArrowLeft className="w-5 h-5 mr-2" />
              Back to SAT Documents
            </button>
            <h1 className="text-3xl font-bold text-gray-900">Canonical Merged Document</h1>
          </div>
        }
      >
        <div className="p-12 text-center">
          <div className="text-red-600 mb-4">
            {error || 'Document not found'}
          </div>
          <button
            onClick={() => router.push('/sat-documents')}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            Back to SAT Documents
          </button>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout
      topSection={
        <div className="px-4 sm:px-6 lg:px-8">
          <button
            onClick={() => router.push('/sat-documents')}
            className="flex items-center text-blue-600 hover:text-blue-700 mb-4"
          >
            <ArrowLeft className="w-5 h-5 mr-2" />
            Back to SAT Documents
          </button>
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <FileText className="w-8 h-8 text-blue-600" />
                <h1 className="text-3xl font-bold text-gray-900">Canonical Merged Document</h1>
              </div>
              <p className="text-gray-600">
                View and download canonical merged SAP XML
              </p>
            </div>
            <div className="flex items-center gap-3">
              <button
                onClick={handleShowPreview}
                disabled={loadingPreview}
                className="inline-flex items-center px-6 py-3 bg-white text-blue-600 border-2 border-blue-600 font-medium rounded-lg hover:bg-blue-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
              >
                {loadingPreview ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600 mr-2"></div>
                    Loading...
                  </>
                ) : (
                  <>
                    <FileText className="w-5 h-5 mr-2" />
                    View JSON
                  </>
                )}
              </button>
              <button
                onClick={handleDownloadXml}
                disabled={downloading}
                className="inline-flex items-center px-6 py-3 bg-gradient-to-r from-blue-600 to-purple-600 text-white font-medium rounded-lg hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
              >
                {downloading ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    Downloading...
                  </>
                ) : (
                  <>
                    <Download className="w-5 h-5 mr-2" />
                    Download XML
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      }
    >
      <div className="space-y-6 py-6">
        {/* Summary Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <Building2 className="w-6 h-6 text-blue-600" />
              <h3 className="text-sm font-medium text-gray-600">Vendor</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">{document.vendor_name}</p>
            <p className="text-sm text-gray-500 font-mono mt-1">{document.vendor_rfc}</p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <Calendar className="w-6 h-6 text-purple-600" />
              <h3 className="text-sm font-medium text-gray-600">Fiscal Period</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {getMonthName(document.fiscal_period)} {document.fiscal_year}
            </p>
            <p className="text-sm text-gray-500 mt-1">
              Period {document.fiscal_period} / {document.fiscal_year}
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <Package className="w-6 h-6 text-green-600" />
              <h3 className="text-sm font-medium text-gray-600">Documents</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">{document.linked_document_ids?.length || 0}</p>
            <p className="text-sm text-gray-500 mt-1">
              {document.cfdi_uuids?.length || 0} CFDIs
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <DollarSign className="w-6 h-6 text-orange-600" />
              <h3 className="text-sm font-medium text-gray-600">Net Amount</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {formatCurrency(document.net_amount, document.currency)}
            </p>
            <p className="text-sm text-gray-500 mt-1">{document.currency}</p>
          </div>
        </div>

        {/* Financial Summary */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">Financial Summary</h2>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="flex items-start gap-4">
                <div className="p-3 bg-green-100 rounded-lg">
                  <TrendingUp className="w-6 h-6 text-green-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-600 mb-1">Total Invoices</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {formatCurrency(document.total_invoices, document.currency)}
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="p-3 bg-orange-100 rounded-lg">
                  <TrendingDown className="w-6 h-6 text-orange-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-600 mb-1">Total Credits</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {formatCurrency(document.total_credits, document.currency)}
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-4">
                <div className="p-3 bg-blue-100 rounded-lg">
                  <Send className="w-6 h-6 text-blue-600" />
                </div>
                <div>
                  <p className="text-sm text-gray-600 mb-1">Total Payments</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {formatCurrency(document.total_payments, document.currency)}
                  </p>
                </div>
              </div>
            </div>

            <div className="mt-6 pt-6 border-t border-gray-200">
              <div className="flex items-center justify-between">
                <span className="text-lg font-medium text-gray-900">Net Amount</span>
                <span className="text-2xl font-bold text-blue-600">
                  {formatCurrency(document.net_amount, document.currency)}
                </span>
              </div>
              <p className="text-sm text-gray-500 mt-2">
                Net Amount = Total Invoices - Total Credits - Total Payments
              </p>
            </div>
          </div>
        </div>

        {/* Document Information */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">Document Information</h2>
          </div>
          <div className="p-6">
            <dl className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Document ID</dt>
                <dd className="text-sm text-gray-900 font-mono">{document.id}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Company Code</dt>
                <dd className="text-sm text-gray-900">{document.company_code}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">SAP G/L Account</dt>
                <dd className="text-sm text-gray-900 font-mono">{document.sap_gl_account || 'NO MAPPING'}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Payment Method</dt>
                <dd className="text-sm text-gray-900">{document.payment_method}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Status</dt>
                <dd>
                  <span className={`px-2 py-1 text-xs font-medium rounded-full ${getStatusBadge(document.status)}`}>
                    {document.status}
                  </span>
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Created At</dt>
                <dd className="text-sm text-gray-900">
                  {format(new Date(document.created_at), 'MMMM dd, yyyy HH:mm:ss')}
                </dd>
              </div>
              {document.sap_document_number && (
                <>
                  <div>
                    <dt className="text-sm font-medium text-gray-500 mb-1">SAP Document Number</dt>
                    <dd className="text-sm text-gray-900 font-mono">{document.sap_document_number}</dd>
                  </div>
                  <div>
                    <dt className="text-sm font-medium text-gray-500 mb-1">Sent to SAP At</dt>
                    <dd className="text-sm text-gray-900">
                      {document.sent_to_sap_at ? format(new Date(document.sent_to_sap_at), 'MMMM dd, yyyy HH:mm:ss') : 'N/A'}
                    </dd>
                  </div>
                </>
              )}
            </dl>
          </div>
        </div>

        {/* Included CFDIs */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">Included CFDI UUIDs</h2>
            <p className="text-sm text-gray-600 mt-1">
              {document.cfdi_uuids?.length || 0} CFDIs merged in this canonical document
            </p>
          </div>
          <div className="p-6">
            <div className="grid grid-cols-1 gap-3">
              {document.cfdi_uuids?.map((uuid, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-3 p-3 bg-gray-50 rounded-lg"
                >
                  <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0" />
                  <span className="text-sm font-mono text-gray-900 break-all">{uuid}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Download Section */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
          <div className="flex items-start gap-4">
            <FileText className="w-8 h-8 text-blue-600 flex-shrink-0 mt-1" />
            <div className="flex-1">
              <h3 className="text-lg font-semibold text-blue-900 mb-2">Download Canonical Merged XML</h3>
              <p className="text-sm text-blue-800 mb-4">
                Download the canonical merged XML file in SAP format. This XML contains all aggregated financial data and is ready to be sent to SAP ECC/S4HANA.
              </p>
              <button
                onClick={handleDownloadXml}
                disabled={downloading}
                className="inline-flex items-center px-6 py-3 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors shadow-sm"
              >
                {downloading ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white mr-2"></div>
                    Downloading...
                  </>
                ) : (
                  <>
                    <Download className="w-5 h-5 mr-2" />
                    Download XML File
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* JSON Preview Modal */}
      {showPreviewModal && previewJson && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden">
            <div className="p-6 border-b border-gray-200 flex items-center justify-between">
              <div>
                <h2 className="text-xl font-semibold text-gray-900">SAP JSON Payload Preview</h2>
                <p className="text-sm text-gray-600 mt-1">
                  This is the format that will be sent to SAP
                </p>
              </div>
              <button
                onClick={() => setShowPreviewModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[calc(90vh-140px)]">
              <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 overflow-x-auto text-sm font-mono">
                {JSON.stringify(previewJson, null, 2)}
              </pre>
            </div>
            <div className="p-6 border-t border-gray-200 flex items-center justify-end gap-3">
              <button
                onClick={() => setShowPreviewModal(false)}
                className="px-4 py-2 text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
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
