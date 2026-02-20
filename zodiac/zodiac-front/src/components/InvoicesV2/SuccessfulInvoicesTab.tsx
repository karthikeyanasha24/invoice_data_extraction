'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { Eye, Edit, CheckCircle, FileType } from 'lucide-react';
import LoadingSpinner from '@/components/LoadingSpinner';
import InvoiceDetailsModal from '@/components/InvoicesV2/InvoiceDetailsModal';
import SuccessfulInvoiceEditModal from '@/components/InvoicesV2/SuccessfulInvoiceEditModal';

interface ValidatedInvoice {
  id: number;
  document_id: number;
  status: 'success' | 'failed';
  is_converted?: boolean;
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

export default function SuccessfulInvoicesTab() {
  const { handleAuthError } = useAuth();
  const [successful, setSuccessful] = useState<ValidatedInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedInvoice, setSelectedInvoice] = useState<ValidatedInvoice | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  const fetchSuccessful = useCallback(async () => {
    try {
      setLoading(true);
      // Include all successful invoices (converted and not converted)
      const response = await invoicesV2Api.getValidated('success', false);
      setSuccessful(response.validated_invoices);
    } catch (error: any) {
      console.error('Failed to fetch successful invoices:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [handleAuthError]);

  useEffect(() => {
    fetchSuccessful();
  }, [fetchSuccessful]);

  const handleViewDetails = (invoice: ValidatedInvoice) => {
    setSelectedInvoice(invoice);
    setShowDetailsModal(true);
  };

  const handleEdit = (invoice: ValidatedInvoice) => {
    setSelectedInvoice(invoice);
    setShowEditModal(true);
  };

  const handleEditSuccess = async () => {
    setShowEditModal(false);
    setSelectedInvoice(null);
    await fetchSuccessful();
  };

  if (loading) {
    return <LoadingSpinner text="Loading successful invoices..." />;
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between bg-green-50 border border-green-200 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <CheckCircle className="h-5 w-5 text-green-600" />
          <div>
            <h3 className="text-sm font-medium text-green-900">Successful Invoices</h3>
            <p className="text-sm text-green-700">
              All invoices that passed validation. Use the Convert tab to convert those not yet converted.
            </p>
          </div>
        </div>
      </div>

      {/* Successful Invoices Table */}
      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {successful.length === 0 ? (
          <div className="text-center py-12">
            <CheckCircle className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No successful invoices</h3>
            <p className="mt-1 text-sm text-gray-500">
              No invoices have been validated successfully yet
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
                    Converted
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
                {successful.map((invoice) => (
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
                    <td className="px-6 py-4 whitespace-nowrap">
                      {invoice.is_converted ? (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-800">
                          <FileType className="h-3 w-3 mr-1" />
                          Converted
                        </span>
                      ) : (
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-700">
                          Not converted
                        </span>
                      )}
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
                        title="Edit Invoice"
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
        <SuccessfulInvoiceEditModal
          invoice={selectedInvoice}
          onClose={() => {
            setShowEditModal(false);
            setSelectedInvoice(null);
          }}
          onSuccess={handleEditSuccess}
        />
      )}
    </div>
  );
}
