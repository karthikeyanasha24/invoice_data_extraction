'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import { satCanonicalApi, satApi } from '@/lib/api';
import { 
  ArrowLeft, 
  Building2, 
  Calendar, 
  DollarSign, 
  FileText, 
  Send,
  CheckCircle,
  XCircle,
  Clock,
  RefreshCw,
  Package,
  TrendingUp,
  TrendingDown,
  Minus,
  ExternalLink
} from 'lucide-react';
import { format } from 'date-fns';

interface CanonicalDocument {
  id: string;
  company_code: string;
  fiscal_year: number;
  fiscal_period: number;
  vendor_rfc: string;
  vendor_name: string | null;
  doc_type: string;
  doc_date: string | null;
  currency: string;
  total_invoices: string;
  total_credits: string;
  total_payments: string;
  net_amount: string;
  amount_signed: string;
  tax_base: string | null;
  tax_amount: string | null;
  payment_date: string | null;
  payment_method: string | null;
  status: string;
  sap_document_number: string | null;
  merged_at: string | null;
  sent_to_sap_at: string | null;
  created_at: string;
  linked_document_ids?: string[];
}

interface LinkedDocument {
  id: string;
  documentType: string;
  cfdiUuid: string;
  fecha: string | null;
  total: string | null;
  status: string;
  folio: string | null;
}

