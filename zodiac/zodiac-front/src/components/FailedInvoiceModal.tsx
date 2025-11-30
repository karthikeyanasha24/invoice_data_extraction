'use client';

import { useState, useEffect } from 'react';
import { X, CheckCircle, XCircle, Edit3, MessageCircle, Upload, Eye, AlertCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import { FailedInvoiceDetails, VersionComparison } from '@/types';
import DiffViewer from './DiffViewer';
import FileEditorModal from './FileEditorModal';
import { versionsApi } from '@/lib/api';

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
            false
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
            false
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
        false
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
        false
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
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h3 className="text-lg font-medium text-gray-900">Invoice Processing Failed</h3>
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
