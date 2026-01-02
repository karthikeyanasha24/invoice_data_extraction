'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import { satApi } from '@/lib/api';
import {
  FileText,
  ArrowLeft,
  Download,
  Building2,
  Calendar,
  DollarSign,
  Hash,
  CheckCircle,
  Clock,
  Send,
  FileCode
} from 'lucide-react';
import { format } from 'date-fns';

interface SATDocumentDetail {
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
  subtotal: string;
  total: string;
  moneda: string;
  tipo_cambio: string | null;
  forma_pago: string | null;
  metodo_pago: string | null;
  related_cfdi_uuid: string | null;
  status: string;
  fiscal_year: number;
  fiscal_period: number;
  received_at: string;
  sap_document_number: string | null;
  sent_to_sap_at: string | null;
  canonical_merged_id: string | null;
  merged_at: string | null;
}

export default function SATDocumentDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user } = useAuth();
  const [document, setDocument] = useState<SATDocumentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloadingXml, setDownloadingXml] = useState(false);

  useEffect(() => {
    if (user && params.id) {
      fetchDocument();
    }
  }, [user, params.id]);

  const fetchDocument = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await satApi.getDocument(params.id as string);
      setDocument(data);
    } catch (err: any) {
      console.error('Error fetching document:', err);
      setError(err.message || 'Failed to fetch document details');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadXml = async () => {
    try {
      setDownloadingXml(true);
      const xmlBlob = await satApi.getDocumentXml(params.id as string);
      const fileName = `cfdi_${document?.cfdi_uuid || 'document'}.xml`;
      
      // Check if we're on iOS
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) && !(window as any).MSStream;
      
      if (isIOS) {
        // iOS: Open in new tab (iOS doesn't support programmatic downloads well)
        const reader = new FileReader();
        reader.onload = function() {
          const dataUrl = reader.result as string;
          const newWindow = window.open(dataUrl, '_blank');
          if (!newWindow) {
            alert('Please allow popups to download the XML file');
          }
        };
        reader.readAsDataURL(xmlBlob);
      } else {
        // Desktop and Android: Standard download
        const url = window.URL.createObjectURL(xmlBlob);
        
        // Use window.document explicitly to avoid variable shadowing
        const downloadLink = window.document.createElement('a');
        downloadLink.href = url;
        downloadLink.download = fileName;
        downloadLink.style.display = 'none';
        
        window.document.body.appendChild(downloadLink);
        downloadLink.click();
        
        // Cleanup after a short delay
        setTimeout(() => {
          window.document.body.removeChild(downloadLink);
          window.URL.revokeObjectURL(url);
        }, 100);
      }
      
    } catch (err: any) {
      console.error('Error downloading XML:', err);
      alert('Failed to download XML: ' + err.message);
    } finally {
      setDownloadingXml(false);
    }
  };

  const formatCurrency = (amount: string | null, currency: string = 'MXN') => {
    if (!amount) return 'N/A';
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
      INVOICE: { bg: 'bg-green-100', text: 'text-green-800', label: 'Invoice' },
      PAYMENT: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Payment' },
      CREDIT_NOTE: { bg: 'bg-orange-100', text: 'text-orange-800', label: 'Credit Note' },
    };
    const style = styles[docType as keyof typeof styles] || { bg: 'bg-gray-100', text: 'text-gray-800', label: docType };
    return (
      <span className={`px-3 py-1 ${style.bg} ${style.text} rounded-full text-sm font-medium`}>
        {style.label}
      </span>
    );
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      RECEIVED: { bg: 'bg-gray-100', text: 'text-gray-800', icon: Clock },
      VALIDATED: { bg: 'bg-blue-100', text: 'text-blue-800', icon: CheckCircle },
      MERGED: { bg: 'bg-purple-100', text: 'text-purple-800', icon: FileCode },
      SAP_SENT: { bg: 'bg-green-100', text: 'text-green-800', icon: Send },
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
            onClick={() => router.push('/sat-documents')}
            className="mb-4 inline-flex items-center gap-2 text-blue-600 hover:text-blue-700 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Documents
          </button>
          
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <FileText className="w-8 h-8 text-blue-600" />
                <h1 className="text-3xl font-bold text-gray-900">SAT Document Details</h1>
              </div>
              <p className="text-gray-600">CFDI UUID: {document.cfdi_uuid}</p>
            </div>
            <button
              onClick={handleDownloadXml}
              disabled={downloadingXml}
              className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              <Download className="w-4 h-4" />
              {downloadingXml ? 'Downloading...' : 'Download XML'}
            </button>
          </div>
        </div>

        {/* Document Type and Status */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mb-6">
          <div className="flex items-center gap-4">
            <div>
              <p className="text-sm text-gray-600 mb-1">Document Type</p>
              {getDocTypeBadge(document.doc_type)}
            </div>
            <div className="border-l border-gray-300 h-12"></div>
            <div>
              <p className="text-sm text-gray-600 mb-1">Status</p>
              {getStatusBadge(document.status)}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Supplier Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Supplier Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">RFC</p>
                <p className="font-mono text-gray-900">{document.supplier_rfc}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Name</p>
                <p className="text-gray-900">{document.supplier_name || 'N/A'}</p>
              </div>
            </div>
          </div>

          {/* Receiver Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Building2 className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Receiver Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">RFC</p>
                <p className="font-mono text-gray-900">{document.receiver_rfc}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Name</p>
                <p className="text-gray-900">{document.receiver_name || 'N/A'}</p>
              </div>
            </div>
          </div>

          {/* Document Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <Hash className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Document Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">Serie - Folio</p>
                <p className="text-gray-900">{document.serie || 'N/A'} - {document.folio || 'N/A'}</p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Document Date</p>
                <p className="text-gray-900">
                  {document.fecha ? format(new Date(document.fecha), 'PPP p') : 'N/A'}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Fiscal Period</p>
                <p className="text-gray-900">{document.fiscal_year} - Period {document.fiscal_period}</p>
              </div>
              {document.related_cfdi_uuid && (
                <div>
                  <p className="text-sm text-gray-600">Related CFDI UUID</p>
                  <p className="font-mono text-xs text-gray-900 break-all">{document.related_cfdi_uuid}</p>
                </div>
              )}
            </div>
          </div>

          {/* Financial Information */}
          <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
            <div className="flex items-center gap-2 mb-4">
              <DollarSign className="w-5 h-5 text-gray-600" />
              <h2 className="text-xl font-semibold text-gray-900">Financial Information</h2>
            </div>
            <div className="space-y-3">
              <div>
                <p className="text-sm text-gray-600">Subtotal</p>
                <p className="text-lg font-semibold text-gray-900">
                  {formatCurrency(document.subtotal, document.moneda)}
                </p>
              </div>
              <div>
                <p className="text-sm text-gray-600">Total</p>
                <p className="text-2xl font-bold text-gray-900">
                  {formatCurrency(document.total, document.moneda)}
                </p>
              </div>
              {document.tipo_cambio && (
                <div>
                  <p className="text-sm text-gray-600">Exchange Rate</p>
                  <p className="text-gray-900">{document.tipo_cambio}</p>
                </div>
              )}
              {document.forma_pago && (
                <div>
                  <p className="text-sm text-gray-600">Payment Form</p>
                  <p className="text-gray-900">{document.forma_pago}</p>
                </div>
              )}
              {document.metodo_pago && (
                <div>
                  <p className="text-sm text-gray-600">Payment Method</p>
                  <p className="text-gray-900">{document.metodo_pago}</p>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Processing Information */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6 mt-6">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="w-5 h-5 text-gray-600" />
            <h2 className="text-xl font-semibold text-gray-900">Processing Information</h2>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            <div>
              <p className="text-sm text-gray-600">Received At</p>
              <p className="text-gray-900">
                {document.received_at ? format(new Date(document.received_at), 'PPP p') : 'N/A'}
              </p>
            </div>
            {document.merged_at && (
              <div>
                <p className="text-sm text-gray-600">Merged At</p>
                <p className="text-gray-900">{format(new Date(document.merged_at), 'PPP p')}</p>
              </div>
            )}
            {document.canonical_merged_id && (
              <div>
                <p className="text-sm text-gray-600">Canonical Merged ID</p>
                <button
                  onClick={() => router.push(`/sat-documents/canonical/${document.canonical_merged_id}`)}
                  className="text-blue-600 hover:text-blue-700 font-mono text-sm underline"
                >
                  View Merged Document
                </button>
              </div>
            )}
            {document.sap_document_number && (
              <div>
                <p className="text-sm text-gray-600">SAP Document Number</p>
                <p className="font-mono text-gray-900">{document.sap_document_number}</p>
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
      </div>
    </MainLayout>
  );
}

