'use client';

import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { satCanonicalApi, satApi } from '@/lib/api';
import { 
  TrendingUp, 
  RefreshCw, 
  Send, 
  CheckCircle, 
  XCircle, 
  Clock,
  FileText,
  AlertCircle,
  Layers,
  Package
} from 'lucide-react';

interface CanonicalDocument {
  id: string;
  company_code: string;
  fiscal_year: number;
  fiscal_period: number;
  vendor_rfc: string;
  vendor_name: string | null;
  doc_type: string;
  total_invoices: string;
  total_credits: string;
  total_payments: string;
  net_amount: string;
  amount_signed: string;
  currency: string;
  tax_base: string | null;
  tax_amount: string | null;
  payment_date: string | null;
  payment_method: string | null;
  status: string;
  sap_document_number: string | null;
  merged_at: string | null;
  sent_to_sap_at: string | null;
}

export default function SATCanonicalTab() {
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
  const [previewData, setPreviewData] = useState<any>(null);
  const [loadingPreview, setLoadingPreview] = useState(false);
  const [selectedCanonicalId, setSelectedCanonicalId] = useState<string | null>(null);

  const router = useRouter();
  
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

      const response = await satCanonicalApi.list({
        fiscal_year: yearFilter,
        fiscal_period: periodFilter
      });

      setCanonicalDocs(response.documents || []);
      setTotalCount(response.total || 0);
    } catch (err: any) {
      console.error('Error fetching canonical documents:', err);
      setError(err.message || 'Failed to load canonical documents');
    } finally {
      setLoading(false);
    }
  };

  const fetchIndividualDocuments = async () => {
    try {
      setLoadingIndividual(true);

      const response = await satApi.getDocuments({
        limit: 100,
        skip: 0
      });

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
    } catch (err: any) {
      console.error('❌ Error merging documents:', err);
      setError(err.message || 'Failed to merge documents');
    } finally {
      setMerging(false);
    }
  };

  const handleShowPreview = async (canonicalId: string) => {
    try {
      setLoadingPreview(true);
      setError(null);
      setSelectedCanonicalId(canonicalId);

      const preview = await satCanonicalApi.preview(canonicalId);
      setPreviewData(preview);
      setShowPreviewModal(true);
    } catch (err: any) {
      console.error('Error loading preview:', err);
      setError(err.message || 'Failed to load preview');
    } finally {
      setLoadingPreview(false);
    }
  };

  const handleConfirmSend = async () => {
    if (!selectedCanonicalId) return;

    try {
      setSendingId(selectedCanonicalId);
      setShowPreviewModal(false);
      setError(null);

      await satCanonicalApi.sendToSAP(selectedCanonicalId);

      // Refresh data
      await fetchCanonicalDocuments();
      setSelectedCanonicalId(null);
      setPreviewData(null);
    } catch (err: any) {
      console.error('Error sending to SAP:', err);
      setError(err.message || 'Failed to send to SAP');
    } finally {
      setSendingId(null);
    }
  };

  const handleSendToSAP = async (canonicalId: string) => {
    // Show preview modal instead of sending directly
    await handleShowPreview(canonicalId);
  };

  const getStatusColor = (status: string) => {
    switch (status.toUpperCase()) {
      case 'DRAFT':
        return 'bg-gray-100 text-gray-700';
      case 'READY':
        return 'bg-blue-100 text-blue-700';
      case 'SENT':
        return 'bg-yellow-100 text-yellow-700';
      case 'CONFIRMED':
        return 'bg-green-100 text-green-700';
      case 'FAILED':
        return 'bg-red-100 text-red-700';
      default:
        return 'bg-gray-100 text-gray-700';
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status.toUpperCase()) {
      case 'CONFIRMED':
        return <CheckCircle className="w-4 h-4" />;
      case 'FAILED':
        return <XCircle className="w-4 h-4" />;
      case 'SENT':
        return <Send className="w-4 h-4" />;
      case 'READY':
        return <Clock className="w-4 h-4" />;
      default:
        return <FileText className="w-4 h-4" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Layers className="w-6 h-6 text-blue-600" />
            Canonical Merged Documents
          </h2>
          <p className="text-gray-600 mt-1">
            3 SAT documents (Invoice + Payment + Credit Note) merged into 1 canonical format for SAP
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchCanonicalDocuments}
            disabled={loading}
            className="p-2 text-gray-600 hover:text-blue-600 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Filters and Merge Button */}
      <div className="bg-white p-4 rounded-lg border border-gray-200 flex items-center gap-4">
        <div className="flex-1 flex items-center gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Year</label>
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(Number(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {[2024, 2025, 2026].map(year => (
                <option key={year} value={year}>{year}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Period (Month)</label>
            <select
              value={periodFilter}
              onChange={(e) => setPeriodFilter(Number(e.target.value))}
              className="px-3 py-2 border border-gray-300 rounded-md text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map(month => (
                <option key={month} value={month}>
                  {new Date(2024, month - 1).toLocaleString('en', { month: 'long' })} ({month})
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={handleMerge}
          disabled={merging}
          className="px-6 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 transition-colors disabled:bg-blue-400 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {merging ? (
            <>
              <RefreshCw className="w-4 h-4 animate-spin" />
              Merging...
            </>
          ) : (
            <>
              <Layers className="w-4 h-4" />
              Generate Canonical
            </>
          )}
        </button>
      </div>

      {/* Individual Documents Preview */}
      {individualDocs.length > 0 && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <div className="flex items-center gap-2 mb-3">
            <Package className="w-5 h-5 text-blue-600" />
            <h3 className="font-medium text-blue-900">
              Documents to Merge ({individualDocs.length})
            </h3>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {individualDocs.map((doc, idx) => (
              <div key={doc.id || idx} className="bg-white rounded-md p-3 border border-blue-200">
                <div className="flex items-center justify-between mb-2">
                  <span className={`text-xs font-medium px-2 py-1 rounded ${
                    doc.document_type === 'INVOICE' ? 'bg-green-100 text-green-700' :
                    doc.document_type === 'PAYMENT' ? 'bg-blue-100 text-blue-700' :
                    'bg-orange-100 text-orange-700'
                  }`}>
                    {doc.document_type}
                  </span>
                  <span className={`text-xs px-2 py-1 rounded ${
                    doc.status === 'VALIDATED' ? 'bg-green-100 text-green-700' :
                    doc.status === 'READY_FOR_SAP' ? 'bg-blue-100 text-blue-700' :
                    'bg-gray-100 text-gray-700'
                  }`}>
                    {doc.status}
                  </span>
                </div>
                <div className="text-sm space-y-1">
                  <div className="font-medium text-gray-900 truncate">
                    {doc.supplierRfc || 'Unknown RFC'}
                  </div>
                  <div className="text-gray-600 text-xs truncate">
                    {doc.supplierName || 'Unknown Supplier'}
                  </div>
                  {doc.fecha && (
                    <div className="text-gray-500 text-xs flex items-center gap-1">
                      <Clock className="w-3 h-3" />
                      {new Date(doc.fecha).toLocaleDateString('en-US', { 
                        year: 'numeric', 
                        month: 'short', 
                        day: 'numeric' 
                      })}
                    </div>
                  )}
                  <div className="text-gray-900 font-bold">
                    ${parseFloat(doc.total || 0).toFixed(2)} {doc.moneda || 'MXN'}
                  </div>
                </div>
              </div>
            ))}
          </div>
          {individualDocs.length >= 3 && (
            <div className="mt-3 text-sm text-blue-700">
              ✅ Ready to merge {individualDocs.length} documents into 1 canonical format
            </div>
          )}
        </div>
      )}

      {loadingIndividual && individualDocs.length === 0 && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 text-center">
          <RefreshCw className="w-5 h-5 text-gray-400 animate-spin mx-auto mb-2" />
          <p className="text-sm text-gray-600">Loading documents for this period...</p>
        </div>
      )}

      {!loadingIndividual && individualDocs.length === 0 && (
        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-yellow-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="font-medium text-yellow-900">No Documents Found</h3>
            <p className="text-sm text-yellow-700 mt-1">
              No SAT documents found for {yearFilter}-{periodFilter.toString().padStart(2, '0')}. 
              Please send documents first before merging.
            </p>
          </div>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <div>
            <h3 className="font-medium text-red-900">Error</h3>
            <p className="text-sm text-red-700 mt-1">{error}</p>
          </div>
        </div>
      )}

      {/* Loading State */}
      {loading && canonicalDocs.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <RefreshCw className="w-8 h-8 text-blue-600 animate-spin mx-auto mb-4" />
          <p className="text-gray-600">Loading canonical documents...</p>
        </div>
      ) : canonicalDocs.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No Canonical Documents Found</h3>
          <p className="text-gray-600 mb-4">
            No merged documents for {yearFilter}-{periodFilter.toString().padStart(2, '0')}
          </p>
          <button
            onClick={handleMerge}
            disabled={merging}
            className="px-4 py-2 bg-blue-600 text-white font-medium rounded-md hover:bg-blue-700 transition-colors disabled:bg-blue-400"
          >
            Generate Canonical Document
          </button>
        </div>
      ) : (
        <>
          {/* Table */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Vendor
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Period
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Invoices
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Credits
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Payments
                    </th>
                    <th className="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Net Amount
                    </th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                      GL Account
                    </th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th className="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {canonicalDocs.map((doc) => (
                    <tr key={doc.id} className="hover:bg-gray-50">
                      <td className="px-4 py-4">
                        <div className="text-sm font-medium text-gray-900">{doc.vendor_rfc}</div>
                        <div className="text-sm text-gray-500">{doc.vendor_name || 'N/A'}</div>
                      </td>
                      <td className="px-4 py-4 whitespace-nowrap">
                        <div className="text-sm text-gray-900">
                          {doc.fiscal_year}-{doc.fiscal_period.toString().padStart(2, '0')}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        <div className="text-sm font-medium text-green-600">
                          ${parseFloat(doc.total_invoices).toFixed(2)}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        <div className="text-sm font-medium text-orange-600">
                          ${parseFloat(doc.total_credits).toFixed(2)}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        <div className="text-sm font-medium text-blue-600">
                          ${parseFloat(doc.total_payments).toFixed(2)}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-right whitespace-nowrap">
                        <div className={`text-sm font-bold ${parseFloat(doc.net_amount) < 0 ? 'text-red-600' : 'text-gray-900'}`}>
                          ${parseFloat(doc.net_amount).toFixed(2)} {doc.currency}
                        </div>
                      </td>
                      <td className="px-4 py-4 text-center">
                        <div className="text-sm font-mono font-medium text-blue-600">
                          {doc.sap_gl_account || 'N/A'}
                        </div>
                        {!doc.sap_gl_account && (
                          <div className="text-xs text-orange-600 mt-1">
                            No mapping
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-4 text-center">
                        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium ${getStatusColor(doc.status)}`}>
                          {getStatusIcon(doc.status)}
                          {doc.status}
                        </span>
                      </td>
                      <td className="px-4 py-4 text-center whitespace-nowrap">
                        <div className="flex items-center justify-center gap-2">
                          <button
                            onClick={() => router.push(`/sat-documents/canonical/${doc.id}`)}
                            className="inline-flex items-center gap-1 px-3 py-1.5 bg-gray-100 text-gray-700 text-sm font-medium rounded-md hover:bg-gray-200 transition-colors"
                            title="View Details"
                          >
                            <FileText className="w-3 h-3" />
                            Details
                          </button>
                          {doc.status === 'READY' || doc.status === 'FAILED' ? (
                            <button
                              onClick={() => handleSendToSAP(doc.id)}
                              disabled={sendingId === doc.id}
                              className="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors disabled:bg-blue-400 disabled:cursor-not-allowed"
                            >
                              {sendingId === doc.id ? (
                                <>
                                  <RefreshCw className="w-3 h-3 animate-spin" />
                                  Sending...
                                </>
                              ) : (
                                <>
                                  <Send className="w-3 h-3" />
                                  Send
                                </>
                              )}
                            </button>
                          ) : doc.status === 'CONFIRMED' && (
                            <div className="text-xs text-green-600 font-medium">
                              ✓ Sent
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Footer */}
          <div className="bg-white rounded-lg border border-gray-200 p-4">
            <div className="flex items-center justify-between text-sm text-gray-600">
              <div>
                Showing <span className="font-medium text-gray-900">{canonicalDocs.length}</span> canonical document{canonicalDocs.length !== 1 ? 's' : ''}
              </div>
              <div>
                Total: <span className="font-medium text-gray-900">{totalCount}</span>
              </div>
            </div>
          </div>
        </>
      )}

      {/* Preview Modal */}
      {showPreviewModal && previewData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-gray-200 bg-blue-50">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-bold text-gray-900">Preview SAP Payload</h2>
                  <p className="text-sm text-blue-700 mt-1">
                    {previewData.message || "This is the format that will be sent to SAP"}
                  </p>
                </div>
                <button
                  onClick={() => {
                    setShowPreviewModal(false);
                    setPreviewData(null);
                    setSelectedCanonicalId(null);
                  }}
                  className="text-gray-400 hover:text-gray-600 transition-colors"
                >
                  <XCircle className="w-6 h-6" />
                </button>
              </div>
            </div>

            {/* Modal Body */}
            <div className="flex-1 overflow-y-auto p-6">
              {/* Summary Section */}
              <div className="bg-gray-50 rounded-lg p-4 mb-6">
                <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
                  <Package className="w-4 h-4" />
                  Summary
                </h3>
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-gray-600">Vendor:</span>
                    <span className="ml-2 font-medium text-gray-900">
                      {previewData.summary.vendor_name} ({previewData.summary.vendor_rfc})
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Period:</span>
                    <span className="ml-2 font-medium text-gray-900">
                      {previewData.summary.fiscal_year}-{previewData.summary.fiscal_period.toString().padStart(2, '0')}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Total Invoices:</span>
                    <span className="ml-2 font-medium text-green-600">
                      ${parseFloat(previewData.summary.total_invoices).toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Total Credits:</span>
                    <span className="ml-2 font-medium text-orange-600">
                      ${parseFloat(previewData.summary.total_credits).toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Total Payments:</span>
                    <span className="ml-2 font-medium text-blue-600">
                      ${parseFloat(previewData.summary.total_payments).toFixed(2)}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Net Amount:</span>
                    <span className={`ml-2 font-bold ${parseFloat(previewData.summary.net_amount) < 0 ? 'text-red-600' : 'text-gray-900'}`}>
                      ${parseFloat(previewData.summary.net_amount).toFixed(2)} {previewData.summary.currency}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">GL Account:</span>
                    <span className="ml-2 font-mono font-medium text-blue-600">
                      {previewData.summary.sap_gl_account}
                    </span>
                  </div>
                  <div>
                    <span className="text-gray-600">Documents Included:</span>
                    <span className="ml-2 font-medium text-gray-900">
                      {previewData.summary.documents_included} CFDIs
                    </span>
                  </div>
                </div>
              </div>

              {/* SAP XML Section */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                    <FileText className="w-4 h-4" />
                    SAP XML Payload
                  </h3>
                  <button
                    onClick={() => {
                      navigator.clipboard.writeText(previewData.sap_xml);
                      alert('XML copied to clipboard!');
                    }}
                    className="text-xs px-3 py-1 bg-gray-200 hover:bg-gray-300 rounded text-gray-700 font-medium transition-colors"
                  >
                    Copy XML
                  </button>
                </div>
                <div className="bg-gray-900 rounded-lg p-4 overflow-x-auto">
                  <pre className="text-xs text-green-400 font-mono whitespace-pre-wrap break-all">
                    {previewData.sap_xml}
                  </pre>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 flex items-center justify-end gap-3">
              <button
                onClick={() => {
                  setShowPreviewModal(false);
                  setPreviewData(null);
                  setSelectedCanonicalId(null);
                }}
                className="px-4 py-2 border border-gray-300 rounded-md text-gray-700 font-medium hover:bg-gray-100 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmSend}
                disabled={sendingId !== null}
                className="px-4 py-2 bg-blue-600 text-white rounded-md font-medium hover:bg-blue-700 transition-colors disabled:bg-blue-400 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {sendingId ? (
                  <>
                    <RefreshCw className="w-4 h-4 animate-spin" />
                    Sending...
                  </>
                ) : (
                  <>
                    <Send className="w-4 h-4" />
                    Confirm & Send to SAP
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

