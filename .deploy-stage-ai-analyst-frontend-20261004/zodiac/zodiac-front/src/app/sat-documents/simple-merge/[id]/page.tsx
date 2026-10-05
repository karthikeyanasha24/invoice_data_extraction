'use client';

import { useState, useEffect } from 'react';
import { use } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { satSimpleMergeApi } from '@/lib/api';
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
  CheckCircle
} from 'lucide-react';
import { format } from 'date-fns';

interface SimpleMergedDocument {
  id: string;
  vendor_rfc: string;
  vendor_name: string;
  fiscal_year: number;
  fiscal_period: number;
  document_count: number;
  document_types: string[];
  cfdi_uuids: string[];
  total_amount: number;
  currency: string;
  created_at: string;
  merged_xml_content: string;
}

export default function SimpleMergedDocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  const router = useRouter();
  const { user } = useAuth();
  const [document, setDocument] = useState<SimpleMergedDocument | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewJson, setPreviewJson] = useState<any | null>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [csrfToken, setCsrfToken] = useState<string | null>(null);
  const [fetchingCsrf, setFetchingCsrf] = useState(false);

  useEffect(() => {
    if (user && resolvedParams.id) {
      fetchDocument();
    }
  }, [user, resolvedParams.id]);

  const fetchDocument = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await satSimpleMergeApi.get(resolvedParams.id as string);
      setDocument(data);
    } catch (err: any) {
      console.error('Error fetching simple merged document:', err);
      setError(err.message || 'Failed to fetch document details.');
    } finally {
      setLoading(false);
    }
  };

  const handleShowPreview = async () => {
    if (!document) return;
    
    try {
      setLoadingPreview(true);
      const response = await satSimpleMergeApi.previewSapJson(document.id);
      setPreviewJson(response.json_payload);
      setShowPreviewModal(true);
    } catch (err: any) {
      console.error('Error loading preview:', err);
      alert('Failed to load SAP JSON preview: ' + (err.message || 'Unknown error'));
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleFetchCsrfToken = async () => {
    if (!document) return;
    
    try {
      setFetchingCsrf(true);
      const response = await satSimpleMergeApi.fetchCsrfToken(document.id);
      setCsrfToken(response.csrf_token);
      alert(`CSRF Token fetched successfully!\n\nToken: ${response.csrf_token}\n\nNow you can send to SAP.`);
    } catch (err: any) {
      console.error('Error fetching CSRF token:', err);
      alert('Failed to fetch CSRF token: ' + (err.message || 'Unknown error'));
    } finally {
      setFetchingCsrf(false);
    }
  };

  const handleDownloadXml = async () => {
    if (!document) return;
    
    try {
      setDownloading(true);
      const xmlBlob = await satSimpleMergeApi.download(document.id);
      const filename = `merged_cfdi_${document.vendor_rfc}_${document.fiscal_year}_${document.fiscal_period.toString().padStart(2, '0')}.xml`;

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
            <h1 className="text-3xl font-bold text-gray-900">Simple Merged Document</h1>
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
                <h1 className="text-3xl font-bold text-gray-900">Simple Merged Document</h1>
              </div>
              <p className="text-gray-600">
                View and download merged CFDI XML
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
                onClick={handleFetchCsrfToken}
                disabled={fetchingCsrf}
                className="inline-flex items-center px-6 py-3 bg-white text-green-600 border-2 border-green-600 font-medium rounded-lg hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-sm hover:shadow-md"
              >
                {fetchingCsrf ? (
                  <>
                    <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-green-600 mr-2"></div>
                    Fetching...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-5 h-5 mr-2" />
                    {csrfToken ? 'Refresh CSRF' : 'Fetch CSRF Token'}
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
              Period {document.fiscal_period}
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <Package className="w-6 h-6 text-green-600" />
              <h3 className="text-sm font-medium text-gray-600">Documents</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">{document.document_count}</p>
            <p className="text-sm text-gray-500 mt-1">
              {document.document_types?.join(', ')}
            </p>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center gap-3 mb-2">
              <DollarSign className="w-6 h-6 text-orange-600" />
              <h3 className="text-sm font-medium text-gray-600">Total Amount</h3>
            </div>
            <p className="text-lg font-semibold text-gray-900">
              {formatCurrency(document.total_amount, document.currency)}
            </p>
            <p className="text-sm text-gray-500 mt-1">{document.currency}</p>
          </div>
        </div>

        {/* CSRF Token Display */}
        {csrfToken && (
          <div className="bg-green-50 border-2 border-green-400 rounded-lg p-6">
            <div className="flex items-start gap-3">
              <CheckCircle className="w-6 h-6 text-green-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h3 className="text-lg font-bold text-green-900 mb-2">
                  CSRF Token Ready!
                </h3>
                <p className="text-green-800 text-sm mb-3">
                  Token fetched from SAP. You can now send this document to SAP.
                </p>
                <div className="bg-white border border-green-300 rounded p-3">
                  <code className="text-sm font-mono text-gray-900 break-all">
                    {csrfToken}
                  </code>
                </div>
              </div>
            </div>
          </div>
        )}

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
                <dt className="text-sm font-medium text-gray-500 mb-1">Created At</dt>
                <dd className="text-sm text-gray-900">
                  {format(new Date(document.created_at), 'MMMM dd, yyyy HH:mm:ss')}
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Vendor RFC</dt>
                <dd className="text-sm text-gray-900 font-mono">{document.vendor_rfc}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Vendor Name</dt>
                <dd className="text-sm text-gray-900">{document.vendor_name}</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Document Count</dt>
                <dd className="text-sm text-gray-900">{document.document_count} documents</dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-gray-500 mb-1">Document Types</dt>
                <dd className="text-sm text-gray-900">
                  <div className="flex flex-wrap gap-2">
                    {document.document_types?.map((type, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-medium rounded-full"
                      >
                        {type}
                      </span>
                    ))}
                  </div>
                </dd>
              </div>
            </dl>
          </div>
        </div>

        {/* Included CFDIs */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">Included CFDI UUIDs</h2>
            <p className="text-sm text-gray-600 mt-1">
              {document.cfdi_uuids?.length || 0} CFDIs merged in this document
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

        {/* XML Preview */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">Merged XML Content</h2>
              <p className="text-sm text-gray-600 mt-1">
                Preview of the merged XML structure
              </p>
            </div>
            <button
              onClick={handleDownloadXml}
              disabled={downloading}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-sm font-medium"
            >
              {downloading ? 'Downloading...' : 'Download XML'}
            </button>
          </div>
          <div className="p-6">
            <pre className="bg-gray-50 border border-gray-200 rounded-lg p-4 overflow-x-auto text-xs font-mono max-h-96">
              {document.merged_xml_content}
            </pre>
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

