'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { satCanonicalApi, satApi } from '@/lib/api';
import {
  RefreshCw,
  Send,
  Calendar,
  DollarSign,
  Building2,
  FileText,
  CheckCircle,
  Clock,
  Eye
} from 'lucide-react';
import { format } from 'date-fns';

interface CanonicalDocument {
  id: string;
  vendor_rfc: string;
  vendor_name: string;
  fiscal_year: number;
  fiscal_period: number;
  total_invoices: number;
  total_credits: number;
  total_payments: number;
  net_amount: number;
  currency: string;
  sap_gl_account: string | null;
  status: string;
  sap_document_number: string | null;
  sent_to_sap_at: string | null;
  created_at: string;
}

export default function SATCanonicalTab() {
  const router = useRouter();
  const [canonicalDocs, setCanonicalDocs] = useState<CanonicalDocument[]>([]);
  const [individualDocs, setIndividualDocs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingIndividual, setLoadingIndividual] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [merging, setMerging] = useState(false);
  const [sendingId, setSendingId] = useState<string | null>(null);
  
  // Preview modal state
  const [showPreviewModal, setShowPreviewModal] = useState(false);
  const [previewJson, setPreviewJson] = useState<any | null>(null);
  const [previewCanonicalDoc, setPreviewCanonicalDoc] = useState<CanonicalDocument | null>(null);

  // Filters
  const [yearFilter, setYearFilter] = useState<number>(new Date().getFullYear());
  const [periodFilter, setPeriodFilter] = useState<number>(new Date().getMonth() + 1);

  useEffect(() => {
    fetchCanonicalDocuments();
    fetchIndividualDocuments();
  }, [yearFilter, periodFilter]);

  const fetchCanonicalDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await satCanonicalApi.list(yearFilter, periodFilter);
      
      setCanonicalDocs(response.documents || []);
      setTotalCount(response.total || 0);
    } catch (err: any) {
      console.error('Error fetching canonical documents:', err);
      setError(err.message || 'Failed to fetch canonical documents.');
    } finally {
      setLoading(false);
    }
  };

  const fetchIndividualDocuments = async () => {
    try {
      setLoadingIndividual(true);
      
      const response = await satApi.list(
        undefined,
        undefined,
        undefined,
        'VALIDATED'
      );

      // Filter by year and month
      const filtered = (response.documents || []).filter((doc: any) => {
        if (!doc.fecha) return false;
        const docDate = new Date(doc.fecha);
        return docDate.getFullYear() === yearFilter && (docDate.getMonth() + 1) === periodFilter;
      });

      setIndividualDocs(filtered);
    } catch (err: any) {
      console.error('Error fetching individual documents:', err);
    } finally {
      setLoadingIndividual(false);
    }
  };

  const handleMerge = async () => {
    try {
      setMerging(true);
      setError(null);

      await satCanonicalApi.merge({
        company_code: 'MX01',
        fiscal_year: yearFilter,
        fiscal_period: periodFilter
      });

      // Refresh data
      await fetchCanonicalDocuments();
      await fetchIndividualDocuments();
    } catch (err: any) {
      console.error('❌ Error merging documents:', err);
      setError(err.message || 'Failed to merge documents.');
    } finally {
      setMerging(false);
    }
  };

  const handleShowPreview = async (doc: CanonicalDocument) => {
    setPreviewCanonicalDoc(doc);
    setSendingId(doc.id);
    setError(null);
    
    try {
      const response = await satCanonicalApi.preview(doc.id);
      setPreviewJson(response.json_payload);
      setShowPreviewModal(true);
    } catch (err: any) {
      console.error('Error loading preview:', err);
      setError(err.message || 'Failed to generate preview');
    } finally {
      setSendingId(null);
    }
  };

  const handleConfirmSendToSAP = async () => {
    if (!previewCanonicalDoc) return;
    
    setShowPreviewModal(false);
    setSendingId(previewCanonicalDoc.id);
    setError(null);

    try {
      await satCanonicalApi.sendToSAP(previewCanonicalDoc.id);
      await fetchCanonicalDocuments();
    } catch (err: any) {
      console.error('Error sending to SAP:', err);
      setError(err.message || 'Failed to send to SAP.');
    } finally {
      setSendingId(null);
      setPreviewCanonicalDoc(null);
      setPreviewJson(null);
    }
  };

  const handleSendToSAP = async (doc: CanonicalDocument) => {
    await handleShowPreview(doc);
  };

  const formatCurrency = (amount: number, currency: string = 'MXN') => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency,
    }).format(amount);
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      MERGED: 'bg-blue-100 text-blue-800',
      SAP_SENT: 'bg-green-100 text-green-800',
      SAP_CONFIRMED: 'bg-green-600 text-white',
    };
    return styles[status as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  return (
    <div className="space-y-6">
      {/* Filters and Actions */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Filters & Actions</h2>
          <button
            onClick={fetchCanonicalDocuments}
            className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Fiscal Year
            </label>
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {[2023, 2024, 2025, 2026].map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Fiscal Period (Month)
            </label>
            <select
              value={periodFilter}
              onChange={(e) => setPeriodFilter(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
                <option key={month} value={month}>
                  {new Date(2000, month - 1, 1).toLocaleString('default', { month: 'long' })}
                </option>
              ))}
            </select>
          </div>

        </div>
        
        {/* Individual Documents Cards - Show before merge */}
        {individualDocs.length > 0 && (
          <div className="mt-6">
            <h3 className="text-sm font-medium text-gray-700 mb-3">
              Documents to be merged ({individualDocs.length})
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {individualDocs.map((doc) => {
                const docTypeColors = {
                  INVOICE: 'bg-green-50 border-green-200',
                  CREDIT_NOTE: 'bg-orange-50 border-orange-200',
                  PAYMENT: 'bg-blue-50 border-blue-200',
                };
                const docTypeIcons = {
                  INVOICE: 'text-green-600',
                  CREDIT_NOTE: 'text-orange-600',
                  PAYMENT: 'text-blue-600',
                };
                
                return (
                  <div
                    key={doc.id}
                    className={`border-2 rounded-lg p-4 ${docTypeColors[doc.doc_type as keyof typeof docTypeColors] || 'bg-gray-50 border-gray-200'}`}
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex items-center gap-2">
                        <FileText className={`w-5 h-5 ${docTypeIcons[doc.doc_type as keyof typeof docTypeIcons] || 'text-gray-600'}`} />
                        <span className="font-semibold text-gray-900">
                          {doc.doc_type.replace('_', ' ')}
                        </span>
                      </div>
                      <CheckCircle className="w-4 h-4 text-green-600" />
                    </div>
                    
                    <div className="space-y-2 text-sm">
                      <div className="flex justify-between">
                        <span className="text-gray-600">Serie-Folio:</span>
                        <span className="font-medium text-gray-900">
                          {doc.serie || 'N/A'}-{doc.folio || 'N/A'}
                        </span>
                      </div>
                      
                      <div className="flex justify-between">
                        <span className="text-gray-600">RFC:</span>
                        <span className="font-mono text-xs text-gray-900">
                          {doc.supplier_rfc}
                        </span>
                      </div>
                      
                      <div className="flex justify-between">
                        <span className="text-gray-600">Date:</span>
                        <span className="text-gray-900">
                          {doc.fecha ? format(new Date(doc.fecha), 'MMM dd, yyyy') : 'N/A'}
                        </span>
                      </div>
                      
                      <div className="flex justify-between pt-2 border-t border-gray-300">
                        <span className="text-gray-600 font-medium">Total:</span>
                        <span className="font-bold text-gray-900">
                          {formatCurrency(parseFloat(doc.total), doc.moneda)}
                        </span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
        
        <div className="mt-6 flex items-center gap-4">
          <button
            onClick={handleMerge}
            disabled={merging || individualDocs.length === 0}
            className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2 font-medium"
          >
            {merging ? (
              <>
                <RefreshCw className="w-5 h-5 animate-spin" />
                Merging Documents...
              </>
            ) : (
              <>
                <FileText className="w-5 h-5" />
                Generate Canonical ({individualDocs.length} docs)
              </>
            )}
          </button>
          
          {individualDocs.length === 0 && !loadingIndividual && (
            <div className="text-sm text-gray-600 italic">
              No validated documents found for this period
            </div>
          )}
          
          {loadingIndividual && (
            <div className="text-sm text-gray-600 italic flex items-center gap-2">
              <RefreshCw className="w-4 h-4 animate-spin" />
              Loading documents...
            </div>
          )}
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Canonical Documents List */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b border-gray-200">
          <h2 className="text-xl font-semibold text-gray-900">
            Canonical Merged Documents ({totalCount})
          </h2>
          <p className="text-sm text-gray-600 mt-1">
            Showing documents for {yearFilter}-{periodFilter.toString().padStart(2, '0')}
          </p>
        </div>

        {loading ? (
          <div className="p-12 text-center">
            <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading canonical documents...</p>
          </div>
        ) : canonicalDocs.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No Canonical Documents</h3>
            <p className="text-gray-600 mb-4">
              {individualDocs.length > 0
                ? `Click "Generate Canonical" to merge ${individualDocs.length} validated documents`
                : 'No validated documents available for this period'}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Vendor
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Period
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Invoices
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Credits
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Payments
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Net Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    GL Account
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
                {canonicalDocs.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Building2 className="w-4 h-4 text-gray-400" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.vendor_rfc}
                          </div>
                          <div className="text-sm text-gray-500">
                            {doc.vendor_name || 'N/A'}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4 text-gray-400" />
                        {doc.fiscal_year}-{doc.fiscal_period.toString().padStart(2, '0')}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-right text-green-600 font-medium">
                      {formatCurrency(doc.total_invoices, doc.currency)}
                    </td>
                    <td className="px-6 py-4 text-sm text-right text-orange-600 font-medium">
                      {formatCurrency(doc.total_credits, doc.currency)}
                    </td>
                    <td className="px-6 py-4 text-sm text-right text-blue-600 font-medium">
                      {formatCurrency(doc.total_payments, doc.currency)}
                    </td>
                    <td className="px-6 py-4 text-sm text-right font-bold text-gray-900">
                      {formatCurrency(doc.net_amount, doc.currency)}
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded text-xs font-medium">
                        {doc.sap_gl_account || 'No mapping'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(doc.status)}`}>
                        {doc.status}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2 justify-end">
                        {/* Details Button - Always visible */}
                        <button
                          onClick={() => router.push(`/sat-documents/canonical/${doc.id}`)}
                          className="px-3 py-2 text-sm font-medium text-blue-600 hover:text-blue-700 bg-blue-50 hover:bg-blue-100 border border-blue-200 hover:border-blue-300 rounded-lg transition-all duration-200 flex items-center gap-2 shadow-sm hover:shadow"
                        >
                          <Eye className="w-4 h-4" />
                          <span className="hidden sm:inline">Details</span>
                        </button>

                        {/* Send to SAP Button or Status */}
                        {doc.status === 'MERGED' ? (
                          <button
                            onClick={() => handleSendToSAP(doc)}
                            disabled={sendingId === doc.id}
                            className="px-4 py-2 text-sm font-semibold text-white bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed rounded-lg shadow-md hover:shadow-lg transition-all duration-200 flex items-center gap-2 min-w-[140px] justify-center"
                          >
                            {sendingId === doc.id ? (
                              <>
                                <RefreshCw className="w-4 h-4 animate-spin" />
                                <span className="hidden sm:inline">Sending...</span>
                              </>
                            ) : (
                              <>
                                <Send className="w-4 h-4" />
                                <span className="hidden sm:inline">Send to SAP</span>
                                <span className="sm:hidden">Send</span>
                              </>
                            )}
                          </button>
                        ) : (
                          <div className="flex items-center gap-2 px-4 py-2 bg-green-50 border border-green-200 rounded-lg text-sm">
                            <CheckCircle className="w-4 h-4 text-green-600 flex-shrink-0" />
                            <span className="text-green-800 font-medium hidden md:inline">
                              Sent: {doc.sap_document_number}
                            </span>
                            <span className="text-green-800 font-medium md:hidden">
                              Sent ✓
                            </span>
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Preview Modal */}
      {showPreviewModal && previewCanonicalDoc && previewJson && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col">
            <div className="p-6 border-b border-gray-200">
              <h3 className="text-xl font-semibold text-gray-900">SAP JSON Preview</h3>
              <p className="text-sm text-gray-600 mt-1">
                This is the format that will be sent to SAP
              </p>
            </div>

            <div className="p-6 overflow-auto flex-1">
              {/* Summary */}
              <div className="mb-4 p-4 bg-blue-50 rounded-lg">
                <h4 className="font-medium text-gray-900 mb-2">Document Summary</h4>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div><span className="text-gray-600">Vendor RFC:</span> <span className="font-medium">{previewCanonicalDoc.vendor_rfc}</span></div>
                  <div><span className="text-gray-600">Period:</span> <span className="font-medium">{previewCanonicalDoc.fiscal_year}-{previewCanonicalDoc.fiscal_period.toString().padStart(2, '0')}</span></div>
                  <div><span className="text-gray-600">Net Amount:</span> <span className="font-medium">{formatCurrency(previewCanonicalDoc.net_amount, previewCanonicalDoc.currency)}</span></div>
                  <div><span className="text-gray-600">GL Account:</span> <span className="font-medium">{previewCanonicalDoc.sap_gl_account || 'N/A'}</span></div>
                </div>
              </div>

              {/* JSON Preview */}
              <div className="bg-gray-900 rounded-lg p-4 overflow-auto">
                <pre className="text-green-400 text-xs font-mono whitespace-pre-wrap">
                  {JSON.stringify(previewJson, null, 2)}
                </pre>
              </div>
            </div>

            <div className="p-6 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowPreviewModal(false);
                  setPreviewCanonicalDoc(null);
                  setPreviewJson(null);
                }}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmSendToSAP}
                className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 transition-colors flex items-center gap-2"
              >
                <Send className="w-4 h-4" />
                Confirm & Send to SAP
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

