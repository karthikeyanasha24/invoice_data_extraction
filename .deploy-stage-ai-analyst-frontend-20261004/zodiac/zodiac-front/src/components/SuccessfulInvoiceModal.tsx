'use client';

import { useState, useEffect } from 'react';
import { X, CheckCircle, Download, Share2, Trash2, Mail, MessageCircle, Eye, Edit3, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Invoice, VersionComparison } from '@/types';
import DiffViewer from './DiffViewer';
import FileEditorModal from './FileEditorModal';
import { versionsApi } from '@/lib/api';

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
  
  // === VERSION CONTROL STATE ===
  const [activeTab, setActiveTab] = useState<'info' | 'xml' | 'edi'>('info');
  const [xmlComparison, setXmlComparison] = useState<VersionComparison | null>(null);
  const [ediComparison, setEdiComparison] = useState<VersionComparison | null>(null);
  const [isLoadingComparison, setIsLoadingComparison] = useState(false);
  const [comparisonError, setComparisonError] = useState('');
  const [showXmlEditor, setShowXmlEditor] = useState(false);
  const [showEdiEditor, setShowEdiEditor] = useState(false);
  const [xmlContent, setXmlContent] = useState('');
  const [ediContent, setEdiContent] = useState('');
  const [isLoadingContent, setIsLoadingContent] = useState(false);

  // Load comparison data when tab changes
  useEffect(() => {
    if (!isOpen || !invoice.tracking_id) return;

    const loadComparison = async () => {
      if (activeTab === 'xml' && !xmlComparison && !isLoadingComparison) {
        setIsLoadingComparison(true);
        setComparisonError('');
        try {
          const data = await versionsApi.getVersionComparison(
            invoice.tracking_id!,
            'xml',
            true
          );
          setXmlComparison(data);
        } catch (error: any) {
          setComparisonError(error.message || 'Failed to load XML comparison');
        } finally {
          setIsLoadingComparison(false);
        }
      }

      if (activeTab === 'edi' && !ediComparison && !isLoadingComparison) {
        setIsLoadingComparison(true);
        setComparisonError('');
        try {
          const data = await versionsApi.getVersionComparison(
            invoice.tracking_id!,
            'edi',
            true
          );
          setEdiComparison(data);
        } catch (error: any) {
          setComparisonError(error.message || 'Failed to load EDI comparison');
        } finally {
          setIsLoadingComparison(false);
        }
      }
    };

    loadComparison();
  }, [activeTab, isOpen, invoice.tracking_id, xmlComparison, ediComparison, isLoadingComparison]);

  // Load file content for editing
  const loadFileContent = async (fileType: 'xml' | 'edi') => {
    if (!invoice.tracking_id) return;
    
    setIsLoadingContent(true);
    try {
      const data = await versionsApi.getFileContent(
        invoice.tracking_id,
        fileType,
        'current',
        true
      );
      if (fileType === 'xml') {
        setXmlContent(data.content);
      } else {
        setEdiContent(data.content);
      }
    } catch (error: any) {
      setComparisonError(`Failed to load ${fileType} content: ${error.message}`);
    } finally {
      setIsLoadingContent(false);
    }
  };

  // Save file edit
  const handleSaveFileEdit = async (content: string, fileType: 'xml' | 'edi') => {
    if (!invoice.tracking_id) throw new Error('Invoice tracking ID not found');
    
    try {
      await versionsApi.saveFileEdit(
        invoice.tracking_id,
        fileType,
        content,
        true
      );
      
      // Refresh comparison after saving
      if (fileType === 'xml') {
        setXmlComparison(null);
      } else {
        setEdiComparison(null);
      }
      
      return { success: true };
    } catch (error: any) {
      throw error;
    }
  };

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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
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

        {/* Tabs */}
        <div className="border-b border-gray-200 px-6 flex items-center gap-4 bg-gray-50">
          <button
            onClick={() => setActiveTab('info')}
            className={cn(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors",
              activeTab === 'info'
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-600 hover:text-gray-900"
            )}
          >
            Invoice Info
          </button>
          <button
            onClick={() => setActiveTab('xml')}
            className={cn(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2",
              activeTab === 'xml'
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-600 hover:text-gray-900"
            )}
          >
            <Eye className="h-4 w-4" />
            XML Comparison
          </button>
          <button
            onClick={() => setActiveTab('edi')}
            className={cn(
              "px-4 py-3 text-sm font-medium border-b-2 transition-colors flex items-center gap-2",
              activeTab === 'edi'
                ? "border-blue-500 text-blue-600"
                : "border-transparent text-gray-600 hover:text-gray-900"
            )}
          >
            <Eye className="h-4 w-4" />
            EDI Comparison
          </button>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto px-6 py-4">
          {/* INFO TAB */}
          {activeTab === 'info' && (
            <div className="space-y-6">
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
                    <span className="text-green-700">Tracking ID:</span>
                    <p className="font-mono text-xs">{invoice.tracking_id}</p>
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
                              "px-4 py-2 rounded-md text-sm font-medium w-full",
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
                              "px-4 py-2 rounded-md text-sm font-medium w-full",
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
          )}

          {/* XML COMPARISON TAB */}
          {activeTab === 'xml' && (
            <div className="space-y-4">
              {isLoadingComparison && (
                <div className="flex justify-center items-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
              )}

              {comparisonError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <h5 className="font-medium text-red-900">Error</h5>
                    <p className="text-sm text-red-700 mt-1">{comparisonError}</p>
                  </div>
                </div>
              )}

              {xmlComparison && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="font-medium text-gray-900">XML File Comparison</h4>
                    <button
                      onClick={() => {
                        loadFileContent('xml');
                        setShowXmlEditor(true);
                      }}
                      disabled={isLoadingContent}
                      className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
                    >
                      <Edit3 className="h-4 w-4" />
                      Edit XML
                    </button>
                  </div>
                  <DiffViewer
                    originalContent={xmlComparison.original_content}
                    fixedContent={xmlComparison.fixed_content}
                    diffs={xmlComparison.diffs}
                    fileType="xml"
                    isAiCorrected={xmlComparison.is_ai_corrected}
                    totalModifiedLines={xmlComparison.modified_line_count}
                  />
                </div>
              )}
            </div>
          )}

          {/* EDI COMPARISON TAB */}
          {activeTab === 'edi' && (
            <div className="space-y-4">
              {isLoadingComparison && (
                <div className="flex justify-center items-center py-8">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
                </div>
              )}

              {comparisonError && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
                  <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
                  <div>
                    <h5 className="font-medium text-red-900">Error</h5>
                    <p className="text-sm text-red-700 mt-1">{comparisonError}</p>
                  </div>
                </div>
              )}

              {ediComparison && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="font-medium text-gray-900">EDI File Comparison</h4>
                    <button
                      onClick={() => {
                        loadFileContent('edi');
                        setShowEdiEditor(true);
                      }}
                      disabled={isLoadingContent}
                      className="flex items-center gap-2 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 text-sm"
                    >
                      <Edit3 className="h-4 w-4" />
                      Edit EDI
                    </button>
                  </div>
                  <DiffViewer
                    originalContent={ediComparison.original_content}
                    fixedContent={ediComparison.fixed_content}
                    diffs={ediComparison.diffs}
                    fileType="edi"
                    isAiCorrected={ediComparison.is_ai_corrected}
                    totalModifiedLines={ediComparison.modified_line_count}
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-gray-200">
          <button
            onClick={onClose}
            className="w-full px-4 py-2 bg-gray-100 text-gray-700 rounded-md text-sm font-medium hover:bg-gray-200"
          >
            Close
          </button>
        </div>

        {/* File Editor Modals */}
        <FileEditorModal
          isOpen={showXmlEditor}
          onClose={() => setShowXmlEditor(false)}
          onSave={async (content) => handleSaveFileEdit(content, 'xml')}
          initialContent={xmlContent}
          fileType="xml"
          trackingId={invoice.tracking_id || ''}
        />

        <FileEditorModal
          isOpen={showEdiEditor}
          onClose={() => setShowEdiEditor(false)}
          onSave={async (content) => handleSaveFileEdit(content, 'edi')}
          initialContent={ediContent}
          fileType="edi"
          trackingId={invoice.tracking_id || ''}
        />
      </div>
    </div>
  );
}
