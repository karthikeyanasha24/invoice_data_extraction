'use client';

import { X, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

interface ValidatedInvoice {
  id: number;
  status: 'success' | 'failed';
  invoice_data: {
    [key: string]: any;
  };
  missing_fields?: string[];
  validation_errors?: Array<{ field: string; message: string }>;
  validation_notes?: string;
}

interface Props {
  invoice: ValidatedInvoice;
  onClose: () => void;
}

export default function InvoiceDetailsModal({ invoice, onClose }: Props) {
  const formatFieldName = (field: string) => {
    return field
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const renderFieldValue = (key: string, value: any): string => {
    if (value === null || value === undefined) return 'N/A';
    if (typeof value === 'object') return JSON.stringify(value, null, 2);
    return String(value);
  };

  // Group fields by category
  const headerFields = ['invoice_number', 'issue_date', 'due_date', 'currency', 'invoice_type_code'];
  const customerFields = ['customer_id', 'customer_name', 'customer_tax_id', 'customer_legal_name'];
  const supplierFields = ['supplier_id', 'supplier_name', 'supplier_tax_id', 'supplier_legal_name'];
  const monetaryFields = ['subtotal', 'tax_amount', 'total', 'line_extension_amount', 'payable_amount'];
  const otherFields = Object.keys(invoice.invoice_data).filter(
    key => ![...headerFields, ...customerFields, ...supplierFields, ...monetaryFields, 'line_items'].includes(key)
  );

  const FieldSection = ({ title, fields }: { title: string; fields: string[] }) => {
    const visibleFields = fields.filter(field => invoice.invoice_data[field] !== undefined);
    if (visibleFields.length === 0) return null;

    return (
      <div className="space-y-3">
        <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">{title}</h4>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {visibleFields.map(field => {
            const isMissing = invoice.missing_fields?.includes(field);
            return (
              <div key={field} className={cn('space-y-1', isMissing && 'opacity-50')}>
                <div className="text-xs font-medium text-gray-500 flex items-center gap-1">
                  {formatFieldName(field)}
                  {isMissing && <AlertCircle className="h-3 w-3 text-red-500" title="Missing" />}
                </div>
                <div className="text-sm text-gray-900 break-words">
                  {renderFieldValue(field, invoice.invoice_data[field])}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
      {/* Overlay */}
      <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>

      {/* Modal */}
      <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div className="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-4xl">
          {/* Header */}
          <div className="bg-white px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-semibold text-gray-900" id="modal-title">
                  Invoice Details
                </h3>
                {invoice.status === 'success' ? (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-800">
                    <CheckCircle className="h-3 w-3 mr-1" />
                    Success
                  </span>
                ) : (
                  <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-800">
                    <XCircle className="h-3 w-3 mr-1" />
                    Failed
                  </span>
                )}
              </div>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500 transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="bg-gray-50 px-6 py-6 max-h-[calc(100vh-200px)] overflow-y-auto">
            <div className="space-y-6">
              {/* Validation Notes */}
              {invoice.validation_notes && (
                <div className={cn(
                  'p-4 rounded-md',
                  invoice.status === 'success' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'
                )}>
                  <p className={cn(
                    'text-sm',
                    invoice.status === 'success' ? 'text-green-700' : 'text-red-700'
                  )}>
                    {invoice.validation_notes}
                  </p>
                </div>
              )}

              {/* Missing Fields Alert */}
              {invoice.missing_fields && invoice.missing_fields.length > 0 && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
                  <div className="flex items-start">
                    <AlertCircle className="h-5 w-5 text-yellow-600 mr-3 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-medium text-yellow-800 mb-1">Missing Fields</h4>
                      <p className="text-sm text-yellow-700">
                        {invoice.missing_fields.map(formatFieldName).join(', ')}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Validation Errors */}
              {invoice.validation_errors && invoice.validation_errors.length > 0 && (
                <div className="bg-red-50 border border-red-200 rounded-md p-4">
                  <div className="flex items-start">
                    <XCircle className="h-5 w-5 text-red-600 mr-3 flex-shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <h4 className="text-sm font-medium text-red-800 mb-2">Validation Errors</h4>
                      <ul className="space-y-1">
                        {invoice.validation_errors.map((error, idx) => (
                          <li key={idx} className="text-sm text-red-700">
                            <span className="font-medium">{formatFieldName(error.field)}:</span> {error.message}
                          </li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </div>
              )}

              {/* Invoice Data Sections */}
              <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-6">
                <FieldSection title="Invoice Header" fields={headerFields} />
                <FieldSection title="Customer Information" fields={customerFields} />
                <FieldSection title="Supplier Information" fields={supplierFields} />
                <FieldSection title="Monetary Details" fields={monetaryFields} />
                {otherFields.length > 0 && <FieldSection title="Additional Information" fields={otherFields} />}

                {/* Line Items */}
                {invoice.invoice_data.line_items && Array.isArray(invoice.invoice_data.line_items) && (
                  <div className="space-y-3">
                    <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Line Items ({invoice.invoice_data.line_items.length})
                    </h4>
                    <div className="space-y-2">
                      {invoice.invoice_data.line_items.map((item: any, idx: number) => (
                        <div key={idx} className="bg-gray-50 rounded-md p-3 text-sm">
                          <div className="font-medium text-gray-900">{item.item_name || `Item ${idx + 1}`}</div>
                          <div className="text-gray-600 mt-1">
                            {item.quantity && <span>Qty: {item.quantity} | </span>}
                            {item.price && <span>Price: {item.price} | </span>}
                            {item.line_amount && <span>Total: {item.line_amount}</span>}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="bg-gray-50 px-6 py-4 border-t border-gray-200 flex justify-end">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
