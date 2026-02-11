'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { Upload, Trash2, Download, Filter, Cloud, MousePointer, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import DeleteConfirmationModal from '@/components/DeleteConfirmationModal';

interface InvoiceV2Document {
  id: number;
  tracking_id: string;
  filename: string;
  source: 'manual' | 'sap';
  validation_status: 'not_validated' | 'processing' | 'validated';
  uploaded_at: string;
  deleted_at?: string | null;
}

export default function DocumentsTab() {
  const { handleAuthError } = useAuth();
  const [documents, setDocuments] = useState<InvoiceV2Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'manual' | 'sap'>('all');
  const [uploading, setUploading] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<InvoiceV2Document | null>(null);

  const fetchDocuments = useCallback(async () => {
    try {
      setLoading(true);
      const source = sourceFilter === 'all' ? undefined : sourceFilter;
      const response = await invoicesV2Api.getDocuments(source);
      setDocuments(response.data.documents);
    } catch (error: any) {
      console.error('Failed to fetch documents:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [sourceFilter, handleAuthError]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith('.xml')) {
      alert('Please upload an XML file');
      return;
    }

    try {
      setUploading(true);
      const formData = new FormData();
      formData.append('file', file);
      
      await invoicesV2Api.uploadManual(formData);
      
      // Reset input
      event.target.value = '';
      
      // Refresh list
      await fetchDocuments();
      
      alert('Invoice uploaded successfully!');
    } catch (error: any) {
      console.error('Upload failed:', error);
      alert(error.response?.data?.detail || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedDocument) return;

    try {
      await invoicesV2Api.deleteDocument(selectedDocument.id);
      setShowDeleteModal(false);
      setSelectedDocument(null);
      await fetchDocuments();
      alert('Document deleted successfully!');
    } catch (error: any) {
      console.error('Delete failed:', error);
      alert(error.response?.data?.detail || 'Delete failed');
    }
  };

  const handleDownload = async (doc: InvoiceV2Document) => {
    try {
      await invoicesV2Api.downloadDocument(doc.id, doc.filename);
    } catch (error: any) {
      console.error('Download failed:', error);
      alert(error.response?.data?.detail || 'Download failed');
    }
  };

  const getStatusBadge = (status: string) => {
    const badges: Record<string, { bg: string; text: string; label: string }> = {
      not_validated: { bg: 'bg-gray-100', text: 'text-gray-800', label: 'Not Validated' },
      processing: { bg: 'bg-blue-100', text: 'text-blue-800', label: 'Processing' },
      validated: { bg: 'bg-green-100', text: 'text-green-800', label: 'Validated' },
    };

    const badge = badges[status] || badges.not_validated;
    
    return (
      <span className={cn('px-2 py-1 text-xs font-medium rounded-full', badge.bg, badge.text)}>
        {badge.label}
      </span>
    );
  };

  const getSourceIcon = (source: string) => {
    return source === 'sap' ? (
      <Cloud className="h-4 w-4 text-blue-500" />
    ) : (
      <MousePointer className="h-4 w-4 text-gray-500" />
    );
  };

  if (loading) {
    return <LoadingSpinner text="Loading documents..." />;
  }

  return (
    <div className="space-y-4">
      {/* Header with filters and upload */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        {/* Source Filter */}
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-gray-500" />
          <select
            value={sourceFilter}
            onChange={(e) => setSourceFilter(e.target.value as any)}
            className="block w-full sm:w-auto rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
          >
            <option value="all">All Sources</option>
            <option value="manual">Manual Upload</option>
            <option value="sap">From SAP</option>
          </select>
        </div>

        {/* Upload Button */}
        <label
          htmlFor="file-upload"
          className={cn(
            'inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 cursor-pointer transition-colors',
            uploading && 'opacity-50 cursor-not-allowed'
          )}
        >
          <Upload className="h-4 w-4 mr-2" />
          {uploading ? 'Uploading...' : 'Upload Invoice'}
          <input
            id="file-upload"
            type="file"
            accept=".xml"
            className="hidden"
            onChange={handleFileUpload}
            disabled={uploading}
          />
        </label>
      </div>

      {/* Documents Table */}
      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {documents.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No documents</h3>
            <p className="mt-1 text-sm text-gray-500">
              {sourceFilter === 'all'
                ? 'Upload an invoice to get started'
                : `No ${sourceFilter} invoices found`}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Filename
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Uploaded
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <FileText className="h-5 w-5 text-gray-400 mr-2 flex-shrink-0" />
                        <div className="text-sm font-medium text-gray-900 truncate max-w-xs">
                          {doc.filename}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {getSourceIcon(doc.source)}
                        <span className="text-sm text-gray-900 capitalize">{doc.source}</span>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(doc.validation_status)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(doc.uploaded_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <div className="flex items-center justify-end gap-3">
                        <button
                          onClick={() => handleDownload(doc)}
                          className="text-blue-600 hover:text-blue-900 transition-colors inline-flex items-center"
                          title="Download XML"
                        >
                          <Download className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => {
                            setSelectedDocument(doc);
                            setShowDeleteModal(true);
                          }}
                          className="text-red-600 hover:text-red-900 transition-colors inline-flex items-center"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
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
      {showDeleteModal && selectedDocument && (
        <DeleteConfirmationModal
          invoice={{
            id: selectedDocument.id,
            filename: selectedDocument.filename,
            status: selectedDocument.validation_status,
            uploaded_at: selectedDocument.uploaded_at
          } as any}
          isOpen={showDeleteModal}
          onClose={() => {
            setShowDeleteModal(false);
            setSelectedDocument(null);
          }}
          onConfirm={handleDelete}
        />
      )}
    </div>
  );
}
