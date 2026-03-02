'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { FileText, Cloud, MousePointer } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';

interface InvoiceV2Document {
  id: number;
  tracking_id: string;
  filename: string;
  source: 'manual' | 'sap';
  validation_status: string;
  uploaded_at: string;
}

export default function CustomerInvoicesDocumentsTab() {
  const { handleAuthError } = useAuth();
  const [documents, setDocuments] = useState<InvoiceV2Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [total, setTotal] = useState(0);

  const fetchDocuments = useCallback(async () => {
    try {
      setLoading(true);
      const data = await invoicesV2Api.getDocumentsForCustomerUser({ skip: 0, limit: 200 });
      setDocuments(data.documents || []);
      setTotal(data.total ?? 0);
    } catch (error: any) {
      console.error('Failed to fetch documents:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [handleAuthError]);

  useEffect(() => {
    fetchDocuments();
  }, [fetchDocuments]);

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
      <p className="text-sm text-gray-600">
        Invoices assigned to your customer(s). Upload and receive are managed by your administrator.
      </p>
      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {documents.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No documents</h3>
            <p className="mt-1 text-sm text-gray-500">No invoices found for your assigned customers.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Filename
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Status
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Uploaded
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <FileText className="h-5 w-5 text-gray-400 mr-2 flex-shrink-0" />
                        <span className="text-sm font-medium text-gray-900 truncate max-w-[200px] sm:max-w-xs">
                          {doc.filename}
                        </span>
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center gap-2">
                        {getSourceIcon(doc.source)}
                        <span className="text-sm text-gray-900 capitalize">{doc.source}</span>
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap">
                      {getStatusBadge(doc.validation_status)}
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(doc.uploaded_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
