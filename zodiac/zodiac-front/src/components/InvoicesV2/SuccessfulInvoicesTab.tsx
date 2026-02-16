'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api, convertedInvoicesApi } from '@/lib/api';
import { Eye, Edit, CheckCircle, RefreshCw, Loader, AlertTriangle } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import InvoiceDetailsModal from '@/components/InvoicesV2/InvoiceDetailsModal';
import SuccessfulInvoiceEditModal from '@/components/InvoicesV2/SuccessfulInvoiceEditModal';
import ValidationMismatchModal from '@/components/InvoicesV2/ValidationMismatchModal';

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

export default function SuccessfulInvoicesTab() {
  const { handleAuthError } = useAuth();
  const [successful, setSuccessful] = useState<ValidatedInvoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedInvoice, setSelectedInvoice] = useState<ValidatedInvoice | null>(null);
  const [showDetailsModal, setShowDetailsModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  
  // Conversion states
  const [selectedInvoices, setSelectedInvoices] = useState<Set<number>>(new Set());
  const [converting, setConverting] = useState(false);
  const [conversionProgress, setConversionProgress] = useState<string[]>([]);
  const [showConversionModal, setShowConversionModal] = useState(false);
  
  // Validation mismatch states
  const [showMismatchModal, setShowMismatchModal] = useState(false);
  const [currentMismatch, setCurrentMismatch] = useState<{
    validatedId: number;
    invoiceNumber: string;
    customerId: string;
    mismatches: Record<string, { expected: string; actual: string }>;
  } | null>(null);
  const [pendingConversions, setPendingConversions] = useState<number[]>([]);

  const fetchSuccessful = useCallback(async () => {
    try {
      setLoading(true);
      // Exclude already converted invoices from the list
      const response = await invoicesV2Api.getValidated('success', true);
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
    const previousInvoiceId = selectedInvoice?.id;
    setSelectedInvoice(null);
    
    // Refresh the list
    await fetchSuccessful();
    
    // If the user had an invoice selected, update it with fresh data
    if (previousInvoiceId) {
      // Wait a bit for state to update
      setTimeout(() => {
        const updatedInvoice = successful.find(inv => inv.id === previousInvoiceId);
        if (updatedInvoice) {
          console.log('✅ Refreshed invoice data after edit');
        }
      }, 100);
    }
  };

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
    if (selectedInvoices.size === successful.length) {
      setSelectedInvoices(new Set());
    } else {
      setSelectedInvoices(new Set(successful.map(inv => inv.id)));
    }
  };

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
      setConversionProgress(prev => [...prev, `🔄 Starting batch conversion for ${selectedIds.length} invoice(s)...`, '']);

      const response = await convertedInvoicesApi.convertInvoices(selectedIds);
      
      // Display detailed steps for each invoice
      response.results.forEach((result: any, index: number) => {
        const invoice = successful.find(inv => inv.id === result.validated_invoice_id);
        const invoiceNum = invoice?.invoice_data.invoice_number || result.validated_invoice_id;
        
        setConversionProgress(prev => [
          ...prev,
          `\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
          `📋 Invoice #${invoiceNum} (ID: ${result.validated_invoice_id}):`,
          ''
        ]);
        
        // Add detailed steps if available
        if (result.steps && Array.isArray(result.steps)) {
          result.steps.forEach((step: string) => {
            setConversionProgress(prev => [...prev, step]);
          });
        }
        
        // Add final status
        if (result.status === 'success') {
          setConversionProgress(prev => [...prev, '']);
        } else if (result.status === 'failed') {
          setConversionProgress(prev => [...prev, `❌ Final Status: FAILED - ${result.error_message || 'Unknown error'}`, '']);
        } else if (result.status === 'validation_mismatch') {
          setConversionProgress(prev => [...prev, `⚠️ Final Status: VALIDATION MISMATCH`, '']);
        }
      });

      // Summary
      setConversionProgress(prev => [
        ...prev,
        `\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
        `📊 BATCH SUMMARY:`,
        `   ✅ Successful: ${response.successful}`,
        `   ❌ Failed: ${response.failed}`,
        `   ⚠️ Validation Mismatches: ${response.validation_mismatches}`,
        ''
      ]);

      // Handle validation mismatches
      const mismatchResults = response.results.filter((r: any) => r.status === 'validation_mismatch');
      
      if (mismatchResults.length > 0) {
        // Show first mismatch
        const firstMismatch = mismatchResults[0];
        const invoice = successful.find(inv => inv.id === firstMismatch.validated_invoice_id);
        
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
        setConversionProgress(prev => [...prev, '🎉 All conversions completed!']);
      }

      // Clear selection for successfully converted invoices
      setSelectedInvoices(new Set());
      
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `❌ Batch Error: ${error.message}`]);
    } finally {
      setConverting(false);
    }
  };

  const handleMismatchUpdateCustomer = async () => {
    if (!currentMismatch) return;

    try {
      setConversionProgress(prev => [...prev, `🔄 Updating customer and converting invoice ${currentMismatch.invoiceNumber}...`]);
      await convertedInvoicesApi.overrideValidation(currentMismatch.validatedId, true);
      setConversionProgress(prev => [...prev, `✅ Invoice ${currentMismatch.invoiceNumber} converted successfully`]);
      
      setShowMismatchModal(false);
      processNextMismatch();
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `❌ Failed to convert: ${error.message}`]);
    }
  };

  const handleMismatchConvertAnyway = async () => {
    if (!currentMismatch) return;

    try {
      setConversionProgress(prev => [...prev, `🔄 Converting invoice ${currentMismatch.invoiceNumber} (bypassing validation)...`]);
      await convertedInvoicesApi.overrideValidation(currentMismatch.validatedId, false);
      setConversionProgress(prev => [...prev, `✅ Invoice ${currentMismatch.invoiceNumber} converted successfully`]);
      
      setShowMismatchModal(false);
      processNextMismatch();
    } catch (error: any) {
      setConversionProgress(prev => [...prev, `❌ Failed to convert: ${error.message}`]);
    }
  };

  const handleMismatchSkip = () => {
    if (currentMismatch) {
      setConversionProgress(prev => [...prev, `⏭️ Skipped invoice ${currentMismatch.invoiceNumber}`]);
    }
    setShowMismatchModal(false);
    processNextMismatch();
  };

  const processNextMismatch = () => {
    if (pendingConversions.length > 0) {
      const nextId = pendingConversions[0];
      const invoice = successful.find(inv => inv.id === nextId);
      
      if (invoice) {
        // For now, just mark as skipped since we don't have the mismatch data
        // In real implementation, this would come from the batch results
        setConversionProgress(prev => [...prev, `⏭️ Skipping remaining mismatched invoices...`]);
      }
      setPendingConversions([]);
    } else {
      setConversionProgress(prev => [...prev, '✨ All conversions completed!']);
    }
    setCurrentMismatch(null);
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
              Select invoices and convert them to customer-specific formats
            </p>
          </div>
        </div>
        
        {successful.length > 0 && (
          <button
            onClick={handleConvert}
            disabled={selectedInvoices.size === 0 || converting}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <RefreshCw className={cn('h-4 w-4', converting && 'animate-spin')} />
            Convert Selected ({selectedInvoices.size})
          </button>
        )}
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
                  <th className="px-6 py-3 text-left">
                    <input
                      type="checkbox"
                      checked={selectedInvoices.size === successful.length && successful.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                    />
                  </th>
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
                    Status
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
                    <td className="px-6 py-4">
                      <input
                        type="checkbox"
                        checked={selectedInvoices.has(invoice.id)}
                        onChange={() => toggleSelectInvoice(invoice.id)}
                        className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
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
                    <td className="px-6 py-4 whitespace-nowrap">
                      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        <CheckCircle className="h-3 w-3 mr-1" />
                        Success
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

      {/* Conversion Progress Modal */}
      {showConversionModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
            <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-indigo-50">
              <h2 className="text-xl font-bold text-gray-900 flex items-center gap-2">
                {converting ? (
                  <>
                    <Loader className="w-5 h-5 animate-spin text-blue-600" />
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
                {conversionProgress.map((msg, idx) => {
                  // Style different types of messages
                  let className = 'text-gray-700 leading-relaxed';
                  
                  if (msg.startsWith('✅')) {
                    className = 'text-green-700 font-medium';
                  } else if (msg.startsWith('❌')) {
                    className = 'text-red-700 font-medium';
                  } else if (msg.startsWith('⚠️')) {
                    className = 'text-yellow-700 font-medium';
                  } else if (msg.startsWith('🔍') || msg.startsWith('🔄')) {
                    className = 'text-blue-700';
                  } else if (msg.startsWith('💾')) {
                    className = 'text-purple-700';
                  } else if (msg.startsWith('📋') || msg.startsWith('📊')) {
                    className = 'text-indigo-800 font-semibold text-sm';
                  } else if (msg.startsWith('━━━')) {
                    className = 'text-gray-400';
                  } else if (msg.startsWith('🎉')) {
                    className = 'text-green-700 font-bold text-sm';
                  } else if (msg.trim().startsWith('Step')) {
                    className = 'text-blue-800 font-medium';
                  } else if (msg.trim().startsWith('ℹ️')) {
                    className = 'text-gray-600 italic';
                  }
                  
                  return (
                    <div key={idx} className={className}>
                      {msg || '\u00A0'}
                    </div>
                  );
                })}
                {converting && (
                  <div className="flex items-center gap-2 text-blue-600 mt-4 pt-4 border-t border-gray-200">
                    <Loader className="w-4 h-4 animate-spin" />
                    <span className="font-medium">Processing...</span>
                  </div>
                )}
              </div>
            </div>
            
            <div className="px-6 py-4 border-t border-gray-200 flex justify-between items-center bg-gray-50">
              <div className="text-sm text-gray-600">
                {converting ? (
                  'Please wait while we process your invoices...'
                ) : (
                  'Conversion process completed. You can close this window.'
                )}
              </div>
              <button
                onClick={() => {
                  setShowConversionModal(false);
                  fetchSuccessful(); // Refresh the list
                }}
                disabled={converting}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              >
                {converting ? 'Please wait...' : 'Close'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Validation Mismatch Modal */}
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
