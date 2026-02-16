'use client';

import { AlertTriangle, X, Check, RefreshCw, SkipForward } from 'lucide-react';

interface ValidationMismatch {
  field_name: string;
  expected: string;
  actual: string;
}

interface ValidationMismatchModalProps {
  isOpen: boolean;
  invoiceNumber: string;
  customerId: string;
  mismatches: Record<string, { expected: string; actual: string }>;
  onUpdateCustomer: () => void;
  onConvertAnyway: () => void;
  onSkip: () => void;
  onClose: () => void;
}

export default function ValidationMismatchModal({
  isOpen,
  invoiceNumber,
  customerId,
  mismatches,
  onUpdateCustomer,
  onConvertAnyway,
  onSkip,
  onClose,
}: ValidationMismatchModalProps) {
  if (!isOpen) return null;

  const mismatchEntries = Object.entries(mismatches);

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 bg-yellow-50">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-100 rounded-lg">
              <AlertTriangle className="w-6 h-6 text-yellow-600" />
            </div>
            <div>
              <h2 className="text-xl font-bold text-gray-900">Validation Mismatch Detected</h2>
              <p className="text-sm text-gray-600">
                Invoice {invoiceNumber} • Customer: {customerId}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="Close"
          >
            <X className="w-5 h-5 text-gray-500" />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          <p className="text-gray-700 mb-4">
            The following fields in the invoice do not match the customer's expected values:
          </p>

          <div className="space-y-4">
            {mismatchEntries.map(([fieldName, data]) => (
              <div
                key={fieldName}
                className="bg-gray-50 border border-gray-200 rounded-lg p-4"
              >
                <div className="font-medium text-gray-900 mb-3 capitalize">
                  {fieldName.replace(/_/g, ' ')}
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {/* Expected Value */}
                  <div className="bg-white border border-blue-200 rounded-lg p-3">
                    <div className="text-xs font-medium text-blue-600 uppercase mb-1">
                      Customer Expected
                    </div>
                    <div className="text-sm font-mono text-gray-900 break-all">
                      {data.expected || '(empty)'}
                    </div>
                  </div>

                  {/* Actual Value */}
                  <div className="bg-white border border-red-200 rounded-lg p-3">
                    <div className="text-xs font-medium text-red-600 uppercase mb-1">
                      Invoice Actual
                    </div>
                    <div className="text-sm font-mono text-gray-900 break-all">
                      {data.actual || '(empty)'}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>

          <div className="mt-6 bg-blue-50 border border-blue-200 rounded-lg p-4">
            <p className="text-sm text-blue-900 font-medium mb-2">What would you like to do?</p>
            <ul className="text-sm text-blue-800 space-y-1 ml-4">
              <li className="list-disc">
                <strong>Update Customer:</strong> Overwrite customer validation fields with invoice values and convert
              </li>
              <li className="list-disc">
                <strong>Convert Anyway:</strong> Bypass validation and convert without updating customer
              </li>
              <li className="list-disc">
                <strong>Skip:</strong> Don't convert this invoice
              </li>
            </ul>
          </div>
        </div>

        {/* Actions */}
        <div className="px-6 py-4 border-t border-gray-200 bg-gray-50 flex gap-3 justify-end">
          <button
            onClick={onSkip}
            className="flex items-center gap-2 px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-100 transition-colors"
          >
            <SkipForward className="w-4 h-4" />
            Skip This Invoice
          </button>

          <button
            onClick={onConvertAnyway}
            className="flex items-center gap-2 px-4 py-2 bg-yellow-600 text-white rounded-lg hover:bg-yellow-700 transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Convert Anyway
          </button>

          <button
            onClick={onUpdateCustomer}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
          >
            <Check className="w-4 h-4" />
            Update Customer & Convert
          </button>
        </div>
      </div>
    </div>
  );
}
