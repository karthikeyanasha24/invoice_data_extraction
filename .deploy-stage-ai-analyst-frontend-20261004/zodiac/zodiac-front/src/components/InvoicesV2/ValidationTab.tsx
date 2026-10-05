'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { CheckSquare, Square, Play, Loader2, FileText, Cloud, MousePointer } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';

interface InvoiceV2Document {
  id: number;
  tracking_id: string;
  filename: string;
  source: 'manual' | 'sap';
  uploaded_at: string;
}

interface ValidationTabProps {
  customerUserMode?: boolean;
}

export default function ValidationTab({ customerUserMode }: ValidationTabProps = {}) {
  const router = useRouter();
  const { handleAuthError } = useAuth();
  const [unvalidated, setUnvalidated] = useState<InvoiceV2Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [processing, setProcessing] = useState(false);

  const fetchUnvalidated = useCallback(async () => {
    try {
      setLoading(true);
      const response = customerUserMode
        ? await invoicesV2Api.getUnvalidatedForCustomerUser()
        : await invoicesV2Api.getUnvalidated();
      setUnvalidated(response.documents || []);
    } catch (error: any) {
      console.error('Failed to fetch unvalidated invoices:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [handleAuthError, customerUserMode]);

  useEffect(() => {
    fetchUnvalidated();
  }, [fetchUnvalidated]);

  const handleSelectAll = () => {
    if (selected.size === unvalidated.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(unvalidated.map(doc => doc.id)));
    }
  };

  const handleSelectOne = (id: number) => {
    const newSelected = new Set(selected);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelected(newSelected);
  };

  const handleProcess = async () => {
    if (selected.size === 0) return;

    try {
      setProcessing(true);

      const selectedIds = Array.from(selected);
      await invoicesV2Api.validateInvoices(selectedIds);

      // Redirect to processing page with document IDs (same for admin and customer user)
      const idsParam = selectedIds.join(',');
      router.push(`/invoices-v2/processing?ids=${idsParam}`);
    } catch (error: any) {
      console.error('Validation failed:', error);
      alert(error.message || 'Failed to start validation');
      setProcessing(false);
    }
  };

  const getSourceIcon = (source: string) => {
    return source === 'sap' ? (
      <Cloud className="h-4 w-4 text-blue-500" />
    ) : (
      <MousePointer className="h-4 w-4 text-gray-500" />
    );
  };

  if (loading) {
    return <LoadingSpinner text="Loading unvalidated invoices..." />;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div className="flex items-center gap-2">
          <div className="text-sm text-gray-600">
            {unvalidated.length} invoice{unvalidated.length !== 1 ? 's' : ''} awaiting validation
          </div>
          {selected.size > 0 && (
            <div className="text-sm font-medium text-blue-600">
              ({selected.size} selected)
            </div>
          )}
        </div>

        <button
          onClick={handleProcess}
          disabled={selected.size === 0 || processing}
          className={cn(
            'inline-flex items-center justify-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white transition-colors',
            selected.size === 0 || processing
              ? 'bg-gray-400 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500'
          )}
        >
          {processing ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              Processing...
            </>
          ) : (
            <>
              <Play className="h-4 w-4 mr-2" />
              Process Selected ({selected.size})
            </>
          )}
        </button>
      </div>

      {/* Invoices Table */}
      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {unvalidated.length === 0 ? (
          <div className="text-center py-12">
            <CheckSquare className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No unvalidated invoices</h3>
            <p className="mt-1 text-sm text-gray-500">
              All invoices have been validated or none have been uploaded yet
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left">
                    <button
                      onClick={handleSelectAll}
                      className="text-gray-500 hover:text-gray-700 transition-colors"
                      title={selected.size === unvalidated.length ? 'Deselect all' : 'Select all'}
                    >
                      {selected.size === unvalidated.length ? (
                        <CheckSquare className="h-5 w-5" />
                      ) : (
                        <Square className="h-5 w-5" />
                      )}
                    </button>
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Filename
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Source
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Uploaded
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {unvalidated.map((doc) => (
                  <tr
                    key={doc.id}
                    className={cn(
                      'hover:bg-gray-50 transition-colors cursor-pointer',
                      selected.has(doc.id) && 'bg-blue-50'
                    )}
                    onClick={() => handleSelectOne(doc.id)}
                  >
                    <td className="px-6 py-4 whitespace-nowrap">
                      {selected.has(doc.id) ? (
                        <CheckSquare className="h-5 w-5 text-blue-600" />
                      ) : (
                        <Square className="h-5 w-5 text-gray-400" />
                      )}
                    </td>
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
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
