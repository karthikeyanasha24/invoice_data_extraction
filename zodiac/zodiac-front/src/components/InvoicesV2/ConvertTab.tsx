'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api, convertedInvoicesApi } from '@/lib/api';
import { RefreshCw, Loader, CheckCircle, FileType } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import ValidationMismatchModal from '@/components/InvoicesV2/ValidationMismatchModal';

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
    customer_id?: string;
    [key: string]: any;
  };
  validated_at: string;
  document?: any;
}

interface ConvertTabProps {
  customerUserMode?: boolean;
}

export default function ConvertTab({ customerUserMode }: ConvertTabProps = {}) {
  const { handleAuthError } = useAuth();
  const [invoices, setInvoices] = useState<ValidatedInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedInvoices, setSelectedInvoices] = useState<Set<number>>(new Set());
  const [converting, setConverting] = useState(false);
  const [conversionProgress, setConversionProgress] = useState<string[]>([]);
  const [showConversionModal, setShowConversionModal] = useState(false);
  const [showMismatchModal, setShowMismatchModal] = useState(false);
  const [currentMismatch, setCurrentMismatch] = useState<{
    validatedId: number;
    invoiceNumber: string;
    customerId: string;
    mismatches: Record<string, { expected: string; actual: string }>;
  } | null>(null);
  const [pendingConversions, setPendingConversions] = useState<number[]>([]);

  const fetchInvoices = useCallback(async () => {
    try {
      setLoading(true);
      const response = customerUserMode
        ? await invoicesV2Api.getValidatedForCustomerUser({ status_filter: 'success' })
        : await invoicesV2Api.getValidated('success', true);
      setInvoices(response.validated_invoices || []);
    } catch (error: any) {
      console.error('Failed to fetch invoices to convert:', error);
      if (error.message?.includes('Session expired')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
    }
  }, [handleAuthError, customerUserMode]);

  useEffect(() => {
    fetchInvoices();
  }, [fetchInvoices]);

  const toggleSelectInvoice = (invoiceId: number) => {
    setSelectedInvoices(prev => {
      const newSet = new Set(prev);
      if (newSet.has(invoiceId)) {
        newSet.delete(invoiceId);
      } else {
        newSet.add(invoiceId);
      }
      return newSet;
    });
  };

  const toggleSelectAll = () => {
    if (selectedInvoices.size === invoices.length) {
      setSelectedInvoices(new Set());
    } else {
      setSelectedInvoices(new Set(invoices.map(inv => inv.id)));
    }
  };

  const processNextMismatch = useCallback(() => {
    if (pendingConversions.length > 0) {
      setConversionProgress(prev => [...prev, 'Skipping remaining mismatched invoices...']);
      setPendingConversions([]);
    } else {
      setConversionProgress(prev => [...prev, 'All conversions completed!']);
    }
    setCurrentMismatch(null);
  }, [pendingConversions.length]);

  const handleConvert = async () => {
    if (selectedInvoices.size === 0) {
      alert('Please select at least one invoice to convert');
      return;
    }

    setConverting(true);
    setShowConversionModal(true);
    setConversionProgress([]);
    setPendingConversions(Array.from(selectedInvoices));

    try {
      const selectedIds = Array.from(selectedInvoices);
      setConversionProgress(prev => [...prev, `Starting batch conversion for ${selectedIds.length} invoice(s)...`, '']);

      const response = await convertedInvoicesApi.convertInvoices(selectedIds);

      response.results.forEach((result: any) => {
        const invoice = invoices.find(inv => inv.id === result.validated_invoice_id);
        const invoiceNum = invoice?.invoice_data.invoice_number || result.validated_invoice_id;

        setConversionProgress(prev => [
          ...prev,
          `Invoice #${invoiceNum} (ID: ${result.validated_invoice_id}):`,
          ''
        ]);

        if (result.steps && Array.isArray(result.steps)) {
          result.steps.forEach((step: string) => {
            setConversionProgress(prev => [...prev, step]);
          });
        }

        if (result.status === 'failed') {
          setConversionProgress(prev => [...prev, `Final Status: FAILED - ${result.error_message || 'Unknown error'}`, '']);
        } else if (result.status === 'validation_mismatch') {
          setConversionProgress(prev => [...prev, 'Final Status: VALIDATION MISMATCH', '']);
        }
      });

      setConversionProgress(prev => [
        ...prev,
        'BATCH SUMMARY:',
        `   Successful: ${response.successful}`,
        `   Failed: ${response.failed}`,
        `   Validation Mismatches: ${response.validation_mismatches}`,
        ''
      ]);

      const mismatchResults = response.results.filter((r: any) => r.status === 'validation_mismatch');

      if (mismatchResults.length > 0) {
        const firstMismatch = mismatchResults[0];
        const invoice = invoices.find(inv => inv.id === firstMismatch.validated_invoice_id);

        if (invoice) {
          setCurrentMismatch({
            validatedId: firstMismatch.validated_invoice_id,
            invoiceNumber: invoice.invoice_data.invoice_number || 'Unknown',
            customerId: invoice.invoice_data.customer_id || 'Unknown',
            mismatches: firstMismatch.validation_mismatches || {}
          });
          setShowMismatchModal(true);
          setPendingConversions(mismatchResults.map((r: any) => r.validated_invoice_id).slice(1));
        }
      } else {
        setPendingConversions([]);
        setConversionProgress(prev => [...prev, 'All conversions completed!']);
      }

      setSelectedInvoices(new Set());
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `Batch Error: ${error.message}`]);
    } finally {
      setConverting(false);
    }
  };

  const handleMismatchUpdateCustomer = async () => {
    if (!currentMismatch) return;
    try {
      setConversionProgress(prev => [...prev, `Updating customer and converting invoice ${currentMismatch.invoiceNumber}...`]);
      await convertedInvoicesApi.overrideValidation(currentMismatch.validatedId, true);
      setConversionProgress(prev => [...prev, `Invoice ${currentMismatch.invoiceNumber} converted successfully`]);
      setShowMismatchModal(false);
      processNextMismatch();
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `Failed to convert: ${error.message}`]);
    }
  };

  const handleMismatchConvertAnyway = async () => {
    if (!currentMismatch) return;
    try {
      setConversionProgress(prev => [...prev, `Converting invoice ${currentMismatch.invoiceNumber} (bypassing validation)...`]);
      await convertedInvoicesApi.overrideValidation(currentMismatch.validatedId, false);
      setConversionProgress(prev => [...prev, `Invoice ${currentMismatch.invoiceNumber} converted successfully`]);
      setShowMismatchModal(false);
      processNextMismatch();
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `Failed to convert: ${error.message}`]);
    }
  };

  const handleMismatchSkip = () => {
    if (currentMismatch) {
      setConversionProgress(prev => [...prev, `Skipped invoice ${currentMismatch.invoiceNumber}`]);
    }
    setShowMismatchModal(false);
    processNextMismatch();
  };

  if (loading) {
    return <LoadingSpinner text="Loading invoices to convert..." />;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between bg-purple-50 border border-purple-200 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <FileType className="h-5 w-5 text-purple-600" />
          <div>
            <h3 className="text-sm font-medium text-purple-900">Convert</h3>
            <p className="text-sm text-purple-700">
              Select successful invoices not yet converted and convert them to customer-specific formats
            </p>
          </div>
        </div>
        {invoices.length > 0 && (
          <button
            onClick={handleConvert}
            disabled={selectedInvoices.size === 0 || converting}
            className={cn(
              'flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed',
              converting && 'opacity-75'
            )}
          >
            <RefreshCw className={cn('h-4 w-4', converting && 'animate-spin')} />
            Convert Selected ({selectedInvoices.size})
          </button>
        )}
      </div>

      <div className="bg-white shadow-sm rounded-lg border border-gray-200 overflow-hidden">
        {invoices.length === 0 ? (
          <div className="text-center py-12">
            <FileType className="mx-auto h-12 w-12 text-gray-400" />
            <h3 className="mt-2 text-sm font-medium text-gray-900">No invoices to convert</h3>
            <p className="mt-1 text-sm text-gray-500">
              All successful invoices have been converted, or none have passed validation yet
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={selectedInvoices.size === invoices.length && invoices.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 text-purple-600 rounded focus:ring-2 focus:ring-purple-500"
                    />
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Invoice #</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Supplier</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Total</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Validated</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {invoices.map((invoice) => (
                  <tr key={invoice.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={selectedInvoices.has(invoice.id)}
                        onChange={() => toggleSelectInvoice(invoice.id)}
                        className="w-4 h-4 text-purple-600 rounded focus:ring-2 focus:ring-purple-500"
                      />
                    </td>
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
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {new Date(invoice.validated_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showConversionModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 bg-purple-50">
              <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                {converting ? (
                  <>
                    <Loader className="w-5 h-5 animate-spin text-purple-600" />
                    Converting Invoices...
                  </>
                ) : (
                  <>
                    <CheckCircle className="w-5 h-5 text-green-600" />
                    Conversion Complete
                  </>
                )}
              </h2>
              <p className="text-sm text-gray-600 mt-1">
                {converting ? 'Processing your invoices...' : 'View detailed conversion results below'}
              </p>
            </div>
            <div className="flex-1 overflow-y-auto px-6 py-4 bg-gray-50">
              <div className="space-y-0 font-mono text-xs bg-white border border-gray-200 rounded-lg p-4">
                {conversionProgress.map((msg, idx) => (
                  <div key={idx} className="text-gray-700 leading-relaxed">
                    {msg || '\u00A0'}
                  </div>
                ))}
                {converting && (
                  <div className="flex items-center gap-2 text-purple-600 mt-4 pt-4 border-t border-gray-200">
                    <Loader className="w-4 h-4 animate-spin" />
                    <span className="font-medium">Processing...</span>
                  </div>
                )}
              </div>
            </div>
            <div className="px-6 py-4 border-t border-gray-200 flex justify-end bg-gray-50">
              <button
                onClick={() => {
                  setShowConversionModal(false);
                  fetchInvoices();
                }}
                disabled={converting}
                className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {converting ? 'Please wait...' : 'Close'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showMismatchModal && currentMismatch && (
        <ValidationMismatchModal
          isOpen={showMismatchModal}
          invoiceNumber={currentMismatch.invoiceNumber}
          customerId={currentMismatch.customerId}
          mismatches={currentMismatch.mismatches}
          onUpdateCustomer={handleMismatchUpdateCustomer}
          onConvertAnyway={handleMismatchConvertAnyway}
          onSkip={handleMismatchSkip}
          onClose={() => {
            setShowMismatchModal(false);
            setCurrentMismatch(null);
          }}
        />
      )}
    </div>
  );
}
