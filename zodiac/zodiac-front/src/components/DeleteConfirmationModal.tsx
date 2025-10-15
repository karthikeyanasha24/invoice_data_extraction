'use client';

import { X, AlertTriangle, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Invoice } from '@/types';

interface DeleteConfirmationModalProps {
  invoice: Invoice | null;
  isOpen: boolean;
  onClose: () => void;
  onConfirm: () => void;
  isDeleting?: boolean;
}

export default function DeleteConfirmationModal({ 
  invoice, 
  isOpen, 
  onClose, 
  onConfirm,
  isDeleting = false
}: DeleteConfirmationModalProps) {
  if (!isOpen || !invoice) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className="flex-shrink-0">
                <AlertTriangle className="h-6 w-6 text-red-600" />
              </div>
              <h3 className="text-lg font-medium text-gray-900">Delete Invoice</h3>
            </div>
            <button
              onClick={onClose}
              disabled={isDeleting}
              className="text-gray-400 hover:text-gray-600 disabled:opacity-50"
            >
              <X className="h-6 w-6" />
            </button>
          </div>
        </div>

        <div className="px-6 py-4">
          <div className="mb-4">
            <p className="text-sm text-gray-600 mb-3">
              Are you sure you want to delete this invoice? This action will move the invoice to the recycle bin.
            </p>
            
            <div className="bg-gray-50 rounded-lg p-3">
              <div className="flex items-center space-x-2 mb-2">
                <Trash2 className="h-4 w-4 text-gray-500" />
                <span className="font-medium text-gray-900">{invoice.filename}</span>
              </div>
              <div className="text-xs text-gray-500">
                <div>Status: <span className="font-medium">{invoice.status || 'Unknown'}</span></div>
                {invoice.uploaded_at && (
                  <div>Uploaded: <span className="font-medium">{new Date(invoice.uploaded_at).toLocaleString()}</span></div>
                )}
              </div>
            </div>
          </div>

          <div className="text-xs text-gray-500 mb-4">
            <p>• The invoice will be moved to the recycle bin</p>
            <p>• You can restore it later if needed</p>
            <p>• This action cannot be undone immediately</p>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200">
          <div className="flex items-center justify-end space-x-3">
            <button
              onClick={onClose}
              disabled={isDeleting}
              className={cn(
                "px-4 py-2 text-sm font-medium rounded-md transition-colors",
                isDeleting 
                  ? "bg-gray-100 text-gray-400 cursor-not-allowed" 
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              Cancel
            </button>
            <button
              onClick={onConfirm}
              disabled={isDeleting}
              className={cn(
                "flex items-center space-x-2 px-4 py-2 text-sm font-medium rounded-md transition-colors",
                isDeleting
                  ? "bg-red-300 text-red-100 cursor-not-allowed"
                  : "bg-red-600 text-white hover:bg-red-700"
              )}
            >
              {isDeleting ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-red-100 border-t-red-300"></div>
                  <span>Deleting...</span>
                </>
              ) : (
                <>
                  <Trash2 className="h-4 w-4" />
                  <span>Delete Invoice</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

