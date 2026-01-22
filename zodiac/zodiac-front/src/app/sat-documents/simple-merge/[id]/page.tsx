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
    </MainLayout>
  );
}

