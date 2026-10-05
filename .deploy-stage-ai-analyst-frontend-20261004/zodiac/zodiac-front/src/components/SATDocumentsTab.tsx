'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { satApi } from '@/lib/api';
import { publicApiError } from '@/lib/apiErrors';
import {
  RefreshCw,
  FileText,
  Calendar,
  Building2,
  DollarSign,
  CheckCircle,
  XCircle,
  Eye,
  Upload,
  Trash2,
  AlertTriangle
} from 'lucide-react';
import { format } from 'date-fns';

interface SATDocument {
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
  total: string;
  moneda: string;
  status: string;
  fiscal_year: number;
  fiscal_period: number;
  source: string;  // 'admin' or 'supplier'
  received_at: string;
}

export default function SATDocumentsTab() {
  const router = useRouter();
  const [documents, setDocuments] = useState<SATDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedDocumentForDelete, setSelectedDocumentForDelete] = useState<SATDocument | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Filters
  const [docTypeFilter, setDocTypeFilter] = useState<string>('');

  useEffect(() => {
    fetchDocuments();
  }, [docTypeFilter]);

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const response = await satApi.list(
        undefined,
        undefined,
        docTypeFilter || undefined,
        undefined
      );
      
      setDocuments(response.documents || []);
      setTotalCount(response.total || 0);
    } catch (err: any) {
      console.error('Error fetching documents:', err);
      setError(publicApiError(err, 'Could not load SAT documents. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  const formatCurrency = (amount: string, currency: string = 'MXN') => {
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
      INVOICE: 'bg-green-100 text-green-800',
      PAYMENT: 'bg-blue-100 text-blue-800',
      CREDIT_NOTE: 'bg-orange-100 text-orange-800',
    };
    return styles[docType as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  const getStatusLabel = (status: string) => {
    const labels: Record<string, string> = {
      RECEIVED: 'Received',
      VALIDATED: 'Validated',
      MERGED: 'Merged',
      SAP_SENT: 'Sent to SAP',
    };
    return labels[status] || status;
  };

  const getStatusBadge = (status: string) => {
    const styles = {
      RECEIVED: 'bg-gray-100 text-gray-800',
      VALIDATED: 'bg-blue-100 text-blue-800',
      MERGED: 'bg-purple-100 text-purple-800',
      SAP_SENT: 'bg-green-100 text-green-800',
    };
    return styles[status as keyof typeof styles] || 'bg-gray-100 text-gray-800';
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    
    try {
      setUploading(true);
      setError(null);
      setUploadSuccess(null);
      
      const result = await satApi.uploadFiles(files);
      setUploadSuccess(`✅ Successfully uploaded ${result.successful_count} of ${result.total_files} file(s)!`);
      await fetchDocuments(); // Refresh the list
      
      // Clear file input
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
      
      // Clear success message after 5 seconds
      setTimeout(() => setUploadSuccess(null), 5000);
    } catch (err: any) {
      setError(publicApiError(err, 'Failed to upload files'));
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteClick = (doc: SATDocument) => {
    setSelectedDocumentForDelete(doc);
    setShowDeleteModal(true);
    setDeleteError(null);
  };

  const handleConfirmDelete = async () => {
    if (!selectedDocumentForDelete) return;
    
    try {
      setDeleting(true);
      setDeleteError(null);
      
      await satApi.deleteDocument(selectedDocumentForDelete.id);
      
      // Remove from list and refresh
      setDocuments(documents.filter(doc => doc.id !== selectedDocumentForDelete.id));
      setTotalCount(totalCount - 1);
      setShowDeleteModal(false);
      setSelectedDocumentForDelete(null);
      
      // Show success message
      setUploadSuccess(`✅ Document deleted successfully!`);
      setTimeout(() => setUploadSuccess(null), 3000);
    } catch (err: any) {
      setDeleteError(publicApiError(err, 'Failed to delete document'));
    } finally {
      setDeleting(false);
    }
  };

  const handleCloseDeleteModal = () => {
    if (!deleting) {
      setShowDeleteModal(false);
      setSelectedDocumentForDelete(null);
      setDeleteError(null);
    }
  };

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-gray-900">Filters</h2>
          <button
            onClick={fetchDocuments}
            className="p-2 text-gray-600 hover:text-gray-900 hover:bg-gray-100 rounded-lg transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-5 h-5" />
          </button>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Document Type
            </label>
            <select
              value={docTypeFilter}
              onChange={(e) => setDocTypeFilter(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              <option value="">All Types</option>
              <option value="INVOICE">Invoice</option>
              <option value="PAYMENT">Payment</option>
              <option value="CREDIT_NOTE">Credit Note</option>
            </select>
          </div>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
          <button
            type="button"
            onClick={fetchDocuments}
            className="mt-3 px-3 py-1.5 text-sm rounded-md bg-red-700 text-white hover:bg-red-800"
          >
            Retry
          </button>
        </div>
      )}

      {/* Upload Success Message */}
      {uploadSuccess && (
        <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
          <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
          <p className="text-green-800">{uploadSuccess}</p>
        </div>
      )}

      {/* Documents List */}
      <div className="bg-white rounded-lg shadow">
        <div className="p-6 border-b border-gray-200">
          <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
            <div>
              <h2 className="text-xl font-semibold text-gray-900">
                SAT Documents ({totalCount})
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                Individual CFDI documents from suppliers and admin uploads
              </p>
            </div>
            
            {/* Upload Buttons */}
            <div className="flex gap-2">
              {/* Bulk Upload Button - Primary Action */}
              <button
                onClick={() => router.push('/sat-documents/upload')}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2 font-medium"
              >
                <Upload className="w-4 h-4" />
                <span className="hidden sm:inline">Bulk Upload</span>
                <span className="sm:hidden">Upload</span>
              </button>
              
              {/* Quick Upload Button - Secondary Action */}
              <label className="cursor-pointer flex-shrink-0">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xml"
                  multiple
                  onChange={handleFileUpload}
                  disabled={uploading}
                  className="hidden"
                />
                <div className={`px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors flex items-center gap-2 ${uploading ? 'opacity-50 cursor-not-allowed' : ''}`}>
                  {uploading ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span className="hidden sm:inline">Uploading...</span>
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4" />
                      <span className="hidden sm:inline">Quick Upload</span>
                    </>
                  )}
                </div>
              </label>
            </div>
          </div>
        </div>

        {loading ? (
          <div className="p-12 text-center" aria-live="polite" aria-busy="true">
            <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading documents...</p>
          </div>
        ) : documents.length === 0 ? (
          <div className="p-12 text-center">
            <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">No SAT documents yet</h3>
            <p className="text-gray-600 max-w-md mx-auto">
              This list is empty because no CFDI files have been uploaded for this account. That is expected for a new workspace.
            </p>
            <p className="text-sm text-gray-500 mt-2">
              Upload XML invoices to start intake, then merge and send to SAP from the tabs above.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="bg-gray-50 border-b border-gray-200">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Document Info
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Supplier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Invoice Date
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Received At
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Type
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.serie || 'N/A'}-{doc.folio || 'N/A'}
                          </div>
                          <div className="text-xs text-gray-500 font-mono">
                            {doc.cfdi_uuid.substring(0, 8)}...
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-2">
                        <Building2 className="w-4 h-4 text-gray-400" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.supplier_rfc}
                          </div>
                          <div className="text-xs text-gray-500">
                            {doc.supplier_name || 'N/A'}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-900">
                      <div className="flex items-center gap-1">
                        <Calendar className="w-4 h-4 text-gray-400" />
                        {doc.fecha ? format(new Date(doc.fecha), 'yyyy-MM-dd') : 'N/A'}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-gray-600">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-xs">
                          {doc.received_at ? format(new Date(doc.received_at), 'yyyy-MM-dd') : 'N/A'}
                        </span>
                        <span className="text-xs text-gray-500">
                          {doc.received_at ? format(new Date(doc.received_at), 'HH:mm:ss') : ''}
                        </span>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-right font-medium text-gray-900">
                      {formatCurrency(doc.total, doc.moneda)}
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getDocTypeBadge(doc.doc_type)}`}>
                        {doc.doc_type}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${getStatusBadge(doc.status)}`}>
                        {getStatusLabel(doc.status)}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      {doc.source === 'supplier' ? (
                        <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded-full text-xs font-medium flex items-center gap-1 w-fit">
                          <Building2 className="w-3 h-3" />
                          Supplier
                        </span>
                      ) : (
                        <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded-full text-xs font-medium flex items-center gap-1 w-fit">
                          <FileText className="w-3 h-3" />
                          Admin
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => router.push(`/sat-documents/${doc.id}`)}
                          className="inline-flex items-center gap-1 px-3 py-1 text-sm text-blue-600 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors"
                        >
                          <Eye className="w-4 h-4" />
                          <span className="hidden sm:inline">Details</span>
                        </button>
                        <button
                          onClick={() => handleDeleteClick(doc)}
                          className="inline-flex items-center gap-1 px-3 py-1 text-sm text-red-600 hover:text-red-700 hover:bg-red-50 rounded-lg transition-colors"
                          title="Delete document"
                        >
                          <Trash2 className="w-4 h-4" />
                          <span className="hidden sm:inline">Delete</span>
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteModal && selectedDocumentForDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-3 sm:p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
            <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2 sm:space-x-3">
                  <div className="flex-shrink-0">
                    <AlertTriangle className="h-5 w-5 sm:h-6 sm:w-6 text-red-600" />
                  </div>
                  <h3 className="text-base sm:text-lg font-medium text-gray-900">Delete Document</h3>
                </div>
                <button
                  onClick={handleCloseDeleteModal}
                  disabled={deleting}
                  className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
                >
                  <XCircle className="h-5 w-5 sm:h-6 sm:w-6" />
                </button>
              </div>
            </div>

            <div className="px-4 sm:px-6 py-3 sm:py-4">
              <div className="mb-4">
                <p className="text-sm text-gray-600 mb-3">
                  Are you sure you want to delete this document? This action cannot be undone.
                </p>
                
                <div className="bg-gray-50 rounded-lg p-3">
                  <div className="flex items-center space-x-2 mb-2">
                    <FileText className="h-4 w-4 text-gray-500" />
                    <span className="font-medium text-gray-900">
                      {selectedDocumentForDelete.serie}-{selectedDocumentForDelete.folio}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 space-y-1">
                    <div>Supplier: <span className="font-medium">{selectedDocumentForDelete.supplier_rfc}</span></div>
                    <div>Amount: <span className="font-medium">{formatCurrency(selectedDocumentForDelete.total, selectedDocumentForDelete.moneda)}</span></div>
                    <div>Type: <span className="font-medium">{selectedDocumentForDelete.doc_type}</span></div>
                  </div>
                </div>
              </div>

              {deleteError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
                  <p className="text-sm text-red-700">{deleteError}</p>
                </div>
              )}

              <div className="text-xs text-gray-500 space-y-1">
                <p>⚠️ This document will be permanently deleted</p>
                <p>• All associated data will be removed</p>
              </div>
            </div>

            <div className="px-4 sm:px-6 py-3 sm:py-4 border-t border-gray-200">
              <div className="flex flex-col-reverse sm:flex-row items-center justify-end space-y-reverse space-y-2 sm:space-y-0 sm:space-x-3 gap-2 sm:gap-0">
                <button
                  onClick={handleCloseDeleteModal}
                  disabled={deleting}
                  className={`w-full sm:w-auto px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                    deleting 
                      ? "bg-gray-100 text-gray-400 cursor-not-allowed" 
                      : "bg-gray-100 text-gray-700 hover:bg-gray-200"
                  }`}
                >
                  Cancel
                </button>
                <button
                  onClick={handleConfirmDelete}
                  disabled={deleting}
                  className={`w-full sm:w-auto flex items-center justify-center space-x-2 px-4 py-2 text-sm font-medium rounded-md transition-colors ${
                    deleting
                      ? "bg-red-300 text-red-100 cursor-not-allowed"
                      : "bg-red-600 text-white hover:bg-red-700"
                  }`}
                >
                  {deleting ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-2 border-red-100 border-t-red-300"></div>
                      <span>Deleting...</span>
                    </>
                  ) : (
                    <>
                      <Trash2 className="h-4 w-4" />
                      <span>Delete</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
