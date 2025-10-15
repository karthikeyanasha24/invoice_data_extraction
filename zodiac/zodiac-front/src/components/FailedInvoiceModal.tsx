'use client';

import { useState } from 'react';
import { X, CheckCircle, XCircle, Edit3, MessageCircle, Upload } from 'lucide-react';
import { cn } from '@/lib/utils';
import { FailedInvoiceDetails } from '@/types';

interface FailedInvoiceModalProps {
  invoice: FailedInvoiceDetails;
  isOpen: boolean;
  onClose: () => void;
  onRetry: (file: File) => void;
  onStartConversation: () => void;
}

export default function FailedInvoiceModal({ 
  invoice, 
  isOpen, 
  onClose, 
  onRetry, 
  onStartConversation 
}: FailedInvoiceModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  if (!isOpen) return null;

  const handleFileSelect = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedFile(file);
    }
  };

  const handleRetry = () => {
    if (selectedFile) {
      onRetry(selectedFile);
      onClose();
    }
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-medium text-gray-900">Invoice Processing Failed</h3>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600"
            >
              <X className="h-6 w-6" />
            </button>
          </div>
        </div>

        <div className="px-6 py-4 space-y-6">
          {/* Invoice Info */}
          <div className="bg-gray-50 rounded-lg p-4">
            <h4 className="font-medium text-gray-900 mb-2">Invoice Information</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-gray-500">Tracking ID:</span>
                <p className="font-mono text-xs">{invoice.tracking_id}</p>
              </div>
              <div>
                <span className="text-gray-500">Uploaded:</span>
                <p>{new Date(invoice.uploaded_at).toLocaleString()}</p>
              </div>
            </div>
          </div>

          {/* Processing Steps */}
          <div className="space-y-4">
            <h4 className="font-medium text-gray-900">Processing Steps</h4>
            
            {/* XML Validation */}
            <div className="border rounded-lg p-4">
              <div className="flex items-center space-x-3 mb-2">
                {invoice.xml_validation_pass ? (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
                <span className="font-medium">XML Validation</span>
                <span className={cn(
                  "px-2 py-1 rounded-full text-xs font-medium",
                  invoice.xml_validation_pass 
                    ? "bg-green-100 text-green-800" 
                    : "bg-red-100 text-red-800"
                )}>
                  {invoice.xml_validation_pass ? 'Passed' : 'Failed'}
                </span>
              </div>
              {invoice.xml_convert_message && (
                <p className="text-sm text-gray-600 mt-1">{invoice.xml_convert_message}</p>
              )}
            </div>

            {/* EDI Conversion */}
            <div className="border rounded-lg p-4">
              <div className="flex items-center space-x-3 mb-2">
                {invoice.edi_convert_pass ? (
                  <CheckCircle className="h-5 w-5 text-green-500" />
                ) : (
                  <XCircle className="h-5 w-5 text-red-500" />
                )}
                <span className="font-medium">EDI Conversion</span>
                <span className={cn(
                  "px-2 py-1 rounded-full text-xs font-medium",
                  invoice.edi_convert_pass 
                    ? "bg-green-100 text-green-800" 
                    : "bg-red-100 text-red-800"
                )}>
                  {invoice.edi_convert_pass ? 'Passed' : 'Failed'}
                </span>
              </div>
              {invoice.edi_convert_message && (
                <p className="text-sm text-gray-600 mt-1">{invoice.edi_convert_message}</p>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="space-y-4">
            <h4 className="font-medium text-gray-900">Next Steps</h4>
            
            {/* Retry with New File */}
            <div className="border rounded-lg p-4">
              <div className="flex items-center space-x-3 mb-3">
                <Edit3 className="h-5 w-5 text-blue-500" />
                <span className="font-medium">Retry with Updated File</span>
              </div>
              <p className="text-sm text-gray-600 mb-3">
                Upload a corrected version of your invoice file to retry processing.
              </p>
              <div className="space-y-3">
                <input
                  type="file"
                  accept=".xml"
                  onChange={handleFileSelect}
                  className="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100"
                />
                <button
                  onClick={handleRetry}
                  disabled={!selectedFile}
                  className={cn(
                    "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium",
                    selectedFile
                      ? "bg-blue-600 text-white hover:bg-blue-700"
                      : "bg-gray-300 text-gray-500 cursor-not-allowed"
                  )}
                >
                  <Upload className="h-4 w-4" />
                  <span>Retry Processing</span>
                </button>
              </div>
            </div>

            {/* AI Assistant */}
            <div className="border rounded-lg p-4">
              <div className="flex items-center space-x-3 mb-3">
                <MessageCircle className="h-5 w-5 text-purple-500" />
                <span className="font-medium">Get AI Help</span>
              </div>
              <p className="text-sm text-gray-600 mb-3">
                Get assistance from our AI assistant to understand and fix the issues with your invoice.
              </p>
              <button
                onClick={onStartConversation}
                className="flex items-center space-x-2 px-4 py-2 bg-purple-600 text-white rounded-md text-sm font-medium hover:bg-purple-700"
              >
                <MessageCircle className="h-4 w-4" />
                <span>Start AI Conversation</span>
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-gray-100 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-200"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
