'use client';

import { X, RotateCcw, CheckCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Invoice } from '@/types';

interface RestoreConfirmationModalProps {
  invoice: Invoice | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isRestoring?: boolean;
}

export default function RestoreConfirmationModal({ 
  invoice, 
  isOpen, 
  onClose, 
  onConfirm,
  isRestoring = false
}: RestoreConfirmationModalProps) {
  if (!isOpen || !invoice) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-3 sm:p-4">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
        <div className="px-4 sm:px-6 py-3 sm:py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2 sm:space-x-3">
              <div className="flex-shrink-0">
                <CheckCircle className="h-5 w-5 sm:h-6 sm:w-6 text-green-600" />
              </div>
              <h3 className="text-base sm:text-lg font-medium text-gray-900">Restore Invoice</h3>
            </div>
            <button
              onClick={onClose}
              disabled={isRestoring}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              <X className="h-5 w-5 sm:h-6 sm:w-6" />
            </button>
          </div>
        </div>

        <div className="px-4 sm:px-6 py-3 sm:py-4">
          <div className="mb-4">
            <p className="text-sm text-gray-600 mb-3">
              Are you sure you want to restore this invoice? It will be moved back to your active invoices list.
            </p>
            
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="flex items-center space-x-2 mb-2">
                <RotateCcw className="h-4 w-4 text-gray-500" />
                <span className="font-medium text-gray-900">{invoice.filename}</span>
              </div>
              <div className="text-xs text-gray-500">
                <div>Status: <span className="font-medium">{invoice.status || 'Unknown'}</span></div>
                {invoice.deleted_at && (
                  <div>Deleted: <span className="font-medium">{new Date(invoice.deleted_at).toLocaleString()}</span></div>
                )}
              </div>
            </div>
          </div>

          <div className="text-xs text-gray-500 mb-4">
            <p>• The invoice will be restored to your active invoices</p>
            <p>• You can access it normally after restoration</p>
            <p>• All invoice data will be preserved</p>
          </div>
        </div>

        <div className="px-4 sm:px-6 py-3 sm:py-4 border-t border-gray-200">
          <div className="flex flex-col-reverse sm:flex-row items-center justify-end space-y-reverse space-y-2 sm:space-y-0 sm:space-x-3 gap-2 sm:gap-0">
            <button
              onClick={onClose}
              disabled={isRestoring}
              className={cn(
                "w-full sm:w-auto px-4 py-2 text-sm font-medium rounded-md transition-colors",
                isRestoring 
                  ? "bg-gray-100 text-gray-400 cursor-not-allowed" 
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isRestoring}
              className={cn(
                "w-full sm:w-auto flex items-center justify-center space-x-2 px-4 py-2 text-sm font-medium rounded-md transition-colors",
                isRestoring
                  ? "bg-green-300 text-green-100 cursor-not-allowed"
                  : "bg-green-600 text-white hover:bg-green-700"
              )}
            >
              {isRestoring ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-green-100 border-t-green-300"></div>
                  <span>Restoring...</span>
                </>
              ) : (
                <>
                  <RotateCcw className="h-4 w-4" />
                  <span>Restore Invoice</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

