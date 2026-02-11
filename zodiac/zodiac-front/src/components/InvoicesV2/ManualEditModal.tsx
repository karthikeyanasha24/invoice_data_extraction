'use client';

import { useState, useEffect } from 'react';
import { X, Save, AlertCircle, Edit } from 'lucide-react';
import { invoicesV2Api } from '@/lib/api';

interface ValidatedInvoice {
  id: number;
  invoice_data: {
    customer_id?: string;
    customer_name?: string;
    [key: string]: any;
  };
  missing_fields?: string[];
}

interface Props {
  invoice: ValidatedInvoice;
  onClose: () => void;
  onSuccess: () => void;
  enableReprocess?: boolean;
}

export default function ManualEditModal({ invoice, onClose, onSuccess, enableReprocess = false }: Props) {
  const [editableFields, setEditableFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [reprocessing, setReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const missingFields = invoice.missing_fields || [];

  // Define which fields should be editable (exclude complex objects and arrays)
  const editableFieldNames = [
    'invoice_number',
    'issue_date',
    'due_date',
    'currency',
    'invoice_type_code',
    'customer_id',
    'customer_name',
    'customer_tax_id',
    'customer_legal_name',
    'supplier_id',
    'supplier_name',
    'supplier_tax_id',
    'supplier_legal_name',
    'subtotal',
    'tax_amount',
    'total',
    'line_extension_amount',
    'payable_amount'
  ];

  // Initialize with current values
  useEffect(() => {
    const initial: Record<string, string> = {};
    editableFieldNames.forEach(field => {
      const value = invoice.invoice_data[field];
      if (value !== undefined && value !== null && typeof value !== 'object') {
        initial[field] = String(value);
      } else {
        initial[field] = '';
      }
    });
    setEditableFields(initial);
  }, [invoice]);

  const handleChange = (field: string, value: string) => {
    setEditableFields(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const formatFieldName = (field: string) => {
    return field
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const getFieldPlaceholder = (field: string): string => {
    const placeholders: Record<string, string> = {
      supplier_id: 'e.g., 9429033821733',
      customer_id: 'e.g., 9429033591476',
      due_date: 'YYYY-MM-DD',
      issue_date: 'YYYY-MM-DD',
      currency: 'e.g., NZD',
      total: 'e.g., 1595.51',
      subtotal: 'e.g., 1387.40',
      tax_amount: 'e.g., 208.11',
    };
    return placeholders[field] || `Enter ${formatFieldName(field).toLowerCase()}`;
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);

      // Find fields that have been changed or filled (only send corrections)
      const corrections: Record<string, string> = {};
      const originalData = invoice.invoice_data;

      editableFieldNames.forEach(field => {
        const newValue = editableFields[field]?.trim();
        const oldValue = originalData[field] ? String(originalData[field]) : '';
        
        // Include if it's a missing field or if value changed
        if (missingFields.includes(field) || (newValue && newValue !== oldValue)) {
          if (newValue) {
            corrections[field] = newValue;
          }
        }
      });

      if (Object.keys(corrections).length === 0) {
        setError('No changes detected. Please modify at least one field.');
        setSaving(false);
        return;
      }

      // Call API to save corrections
      await invoicesV2Api.manualFix(invoice.id, corrections);

      // If reprocessing is enabled, trigger revalidation
      if (enableReprocess) {
        setSaving(false);
        setReprocessing(true);
        
        try {
          // Trigger reprocessing using the new reprocess endpoint
          await invoicesV2Api.reprocessInvoice(invoice.id);
          
          alert(`Successfully saved ${Object.keys(corrections).length} correction(s) and reprocessed the invoice! Check back in a moment for updated results.`);
          onSuccess();
        } catch (reprocessErr: any) {
          console.error('Failed to reprocess invoice:', reprocessErr);
          setError(`Corrections saved but reprocessing failed: ${reprocessErr.message || 'Unknown error'}`);
          setReprocessing(false);
        }
      } else {
        // Success without reprocessing
        alert(`Successfully saved ${Object.keys(corrections).length} correction(s)!`);
        onSuccess();
      }
    } catch (err: any) {
      console.error('Failed to save corrections:', err);
      setError(err.message || 'Failed to save corrections');
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
      {/* Overlay */}
      <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>

      {/* Modal */}
      <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div className="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-2xl">
          {/* Header */}
          <div className="bg-white px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900" id="modal-title">
                Edit Invoice Fields
              </h3>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500 transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="bg-white px-6 py-6">
            <div className="space-y-6">
              {/* Info Alert */}
              <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
                <div className="flex items-start">
                  <Edit className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-medium text-blue-800 mb-1">Edit Invoice Fields</h4>
                    <p className="text-sm text-blue-700">
                      You can edit any field below. Corrections for <strong>{invoice.invoice_data.customer_name || 'this customer'}</strong> will be saved
                      to the cache and automatically applied to future invoices with the same customer ID.
                      {enableReprocess && (
                        <span className="block mt-2 font-semibold">
                          ⚠️ After saving, the invoice will be automatically reprocessed to validate all fields.
                        </span>
                      )}
                    </p>
                  </div>
                </div>
              </div>

              {/* Error Message */}
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-md p-4">
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              {/* Missing Fields Alert */}
              {missingFields.length > 0 && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
                  <div className="flex items-start">
                    <AlertCircle className="h-5 w-5 text-yellow-600 mr-3 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-medium text-yellow-800 mb-1">Missing Fields</h4>
                      <p className="text-sm text-yellow-700">
                        {missingFields.map(formatFieldName).join(', ')}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Editable Fields - Organized by Section */}
              <div className="space-y-6">
                {/* Invoice Header Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Invoice Header
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['invoice_number', 'issue_date', 'due_date', 'currency', 'invoice_type_code']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Customer Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Customer Information
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['customer_id', 'customer_name', 'customer_tax_id', 'customer_legal_name']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Supplier Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Supplier Information
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['supplier_id', 'supplier_name', 'supplier_tax_id', 'supplier_legal_name']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Monetary Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Monetary Details
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['subtotal', 'tax_amount', 'total', 'line_extension_amount', 'payable_amount']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="bg-gray-50 px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              onClick={onClose}
              disabled={saving || reprocessing}
              className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || reprocessing}
              className="inline-flex items-center px-4 py-2 bg-blue-600 border border-transparent rounded-md text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Saving...
                </>
              ) : reprocessing ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Reprocessing...
                </>
              ) : (
                <>
                  <Save className="h-4 w-4 mr-2" />
                  {enableReprocess ? 'Save & Reprocess' : 'Save to Cache'}
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
