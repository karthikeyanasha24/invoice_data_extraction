'use client';

import { useState } from 'react';
import { X, CheckCircle, Download, Share2, Trash2, Mail, MessageCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Invoice } from '@/types';

interface SuccessfulInvoiceModalProps {
  invoice: Invoice;
  isOpen: boolean;
  onClose: () => void;
  onDownload: () => void;
  onShare: () => void;
  onDelete: () => void;
}

export default function SuccessfulInvoiceModal({ 
  invoice, 
  isOpen, 
  onClose, 
  onDownload,
  onShare,
  onDelete
}: SuccessfulInvoiceModalProps) {
  const [shareMethod, setShareMethod] = useState<'email' | 'whatsapp' | null>(null);
  const [emailAddress, setEmailAddress] = useState('');
  const [phoneNumber, setPhoneNumber] = useState('');

  if (!isOpen) return null;

  const handleEmailShare = () => {
    if (!emailAddress) return;
    
    const subject = `Invoice: ${invoice.filename}`;
    const body = `Please find attached the processed invoice: ${invoice.filename}`;
    const mailtoLink = `mailto:${emailAddress}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    
    window.open(mailtoLink);
    setShareMethod(null);
    onShare();
  };

  const handleWhatsAppShare = () => {
    if (!phoneNumber) return;
    
    const message = `Invoice processed successfully: ${invoice.filename}`;
    const whatsappLink = `https://wa.me/${phoneNumber.replace(/\D/g, '')}?text=${encodeURIComponent(message)}`;
    
    window.open(whatsappLink, '_blank');
    setShareMethod(null);
    onShare();
  };

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-4 border-b border-gray-200">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <CheckCircle className="h-6 w-6 text-green-500" />
              <h3 className="text-lg font-medium text-gray-900">Invoice Processed Successfully</h3>
            </div>
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
          <div className="bg-green-50 rounded-lg p-4">
            <h4 className="font-medium text-green-900 mb-2">Invoice Information</h4>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <span className="text-green-700">File Name:</span>
                <p className="font-medium">{invoice.filename}</p>
              </div>
              <div>
                <span className="text-green-700">Customer:</span>
                <p>{invoice.customerName || 'N/A'}</p>
              </div>
              <div>
                <span className="text-green-700">Status:</span>
                <p className="font-medium text-green-600">Successfully Processed</p>
              </div>
              <div>
                <span className="text-green-700">Format:</span>
                <p>{invoice.formate || 'N/A'}</p>
              </div>
            </div>
          </div>

          {/* Processing Results */}
          <div className="space-y-4">
            <h4 className="font-medium text-gray-900">Processing Results</h4>
            
            <div className="space-y-3">
              <div className="flex items-center space-x-3 p-3 bg-green-50 rounded-lg">
                <CheckCircle className="h-5 w-5 text-green-500" />
                <div>
                  <span className="font-medium text-green-900">XML Validation</span>
                  <p className="text-sm text-green-700">Passed successfully</p>
                </div>
              </div>

              <div className="flex items-center space-x-3 p-3 bg-green-50 rounded-lg">
                <CheckCircle className="h-5 w-5 text-green-500" />
                <div>
                  <span className="font-medium text-green-900">EDI Conversion</span>
                  <p className="text-sm text-green-700">Completed successfully</p>
                </div>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="space-y-4">
            <h4 className="font-medium text-gray-900">Actions</h4>
            
            <div className="grid grid-cols-1 gap-3">
              {/* Download */}
              <button
                onClick={onDownload}
                className="flex items-center space-x-3 p-3 bg-blue-50 hover:bg-blue-100 rounded-lg transition-colors"
              >
                <Download className="h-5 w-5 text-blue-600" />
                <div className="text-left">
                  <span className="font-medium text-blue-900">Download EDI File</span>
                  <p className="text-sm text-blue-700">Download the processed EDI file</p>
                </div>
              </button>

              {/* Share */}
              <button
                onClick={() => setShareMethod(shareMethod ? null : 'email')}
                className="flex items-center space-x-3 p-3 bg-purple-50 hover:bg-purple-100 rounded-lg transition-colors"
              >
                <Share2 className="h-5 w-5 text-purple-600" />
                <div className="text-left">
                  <span className="font-medium text-purple-900">Share Invoice</span>
                  <p className="text-sm text-purple-700">Share via email or WhatsApp</p>
                </div>
              </button>

              {/* Delete */}
              <button
                onClick={onDelete}
                className="flex items-center space-x-3 p-3 bg-red-50 hover:bg-red-100 rounded-lg transition-colors"
              >
                <Trash2 className="h-5 w-5 text-red-600" />
                <div className="text-left">
                  <span className="font-medium text-red-900">Delete Invoice</span>
                  <p className="text-sm text-red-700">Remove this invoice from your account</p>
                </div>
              </button>
            </div>
          </div>

          {/* Share Options */}
          {shareMethod && (
            <div className="border rounded-lg p-4 bg-gray-50">
              <h5 className="font-medium text-gray-900 mb-3">Share Options</h5>
              
              <div className="space-y-3">
                {/* Email Share */}
                <div>
                  <button
                    onClick={() => setShareMethod('email')}
                    className={cn(
                      "flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium w-full",
                      shareMethod === 'email' 
                        ? "bg-blue-100 text-blue-800" 
                        : "bg-white text-gray-700 hover:bg-gray-100"
                    )}
                  >
                    <Mail className="h-4 w-4" />
                    <span>Share via Email</span>
                  </button>
                  
                  {shareMethod === 'email' && (
                    <div className="mt-2 space-y-2">
                      <input
                        type="email"
                        placeholder="Enter email address"
                        value={emailAddress}
                        onChange={(e) => setEmailAddress(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                      />
                      <button
                        onClick={handleEmailShare}
                        disabled={!emailAddress}
                        className={cn(
                          "px-4 py-2 rounded-md text-sm font-medium",
                          emailAddress
                            ? "bg-blue-600 text-white hover:bg-blue-700"
                            : "bg-gray-300 text-gray-500 cursor-not-allowed"
                        )}
                      >
                        Send Email
                      </button>
                    </div>
                  )}
                </div>

                {/* WhatsApp Share */}
                <div>
                  <button
                    onClick={() => setShareMethod('whatsapp')}
                    className={cn(
                      "flex items-center space-x-2 px-3 py-2 rounded-md text-sm font-medium w-full",
                      shareMethod === 'whatsapp' 
                        ? "bg-green-100 text-green-800" 
                        : "bg-white text-gray-700 hover:bg-gray-100"
                    )}
                  >
                    <MessageCircle className="h-4 w-4" />
                    <span>Share via WhatsApp</span>
                  </button>
                  
                  {shareMethod === 'whatsapp' && (
                    <div className="mt-2 space-y-2">
                      <input
                        type="tel"
                        placeholder="Enter phone number"
                        value={phoneNumber}
                        onChange={(e) => setPhoneNumber(e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm"
                      />
                      <button
                        onClick={handleWhatsAppShare}
                        disabled={!phoneNumber}
                        className={cn(
                          "px-4 py-2 rounded-md text-sm font-medium",
                          phoneNumber
                            ? "bg-green-600 text-white hover:bg-green-700"
                            : "bg-gray-300 text-gray-500 cursor-not-allowed"
                        )}
                      >
                        Open WhatsApp
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
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
