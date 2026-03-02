'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { satCanonicalApi, satSimpleMergeApi } from '@/lib/api';
import {
  RefreshCw,
  Send,
  Calendar,
  DollarSign,
  Building2,
  FileText,
  CheckCircle,
  AlertCircle,
  Eye,
  Loader2,
  X,
  Copy
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
  sent_to_sap: boolean;
  sap_document_number: string | null;
  sent_to_sap_at: string | null;
}

export default function SAPSendTab() {
  const router = useRouter();
  const [canonicalDocs, setCanonicalDocs] = useState<CanonicalDocument[]>([]);
  const [simpleDocs, setSimpleDocs] = useState<SimpleMergedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState<{ [key: string]: boolean }>({});
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [csrfTokens, setCsrfTokens] = useState<{ [key: string]: string }>({});  // Store CSRF tokens per document
  const [fetchingCsrf, setFetchingCsrf] = useState<{ [key: string]: boolean }>({});
  const [showSapModal, setShowSapModal] = useState(false);
  const [sapResponseData, setSapResponseData] = useState<any>(null);

  // Filters
  const [yearFilter, setYearFilter] = useState<number>(new Date().getFullYear());
  const [periodFilter, setPeriodFilter] = useState<number>(new Date().getMonth() + 1);
  const [activeSection, setActiveSection] = useState<'canonical' | 'simple'>('canonical');

  useEffect(() => {
    fetchData();
  }, [yearFilter, periodFilter]);

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);

      const [canonicalResponse, simpleResponse] = await Promise.all([
        satCanonicalApi.list(yearFilter, periodFilter),
        satSimpleMergeApi.list(yearFilter, periodFilter)
      ]);

      setCanonicalDocs(canonicalResponse.documents || []);
      setSimpleDocs(simpleResponse.documents || []);
    } catch (err: any) {
      console.error('Error fetching documents:', err);
      setError(err.message || 'Failed to fetch documents.');
    } finally {
      setLoading(false);
    }
  };

  const handleSendCanonicalToSAP = async (doc: CanonicalDocument) => {
    const docKey = `canonical-${doc.id}`;
    setSending(prev => ({ ...prev, [docKey]: true }));
    setError(null);
    setSuccess(null);

    try {
      const response = await satCanonicalApi.sendToSAP(doc.id);
      setSuccess(`✅ Canonical document sent successfully! SAP Doc #: ${response.sap_document_number}`);
      await fetchData(); // Refresh to show updated status
    } catch (err: any) {
      console.error('Error sending canonical to SAP:', err);
      setError(err.message || 'Failed to send canonical document to SAP.');
    } finally {
      setSending(prev => ({ ...prev, [docKey]: false }));
    }
  };

  const handleFetchCsrfToken = async (doc: SimpleMergedDocument) => {
    const docKey = `simple-${doc.id}`;
    setFetchingCsrf(prev => ({ ...prev, [docKey]: true }));
    setError(null);
    setSuccess(null);

    try {
      const response = await satSimpleMergeApi.fetchCsrfToken(doc.id);
      setCsrfTokens(prev => ({ ...prev, [docKey]: response.csrf_token }));
      setSuccess(`✅ CSRF Token fetched! Token: ${response.csrf_token.substring(0, 20)}...`);
    } catch (err: any) {
      console.error('Error fetching CSRF token:', err);
      setError(err.message || 'Failed to fetch CSRF token from SAP.');
    } finally {
      setFetchingCsrf(prev => ({ ...prev, [docKey]: false }));
    }
  };

  const handleSendSimpleToSAP = async (doc: SimpleMergedDocument) => {
    const docKey = `simple-${doc.id}`;
    
    // Check if CSRF token exists
    if (!csrfTokens[docKey]) {
      setError('Please fetch CSRF token first before sending to SAP.');
      return;
    }
    
    setSending(prev => ({ ...prev, [docKey]: true }));
    setError(null);
    setSuccess(null);

    try {
      // Send to SAP with the fetched CSRF token
      const response = await satSimpleMergeApi.sendToSAP(doc.id, csrfTokens[docKey]);
      setSuccess(`✅ Simple merged document sent successfully! SAP Doc #: ${response.sap_document_number}`);
      
      // Store SAP response data for modal display
      setSapResponseData(response);
      setShowSapModal(true);
      
      await fetchData(); // Refresh to show updated status
      // Clear CSRF token after successful send
      setCsrfTokens(prev => {
        const newTokens = { ...prev };
        delete newTokens[docKey];
        return newTokens;
      });
    } catch (err: any) {
      console.error('Error sending simple merge to SAP:', err);
      setError(err.message || 'Failed to send simple merged document to SAP.');
    } finally {
      setSending(prev => ({ ...prev, [docKey]: false }));
    }
  };

  const formatCurrency = (amount: number, currency: string = 'MXN') => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency || 'MXN',
    }).format(amount);
  };

  const getMonthName = (month: number) => {
    return new Date(2000, month - 1, 1).toLocaleString('default', { month: 'long' });
  };

  // Filter out already sent documents
  const pendingCanonicalDocs = canonicalDocs.filter(
    doc => doc.status === 'MERGED' && !doc.sap_document_number
  );

  const pendingSimpleDocs = simpleDocs.filter(
    doc => !doc.sent_to_sap && !doc.sap_document_number
  );

  return (
    <div className="space-y-6">
      {/* Header with Info */}
      <div className="bg-gradient-to-r from-green-50 to-blue-50 rounded-lg border border-green-200 p-6">
        <div className="flex items-start gap-4">
          <div className="p-3 bg-white rounded-lg shadow-sm">
            <Send className="w-8 h-8 text-green-600" />
          </div>
          <div className="flex-1">
            <h2 className="text-2xl font-bold text-gray-900 mb-2">Send Documents to SAP</h2>
            <p className="text-gray-700 mb-4">
              Send your merged documents (Simple Merge or Canonical Merge) to SAP ERP. 
              Both types will be sent to the SAP endpoint configured by your client.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
              <div className="flex items-center gap-2 text-gray-700">
                <CheckCircle className="w-4 h-4 text-green-600" />
                <span><strong>Simple Merge:</strong> Raw XML with all CFDI documents</span>
              </div>
              <div className="flex items-center gap-2 text-gray-700">
                <CheckCircle className="w-4 h-4 text-green-600" />
                <span><strong>Canonical Merge:</strong> JSON payload with financial summary</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-900">Filters</h3>
          <button
            onClick={fetchData}
            className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Fiscal Year
            </label>
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
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
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-green-500 focus:border-transparent"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
                <option key={month} value={month}>
                  {getMonthName(month)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Success/Error Messages */}
      {success && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
          <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
          <p className="text-green-800 font-medium">{success}</p>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Section Tabs */}
      <div className="bg-white rounded-lg shadow">
        <div className="border-b border-gray-200">
          <div className="flex gap-4 px-6">
            <button
              onClick={() => setActiveSection('canonical')}
              className={`py-4 px-4 font-medium text-sm border-b-2 transition-colors ${
                activeSection === 'canonical'
                  ? 'border-green-600 text-green-600'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              }`}
            >
              Canonical Merged ({pendingCanonicalDocs.length})
            </button>
            <button
              onClick={() => setActiveSection('simple')}
              className={`py-4 px-4 font-medium text-sm border-b-2 transition-colors ${
                activeSection === 'simple'
                  ? 'border-green-600 text-green-600'
                  : 'border-transparent text-gray-600 hover:text-gray-900'
              }`}
            >
              Simple Merged ({pendingSimpleDocs.length})
            </button>
          </div>
        </div>

        {/* Loading State */}
        {loading ? (
          <div className="p-12 text-center">
            <Loader2 className="w-8 h-8 animate-spin text-green-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading documents...</p>
          </div>
        ) : (
          <div className="p-6">
            {/* Canonical Merged Documents */}
            {activeSection === 'canonical' && (
              <div>
                {pendingCanonicalDocs.length === 0 ? (
                  <div className="text-center py-12">
                    <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No Pending Canonical Documents</h3>
                    <p className="text-gray-600">
                      All canonical merged documents have been sent to SAP, or there are no documents for this period.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {pendingCanonicalDocs.map((doc) => {
                      const docKey = `canonical-${doc.id}`;
                      const isSending = sending[docKey];

                      return (
                        <div
                          key={doc.id}
                          className="border-2 border-gray-200 hover:border-green-300 rounded-lg p-6 transition-all hover:shadow-md"
                        >
                          <div className="flex items-start justify-between mb-4">
                            <div className="flex-1">
                              <div className="flex items-center gap-3 mb-2">
                                <Building2 className="w-5 h-5 text-blue-600" />
                                <h3 className="text-lg font-semibold text-gray-900">
                                  {doc.vendor_name || doc.vendor_rfc}
                                </h3>
                                <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs font-medium rounded-full">
                                  Canonical
                                </span>
                              </div>
                              <div className="flex items-center gap-4 text-sm text-gray-600">
                                <span className="flex items-center gap-1">
                                  <span className="font-medium">RFC:</span>
                                  <span className="font-mono">{doc.vendor_rfc}</span>
                                </span>
                                <span className="flex items-center gap-1">
                                  <Calendar className="w-4 h-4" />
                                  {getMonthName(doc.fiscal_period)} {doc.fiscal_year}
                                </span>
                              </div>
                            </div>
                            <div className="text-right">
                              <div className="text-sm text-gray-600 mb-1">Net Amount</div>
                              <div className="text-xl font-bold text-gray-900">
                                {formatCurrency(doc.net_amount, doc.currency)}
                              </div>
                            </div>
                          </div>

                          <div className="grid grid-cols-3 gap-4 mb-4 p-4 bg-gray-50 rounded-lg">
                            <div>
                              <div className="text-xs text-gray-600 mb-1">Invoices</div>
                              <div className="text-sm font-semibold text-green-600">
                                {formatCurrency(doc.total_invoices, doc.currency)}
                              </div>
                            </div>
                            <div>
                              <div className="text-xs text-gray-600 mb-1">Credits</div>
                              <div className="text-sm font-semibold text-orange-600">
                                {formatCurrency(doc.total_credits, doc.currency)}
                              </div>
                            </div>
                            <div>
                              <div className="text-xs text-gray-600 mb-1">Payments</div>
                              <div className="text-sm font-semibold text-blue-600">
                                {formatCurrency(doc.total_payments, doc.currency)}
                              </div>
                            </div>
                          </div>

                          <div className="flex items-center gap-3">
                            <button
                              onClick={() => router.push(`/sat-documents/canonical/${doc.id}`)}
                              className="px-4 py-2 text-sm font-medium text-blue-600 bg-blue-50 hover:bg-blue-100 border border-blue-200 rounded-lg transition-colors flex items-center gap-2"
                            >
                              <Eye className="w-4 h-4" />
                              View Details
                            </button>
                            <button
                              onClick={() => handleSendCanonicalToSAP(doc)}
                              disabled={isSending}
                              className="flex-1 px-6 py-3 text-sm font-semibold text-white bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed rounded-lg shadow-md hover:shadow-lg transition-all duration-200 flex items-center justify-center gap-2"
                            >
                              {isSending ? (
                                <>
                                  <Loader2 className="w-5 h-5 animate-spin" />
                                  Sending to SAP...
                                </>
                              ) : (
                                <>
                                  <Send className="w-5 h-5" />
                                  Send to SAP
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Simple Merged Documents */}
            {activeSection === 'simple' && (
              <div>
                {pendingSimpleDocs.length === 0 ? (
                  <div className="text-center py-12">
                    <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                    <h3 className="text-lg font-medium text-gray-900 mb-2">No Pending Simple Merged Documents</h3>
                    <p className="text-gray-600">
                      All simple merged documents have been sent to SAP, or there are no documents for this period.
                    </p>
                  </div>
                ) : (
                  <div className="space-y-4">
                    {pendingSimpleDocs.map((doc) => {
                      const docKey = `simple-${doc.id}`;
                      const isSending = sending[docKey];
                      const isFetchingCsrf = fetchingCsrf[docKey];

                      return (
                        <div
                          key={doc.id}
                          className="border-2 border-gray-200 hover:border-purple-300 rounded-lg p-6 transition-all hover:shadow-md"
                        >
                          <div className="flex items-start justify-between mb-4">
                            <div className="flex-1">
                              <div className="flex items-center gap-3 mb-2">
                                <Building2 className="w-5 h-5 text-purple-600" />
                                <h3 className="text-lg font-semibold text-gray-900">
                                  {doc.vendor_name || doc.vendor_rfc}
                                </h3>
                                <span className="px-2 py-1 bg-purple-100 text-purple-800 text-xs font-medium rounded-full">
                                  Simple Merge
                                </span>
                              </div>
                              <div className="flex items-center gap-4 text-sm text-gray-600">
                                <span className="flex items-center gap-1">
                                  <span className="font-medium">RFC:</span>
                                  <span className="font-mono">{doc.vendor_rfc}</span>
                                </span>
                                <span className="flex items-center gap-1">
                                  <Calendar className="w-4 h-4" />
                                  {getMonthName(doc.fiscal_period)} {doc.fiscal_year}
                                </span>
                                <span className="flex items-center gap-1">
                                  <FileText className="w-4 h-4" />
                                  {doc.document_count} documents
                                </span>
                              </div>
                            </div>
                            <div className="text-right">
                              <div className="text-sm text-gray-600 mb-1">Total Amount</div>
                              <div className="text-xl font-bold text-gray-900">
                                {formatCurrency(doc.total_amount, doc.currency)}
                              </div>
                            </div>
                          </div>

                          <div className="mb-4 p-4 bg-purple-50 border border-purple-200 rounded-lg">
                            <div className="text-xs font-medium text-purple-800 mb-2">Document Types:</div>
                            <div className="flex flex-wrap gap-2">
                              {doc.document_types.map((type, idx) => (
                                <span key={idx} className="px-2 py-1 bg-white text-purple-700 text-xs font-medium rounded border border-purple-200">
                                  {type}
                                </span>
                              ))}
                            </div>
                          </div>

                          <div className="space-y-3">
                            {/* CSRF Token Status */}
                            {csrfTokens[docKey] && (
                              <div className="bg-green-50 border border-green-200 rounded p-2">
                                <div className="text-xs text-green-800 flex items-center gap-2">
                                  <CheckCircle className="w-4 h-4" />
                                  <span>CSRF Token Ready: {csrfTokens[docKey].substring(0, 15)}...</span>
                                </div>
                              </div>
                            )}
                            
                            <div className="flex items-center gap-3">
                              <button
                                onClick={() => router.push(`/sat-documents/simple-merge/${doc.id}`)}
                                className="px-4 py-2 text-sm font-medium text-purple-600 bg-purple-50 hover:bg-purple-100 border border-purple-200 rounded-lg transition-colors flex items-center gap-2"
                              >
                                <Eye className="w-4 h-4" />
                                View
                              </button>
                              
                              <button
                                onClick={() => handleFetchCsrfToken(doc)}
                                disabled={isFetchingCsrf}
                                className="px-4 py-2 text-sm font-medium text-green-600 bg-green-50 hover:bg-green-100 border border-green-200 rounded-lg transition-colors flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
                              >
                                {isFetchingCsrf ? (
                                  <>
                                    <Loader2 className="w-4 h-4 animate-spin" />
                                    Fetching...
                                  </>
                                ) : (
                                  <>
                                    <CheckCircle className="w-4 h-4" />
                                    {csrfTokens[docKey] ? 'Refresh Token' : 'Get CSRF Token'}
                                  </>
                                )}
                              </button>
                              
                              <button
                                onClick={() => handleSendSimpleToSAP(doc)}
                                disabled={isSending || !csrfTokens[docKey]}
                                className="flex-1 px-6 py-3 text-sm font-semibold text-white bg-gradient-to-r from-purple-600 to-purple-700 hover:from-purple-700 hover:to-purple-800 disabled:from-gray-300 disabled:to-gray-400 disabled:cursor-not-allowed rounded-lg shadow-md hover:shadow-lg transition-all duration-200 flex items-center justify-center gap-2"
                                title={!csrfTokens[docKey] ? 'Fetch CSRF token first' : ''}
                              >
                                {isSending ? (
                                  <>
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    Sending to SAP...
                                  </>
                                ) : (
                                  <>
                                    <Send className="w-5 h-5" />
                                    Send to SAP
                                  </>
                                )}
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
        <div className="flex gap-3">
          <AlertCircle className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-blue-900 mb-2">About Sending to SAP</h4>
            <ul className="text-sm text-blue-800 space-y-1">
              <li>• <strong>Canonical Merge:</strong> Sends JSON payload with financial summary (invoices, credits, payments)</li>
              <li>• <strong>Simple Merge:</strong> Sends raw XML with all CFDI documents</li>
              <li>• Both are sent to the SAP endpoint: <code className="bg-blue-100 px-1 rounded">saperp.abor-tech.online</code></li>
              <li>• Documents can only be sent once. After sending, they will not appear in this list.</li>
            </ul>
          </div>
        </div>
      </div>

      {/* SAP Response Modal */}
      {showSapModal && sapResponseData && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
            {/* Header */}
            <div className="sticky top-0 bg-white px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-green-100 rounded-lg">
                  <CheckCircle className="w-5 h-5 text-green-600" />
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-gray-900">Document Sent to SAP</h3>
                  <p className="text-xs text-gray-500">SAP Doc #: {sapResponseData.sap_document_number}</p>
                </div>
              </div>
              <button
                onClick={() => {
                  setShowSapModal(false);
                  setSapResponseData(null);
                }}
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-6 h-6" />
              </button>
            </div>

            {/* Content */}
            <div className="p-4 sm:p-6 space-y-4">
              {/* Summary Info */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <p className="text-xs text-gray-500 mb-1">Document Number</p>
                  <p className="text-sm font-semibold text-gray-900">{sapResponseData.sap_document_number}</p>
                </div>
                <div>
                  <p className="text-xs text-gray-500 mb-1">Sent At</p>
                  <p className="text-sm font-semibold text-gray-900">
                    {sapResponseData.sent_at ? new Date(sapResponseData.sent_at).toLocaleString() : 'N/A'}
                  </p>
                </div>
              </div>

              {/* Message */}
              {sapResponseData.message && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                  <p className="text-sm text-green-800">{sapResponseData.message}</p>
                </div>
              )}

              {/* JSON Payload Section */}
              <div>
                <h4 className="text-sm font-semibold text-gray-900 mb-3">JSON Payload Sent to SAP</h4>
                <div className="bg-gray-50 border border-gray-200 rounded-lg overflow-hidden">
                  <div className="bg-gray-100 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
                    <span className="text-xs font-medium text-gray-600">Request Body</span>
                    <button
                      onClick={() => {
                        if (sapResponseData.sap_response) {
                          const payloadStr = typeof sapResponseData.sap_response === 'string' 
                            ? sapResponseData.sap_response 
                            : JSON.stringify(sapResponseData.sap_response, null, 2);
                          navigator.clipboard.writeText(payloadStr);
                          alert('Copied to clipboard!');
                        }
                      }}
                      className="text-gray-600 hover:text-gray-900 flex items-center gap-1 text-xs"
                      title="Copy to clipboard"
                    >
                      <Copy className="w-3 h-3" />
                      Copy
                    </button>
                  </div>
                  <pre className="p-4 text-xs overflow-x-auto text-gray-800 bg-gray-50" style={{ fontFamily: 'monospace', maxHeight: '300px' }}>
                    {sapResponseData.sap_response 
                      ? (typeof sapResponseData.sap_response === 'string' 
                          ? sapResponseData.sap_response 
                          : JSON.stringify(sapResponseData.sap_response, null, 2))
                      : 'No response data available'}
                  </pre>
                </div>
              </div>

              {/* Response Details if available */}
              {sapResponseData.sap_response && typeof sapResponseData.sap_response === 'object' && (
                <div>
                  <h4 className="text-sm font-semibold text-gray-900 mb-3">SAP Response Details</h4>
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 space-y-2">
                    {Object.entries(sapResponseData.sap_response as Record<string, any>).map(([key, value]) => (
                      <div key={key} className="flex justify-between items-start border-b border-gray-200 pb-2 last:border-b-0">
                        <span className="text-xs font-medium text-gray-600 capitalize">{key.replace(/_/g, ' ')}:</span>
                        <span className="text-xs text-gray-900 text-right break-words max-w-[60%]">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="sticky bottom-0 bg-white px-4 sm:px-6 py-3 sm:py-4 border-t border-gray-200 flex justify-end gap-3">
              <button
                onClick={() => {
                  setShowSapModal(false);
                  setSapResponseData(null);
                }}
                className="px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

