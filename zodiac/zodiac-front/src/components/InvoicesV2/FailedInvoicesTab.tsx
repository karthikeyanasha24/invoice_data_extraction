'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { Eye, Edit, XCircle, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import InvoiceDetailsModal from '@/components/InvoicesV2/InvoiceDetailsModal';
import ManualEditModal from '@/components/InvoicesV2/ManualEditModal';

interface ValidatedInvoice {
  id: number;
  document_id: number;
  status: 'success' | 'failed';
  invoice_data: {
    invoice_number?: string;
    customer_name?: string;
    supplier_name?: string;
    total?: string;
    currency?: string;
    [key: string]: any;
  };
  missing_fields?: string[];
  validation_errors?: any[];
  validated_at: string;
  document?: any;
}

export default function FailedInvoicesTab() {
  const { handleAuthError } = useAuth();
  const [failed, setFailed] = useState<ValidatedInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedInvoice, setSelectedInvoice] = useState<ValidatedInvoice | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  const fetchFailed = useCallback(async () => {
    try {
      setLoading(true);
      const response = await invoicesV2Api.getValidated('failed');
      setFailed(response.validated_invoices);
    } catch (error: any) {
      console.error('Failed to fetch failed invoices:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [handleAuthError]);

  useEffect(() => {
    fetchFailed();
  }, [fetchFailed]);

  const handleViewDetails = (invoice: ValidatedInvoice) => {
    setSelectedInvoice(invoice);
    setShowDetailsModal(true);
  };

  const handleEdit = (invoice: ValidatedInvoice) => {
    setSelectedInvoice(invoice);
    setShowEditModal(true);
  };

  const handleEditSuccess = () => {
    setShowEditModal(false);
    setSelectedInvoice(null);
    fetchFailed();
  };

  if (loading) {
    return <LoadingSpinner text="Loading failed invoices..." />;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg p-4">
        <AlertTriangle className="h-5 w-5 text-red-600" />
        <div>
          <h3 className="text-sm font-medium text-red-900">Failed Invoices</h3>
          <p className="text-sm text-red-700">
            These invoices have missing fields or validation errors. Edit them to fix and reprocess.
          </p>
        </div>
      </div>

      {/* Failed Invoices Table */}
      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {failed.length === 0 ? (
          <div className="text-center py-12">
            <XCircle className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No failed invoices</h3>
            <p className="mt-1 text-sm text-gray-500">
              All validated invoices have been processed successfully
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Invoice #
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Customer
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Supplier
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Total
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Missing Fields
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Validated
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {failed.map((invoice) => (
                  <tr key={invoice.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                      {invoice.invoice_data.invoice_number || 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {invoice.invoice_data.customer_name || 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {invoice.invoice_data.supplier_name || 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {invoice.invoice_data.total
                        ? `${invoice.invoice_data.currency || ''} ${invoice.invoice_data.total}`
                        : 'N/A'}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-red-600">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                        {invoice.missing_fields?.length || 0} missing
                      </span>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(invoice.validated_at).toLocaleString()}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium space-x-3">
                      <button
                        onClick={() => handleViewDetails(invoice)}
                        className="text-blue-600 hover:text-blue-900 transition-colors inline-flex items-center"
                        title="View Details"
                      >
                        <Eye className="h-4 w-4" />
                      </button>
                      <button
                        onClick={() => handleEdit(invoice)}
                        className="text-green-600 hover:text-green-900 transition-colors inline-flex items-center"
                        title="Edit and Reprocess"
                      >
                        <Edit className="h-4 w-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Modals */}
      {showDetailsModal && selectedInvoice && (
        <InvoiceDetailsModal
          invoice={selectedInvoice}
          onClose={() => {
            setShowDetailsModal(false);
            setSelectedInvoice(null);
          }}
        />
      )}

      {showEditModal && selectedInvoice && (
        <ManualEditModal
          invoice={selectedInvoice}
          onClose={() => {
            setShowEditModal(false);
            setSelectedInvoice(null);
          }}
          onSuccess={handleEditSuccess}
          enableReprocess={true}
        />
      )}
    </div>
  );
}
