'use client';

import { X, CheckCircle, XCircle, ArrowRight, ExternalLink } from 'lucide-react';
import { useRouter } from 'next/navigation';

interface FixDetail {
  invoice_id: number;
  tracking_id: string;
  customer_name: string;
  fix_applied: string;
  before_value: string;
  after_value: string;
  success: boolean;
  timestamp: string;
}

interface AutoFixDetailsModalProps {
  isOpen: boolean;
  onClose: () => void;
  fixType: string;
  details: FixDetail[];
  loading: boolean;
}

export default function AutoFixDetailsModal({
  isOpen,
  onClose,
  fixType,
  details,
  loading
}: AutoFixDetailsModalProps) {
  const router = useRouter();

  if (!isOpen) return null;

  const handleViewInvoice = (invoiceId: number, status: string) => {
    if (status === 'successful') {
      router.push(`/invoice/${invoiceId}`);
    } else {
      router.push(`/failed-invoice/${invoiceId}`);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      <div className="flex min-h-screen items-center justify-center p-4">
        {/* Backdrop */}
        <div
          className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
          onClick={onClose}
        />

        {/* Modal */}
        <div className="relative w-full max-w-4xl bg-white rounded-lg shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200">
            <div>
              <h2 className="text-2xl font-bold text-gray-900">Auto-Fix Details</h2>
              <p className="text-sm text-gray-600 mt-1">{fixType}</p>
            </div>
            <button
              onClick={onClose}
              className="p-2 hover:bg-gray-100 rounded-full transition-colors"
            >
              <X className="h-6 w-6 text-gray-500" />
            </button>
          </div>

          {/* Content */}
          <div className="p-6 max-h-[600px] overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
              </div>
            ) : details.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-gray-500">No auto-fix details available</p>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Summary */}
                <div className="bg-blue-50 rounded-lg p-4 mb-6">
                  <div className="grid grid-cols-3 gap-4 text-center">
                    <div>
                      <div className="text-2xl font-bold text-gray-900">{details.length}</div>
                      <div className="text-sm text-gray-600">Total Fixes</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-green-600">
                        {details.filter(d => d.success).length}
                      </div>
                      <div className="text-sm text-gray-600">Successful</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold text-red-600">
                        {details.filter(d => !d.success).length}
                      </div>
                      <div className="text-sm text-gray-600">Failed</div>
                    </div>
                  </div>
                </div>

                {/* Details List */}
                {details.map((detail, index) => (
                  <div
                    key={index}
                    className="border border-gray-200 rounded-lg p-4 hover:shadow-md transition-shadow"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          {detail.success ? (
                            <CheckCircle className="h-5 w-5 text-green-600" />
                          ) : (
                            <XCircle className="h-5 w-5 text-red-600" />
                          )}
                          <span className="font-semibold text-gray-900">
                            {detail.customer_name || 'Unknown Customer'}
                          </span>
                        </div>
                        <p className="text-sm text-gray-600">
                          Tracking ID: <code className="text-xs bg-gray-100 px-2 py-1 rounded">{detail.tracking_id}</code>
                        </p>
                      </div>
                      <button
                        onClick={() => handleViewInvoice(detail.invoice_id, detail.success ? 'successful' : 'failed')}
                        className="flex items-center gap-1 text-sm text-blue-600 hover:text-blue-700"
                      >
                        View
                        <ExternalLink className="h-4 w-4" />
                      </button>
                    </div>

                    {/* Fix Details */}
                    <div className="bg-gray-50 rounded p-3">
                      <div className="text-xs font-medium text-gray-700 mb-2">
                        {detail.fix_applied}
                      </div>
                      <div className="flex items-center gap-3 text-sm">
                        <div className="flex-1 bg-red-50 border border-red-200 rounded px-3 py-2">
                          <div className="text-xs text-red-700 font-medium mb-1">Before</div>
                          <code className="text-xs text-red-900 break-all">
                            {detail.before_value || 'null'}
                          </code>
                        </div>
                        <ArrowRight className="h-5 w-5 text-gray-400 flex-shrink-0" />
                        <div className="flex-1 bg-green-50 border border-green-200 rounded px-3 py-2">
                          <div className="text-xs text-green-700 font-medium mb-1">After</div>
                          <code className="text-xs text-green-900 break-all">
                            {detail.after_value}
                          </code>
                        </div>
                      </div>
                    </div>

                    {/* Timestamp */}
                    <div className="mt-2 text-xs text-gray-500">
                      {new Date(detail.timestamp).toLocaleString()}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-end gap-3 p-6 border-t border-gray-200 bg-gray-50">
            <button
              onClick={onClose}
              className="px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-md hover:bg-gray-50"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