export default function CanonicalDetailPage() {
  const router = useRouter();
  const params = useParams();
  const canonicalId = params?.id as string;

  const [canonical, setCanonical] = useState<CanonicalDocument | null>(null);
  const [linkedDocs, setLinkedDocs] = useState<LinkedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (canonicalId) {
      fetchCanonicalDetails();
    }
  }, [canonicalId]);

  const fetchCanonicalDetails = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch canonical document
      const canonicalData = await satCanonicalApi.get(canonicalId);
      setCanonical(canonicalData);

      // Fetch linked individual documents if available
      if (canonicalData.linked_document_ids && canonicalData.linked_document_ids.length > 0) {
        const docsPromises = canonicalData.linked_document_ids.map((docId: string) =>
          satApi.getDocument(docId).catch(() => null)
        );
        const docs = await Promise.all(docsPromises);
        setLinkedDocs(docs.filter(Boolean));
      }
    } catch (err: any) {
      console.error('Error fetching canonical details:', err);
      setError(err.message || 'Failed to load canonical document details');
    } finally {
      setLoading(false);
    }
  };

  const handleSendToSAP = async () => {
    if (!canonical) return;
    
    try {
      setSending(true);
      setError(null);
      await satCanonicalApi.sendToSAP(canonical.id);
      await fetchCanonicalDetails(); // Refresh data
    } catch (err: any) {
      console.error('Error sending to SAP:', err);
      setError(err.message || 'Failed to send to SAP');
    } finally {
      setSending(false);
    }
  };

  if (loading) {
    return (
      <MainLayout topSection={<TopSection title="Canonical Document" subtitle="Loading..." />}>
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="w-8 h-8 text-blue-600 animate-spin" />
        </div>
      </MainLayout>
    );
  }

  if (error || !canonical) {
    return (
      <MainLayout topSection={<TopSection title="Canonical Document" subtitle="Error" />}>
        <div className="bg-red-50 border border-red-200 rounded-lg p-6">
          <p className="text-red-800">{error || 'Canonical document not found'}</p>
          <button
            onClick={() => router.push('/sat-documents')}
            className="mt-4 text-blue-600 hover:text-blue-800 flex items-center gap-2"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Documents
          </button>
        </div>
      </MainLayout>
    );
  }

  const netAmount = parseFloat(canonical.amount_signed);
  const isPositive = netAmount > 0;
  const isNegative = netAmount < 0;

  return (
    <MainLayout
      topSection={
        <TopSection
          title="Canonical Merged Document"
          subtitle={`${canonical.vendor_name || canonical.vendor_rfc} - ${canonical.fiscal_year}-${canonical.fiscal_period.toString().padStart(2, '0')}`}
        />
      }
    >
      {/* Back Button */}
      <button
        onClick={() => router.push('/sat-documents')}
        className="mb-6 text-gray-600 hover:text-gray-900 flex items-center gap-2 transition-colors"
      >
        <ArrowLeft className="w-4 h-4" />
        Back to Documents
      </button>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column - Main Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Status Card */}
          <div className="bg-white shadow-sm rounded-lg p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-gray-900">Document Status</h2>
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                canonical.status === 'CONFIRMED' ? 'bg-green-100 text-green-800' :
                canonical.status === 'SENT' ? 'bg-blue-100 text-blue-800' :
                canonical.status === 'READY' ? 'bg-purple-100 text-purple-800' :
                canonical.status === 'FAILED' ? 'bg-red-100 text-red-800' :
                'bg-gray-100 text-gray-800'
              }`}>
                {canonical.status}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="flex items-start gap-3">
                <Building2 className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm text-gray-500">Vendor RFC</p>
                  <p className="font-medium text-gray-900">{canonical.vendor_rfc}</p>
                  {canonical.vendor_name && (
                    <p className="text-sm text-gray-600 mt-1">{canonical.vendor_name}</p>
                  )}
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Calendar className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm text-gray-500">Fiscal Period</p>
                  <p className="font-medium text-gray-900">
                    {canonical.fiscal_year}-{canonical.fiscal_period.toString().padStart(2, '0')}
                  </p>
                  <p className="text-sm text-gray-600 mt-1">
                    {new Date(canonical.fiscal_year, canonical.fiscal_period - 1).toLocaleString('en', { month: 'long', year: 'numeric' })}
                  </p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <Package className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm text-gray-500">Company Code</p>
                  <p className="font-medium text-gray-900">{canonical.company_code}</p>
                </div>
              </div>

              <div className="flex items-start gap-3">
                <FileText className="w-5 h-5 text-gray-400 mt-0.5" />
                <div>
                  <p className="text-sm text-gray-500">Document Type</p>
                  <p className="font-medium text-gray-900">{canonical.doc_type}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Financial Summary */}
          <div className="bg-white shadow-sm rounded-lg p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-6">Financial Summary</h2>
            
            <div className="space-y-4">
              {/* Total Invoices */}
              <div className="flex items-center justify-between py-3 border-b border-gray-100">
                <div className="flex items-center gap-3">
                  <TrendingUp className="w-5 h-5 text-green-600" />
                  <span className="text-gray-700">Total Invoices</span>
                </div>
                <span className="font-semibold text-green-600">
                  +{canonical.currency} {parseFloat(canonical.total_invoices).toFixed(2)}
                </span>
              </div>

              {/* Total Payments */}
              <div className="flex items-center justify-between py-3 border-b border-gray-100">
                <div className="flex items-center gap-3">
                  <Minus className="w-5 h-5 text-blue-600" />
                  <span className="text-gray-700">Total Payments</span>
                </div>
                <span className="font-semibold text-blue-600">
                  -{canonical.currency} {parseFloat(canonical.total_payments).toFixed(2)}
                </span>
              </div>

              {/* Total Credits */}
              <div className="flex items-center justify-between py-3 border-b border-gray-100">
                <div className="flex items-center gap-3">
                  <TrendingDown className="w-5 h-5 text-orange-600" />
                  <span className="text-gray-700">Total Credit Notes</span>
                </div>
                <span className="font-semibold text-orange-600">
                  -{canonical.currency} {parseFloat(canonical.total_credits).toFixed(2)}
                </span>
              </div>

              {/* Net Amount */}
              <div className="flex items-center justify-between py-4 bg-gray-50 rounded-lg px-4 mt-4">
                <div className="flex items-center gap-3">
                  <DollarSign className={`w-6 h-6 ${isPositive ? 'text-green-600' : isNegative ? 'text-red-600' : 'text-gray-600'}`} />
                  <span className="font-semibold text-gray-900 text-lg">Net Amount</span>
                </div>
                <span className={`font-bold text-xl ${isPositive ? 'text-green-600' : isNegative ? 'text-red-600' : 'text-gray-900'}`}>
                  {canonical.currency} {netAmount.toFixed(2)}
                </span>
              </div>

              {/* Tax Information */}
              {canonical.tax_base && (
                <div className="grid grid-cols-2 gap-4 mt-4 pt-4 border-t">
                  <div>
                    <p className="text-sm text-gray-500">Tax Base</p>
                    <p className="font-medium text-gray-900">
                      {canonical.currency} {parseFloat(canonical.tax_base).toFixed(2)}
                    </p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500">Tax Amount</p>
                    <p className="font-medium text-gray-900">
                      {canonical.currency} {parseFloat(canonical.tax_amount || '0').toFixed(2)}
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Linked Documents */}
          {linkedDocs.length > 0 && (
            <div className="bg-white shadow-sm rounded-lg p-6">
              <h2 className="text-xl font-semibold text-gray-900 mb-4">Linked Documents ({linkedDocs.length})</h2>
              <div className="space-y-3">
                {linkedDocs.map((doc) => (
                  <div key={doc.id} className="border border-gray-200 rounded-lg p-4 hover:border-blue-300 transition-colors">
                    <div className="flex items-center justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-2">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                            doc.documentType === 'INVOICE' ? 'bg-green-100 text-green-800' :
                            doc.documentType === 'PAYMENT' ? 'bg-blue-100 text-blue-800' :
                            doc.documentType === 'CREDIT_NOTE' ? 'bg-orange-100 text-orange-800' :
                            'bg-gray-100 text-gray-700'
                          }`}>
                            {doc.documentType}
                          </span>
                          {doc.folio && (
                            <span className="text-sm text-gray-600">Folio: {doc.folio}</span>
                          )}
                        </div>
                        <p className="text-xs text-gray-500 font-mono truncate">{doc.cfdiUuid}</p>
                        <div className="flex items-center gap-4 mt-2 text-sm">
                          {doc.fecha && (
                            <span className="text-gray-600">
                              {format(new Date(doc.fecha), 'MMM dd, yyyy')}
                            </span>
                          )}
                          {doc.total && (
                            <span className="font-medium text-gray-900">
                              ${parseFloat(doc.total).toFixed(2)}
                            </span>
                          )}
                        </div>
                      </div>
                      <button
                        onClick={() => router.push(`/sat-documents/${doc.id}`)}
                        className="text-blue-600 hover:text-blue-800 p-2"
                        title="View Document"
                      >
                        <ExternalLink className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right Column - Actions & Metadata */}
        <div className="space-y-6">
          {/* Actions Card */}
          <div className="bg-white shadow-sm rounded-lg p-6">
            <h3 className="font-semibold text-gray-900 mb-4">Actions</h3>
            <button
              onClick={handleSendToSAP}
              disabled={sending || canonical.status === 'SENT' || canonical.status === 'CONFIRMED'}
              className="w-full px-4 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 transition-colors disabled:bg-gray-300 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {sending ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Sending...
                </>
              ) : (
                <>
                  <Send className="w-4 h-4" />
                  Send to SAP
                </>
              )}
            </button>
          </div>

          {/* SAP Integration */}
          {canonical.sap_document_number && (
            <div className="bg-white shadow-sm rounded-lg p-6">
              <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
                <CheckCircle className="w-5 h-5 text-green-600" />
                SAP Integration
              </h3>
              <div className="space-y-3">
                <div>
                  <p className="text-sm text-gray-500">SAP Document Number</p>
                  <p className="font-medium text-gray-900">{canonical.sap_document_number}</p>
                </div>
                {canonical.sent_to_sap_at && (
                  <div>
                    <p className="text-sm text-gray-500">Sent to SAP</p>
                    <p className="text-sm text-gray-900">
                      {format(new Date(canonical.sent_to_sap_at), 'MMM dd, yyyy HH:mm')}
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Metadata */}
          <div className="bg-white shadow-sm rounded-lg p-6">
            <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
              <Clock className="w-5 h-5 text-gray-600" />
              Metadata
            </h3>
            <div className="space-y-3 text-sm">
              <div>
                <p className="text-gray-500">Created</p>
                <p className="text-gray-900">
                  {format(new Date(canonical.created_at), 'MMM dd, yyyy HH:mm')}
                </p>
              </div>
              {canonical.merged_at && (
                <div>
                  <p className="text-gray-500">Merged</p>
                  <p className="text-gray-900">
                    {format(new Date(canonical.merged_at), 'MMM dd, yyyy HH:mm')}
                  </p>
                </div>
              )}
              {canonical.doc_date && (
                <div>
                  <p className="text-gray-500">Document Date</p>
                  <p className="text-gray-900">
                    {format(new Date(canonical.doc_date), 'MMM dd, yyyy')}
                  </p>
                </div>
              )}
              {canonical.payment_date && (
                <div>
                  <p className="text-gray-500">Payment Date</p>
                  <p className="text-gray-900">
                    {format(new Date(canonical.payment_date), 'MMM dd, yyyy')}
                  </p>
                </div>
              )}
              {canonical.payment_method && (
                <div>
                  <p className="text-gray-500">Payment Method</p>
                  <p className="text-gray-900">{canonical.payment_method}</p>
                </div>
              )}
            </div>
          </div>

          {/* Document ID */}
          <div className="bg-gray-50 rounded-lg p-4">
            <p className="text-xs text-gray-500 mb-1">Canonical Document ID</p>
            <p className="text-xs font-mono text-gray-700 break-all">{canonical.id}</p>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}

