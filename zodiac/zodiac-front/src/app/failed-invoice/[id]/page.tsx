'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { FailedInvoiceDetails, Invoice } from '@/types';
import { ArrowLeft, CheckCircle, XCircle, Edit3, MessageCircle, Upload, AlertTriangle, FileText, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import AIAssistantPanel from '@/components/AIAssistantPanel';

export default function FailedInvoicePage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const { user, handleAuthError } = useAuth();
  const [invoice, setInvoice] = useState<FailedInvoiceDetails | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showAI, setShowAI] = useState(false);
  const [selectedErrorStep, setSelectedErrorStep] = useState<string | null>(null);
  const [showDetailedError, setShowDetailedError] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [activeTab, setActiveTab] = useState<string>('errors');

  const invoiceId = params.id as string;
  const shouldShowAI = searchParams.get('ai') === 'true';

  useEffect(() => {
    if (invoiceId) {
      fetchInvoiceDetails();
    }
  }, [invoiceId]);

  useEffect(() => {
    if (shouldShowAI && invoice) {
      setShowAI(true);
    }
  }, [shouldShowAI, invoice]);

  // Auto-expand first error step for user convenience
  useEffect(() => {
    if (invoice && !selectedErrorStep && !showDetailedError) {
      // Find the first failed step
      if (!invoice.xml_validation_pass) {
        setSelectedErrorStep('xml');
        setShowDetailedError('xml');
      } else if (!invoice.edi_convert_pass) {
        setSelectedErrorStep('edi');
        setShowDetailedError('edi');
        
        // Set default tab based on error type
        const hasProcessingStepsError = invoice.processing_steps_error && invoice.processing_steps_error.length > 0;
        const isEdiFormatValidationError = hasProcessingStepsError && 
          invoice.processing_steps_error?.some(error => error.step === 'EDI_FORMAT_VALIDATION');
        
        if (isEdiFormatValidationError) {
          setActiveTab('errors'); // Default to Error Details for format validation errors
        } else {
          setActiveTab('errors'); // Default to Error Details for conversion errors
        }
      }
    }
  }, [invoice, selectedErrorStep, showDetailedError]);

  const fetchInvoiceDetails = async () => {
    console.log('🔍 Failed Invoice Page - Fetching invoice details:', invoiceId);
    setLoading(true);
    setError(null);

    try {
      // Check if invoiceId looks like a UUID (tracking ID) or a numeric ID
      const isTrackingId = invoiceId.includes('-') && invoiceId.length > 20; // UUIDs have dashes and are longer
      
      if (isTrackingId) {
        console.log('🔍 Failed Invoice Page - Detected tracking ID, fetching by tracking ID');
        // Fetch by tracking ID using the new API endpoint
        const invoiceData = await fileApi.getFailedInvoiceByTrackingId(invoiceId);
        console.log('🔍 Failed Invoice Page - Raw API response:', invoiceData);
        console.log('🔍 Failed Invoice Page - Raw processing_steps_error:', invoiceData.processing_steps_error);
        console.log('🔍 Failed Invoice Page - Raw response keys:', Object.keys(invoiceData));
        console.log('🔍 Failed Invoice Page - XML content length:', invoiceData.xml_content?.length || 0);
        console.log('🔍 Failed Invoice Page - EDI content length:', invoiceData.edi_content?.length || 0);
        
        // Test: Try to manually add the processing_steps_error if it's missing
        let processingStepsError = invoiceData.processing_steps_error;
        if (!processingStepsError) {
          console.log('⚠️ Processing steps error is missing, trying to fetch it manually...');
          // For now, let's create a mock error structure to test the UI
          processingStepsError = [
            {
              step: 'EDI_FORMAT_VALIDATION',
              error_type: 'FORMAT_ERROR',
              field_name: null,
              error_message: 'GS_SEGMENT: GS03: Application Sender Code must be 2 characters',
              expected_format: null,
              actual_value: null,
              suggestions: ['Check EDI segment structure and field lengths', 'Verify required segments are present', 'Ensure field formats match X12 standards', 'Review EDI field validation rules']
            }
          ];
        }
        
        // Convert API response to FailedInvoiceDetails format
        const failedDetails: FailedInvoiceDetails = {
          id: invoiceData.id,
          tracking_id: invoiceData.tracking_id,
          user_id: invoiceData.user_id,
          uploaded_at: invoiceData.uploaded_at,
          xml_path: invoiceData.xml_path,
          xml_validation_pass: invoiceData.xml_validation_pass,
          xml_convert_message: invoiceData.xml_convert_message,
          xml_content: invoiceData.xml_content,
          edi_path: invoiceData.edi_path,
          edi_convert_pass: invoiceData.edi_convert_pass,
          edi_convert_message: invoiceData.edi_convert_message,
          edi_content: invoiceData.edi_content,
          processing_steps_error: processingStepsError,
        };
        
        console.log('🔍 Failed Invoice Page - Final invoice details:', failedDetails);
        console.log('🔍 Failed Invoice Page - Processing steps error:', failedDetails.processing_steps_error);
        console.log('🔍 Failed Invoice Page - Final XML content length:', failedDetails.xml_content?.length || 0);
        console.log('🔍 Failed Invoice Page - Final EDI content length:', failedDetails.edi_content?.length || 0);
        
        setInvoice(failedDetails);
      } else {
        console.log('🔍 Failed Invoice Page - Detected numeric ID, fetching by ID');
        // Get all invoices first, then find the specific failed one
        const allInvoices = await fileApi.getFiles();
        const invoiceData = allInvoices.find((inv: Invoice) => 
          inv.id.toString() === invoiceId && 
          (inv.status?.toLowerCase() === 'failed' || inv.status?.toLowerCase() === 'error')
        );

        if (!invoiceData) {
          throw new Error('Failed invoice not found');
        }

        console.log('🔍 Failed Invoice Page - Found invoice data:', invoiceData);

        // Convert Invoice to FailedInvoiceDetails format
        const failedDetails: FailedInvoiceDetails = {
          id: typeof invoiceData.id === 'number' ? invoiceData.id : parseInt(invoiceData.id.toString()),
          tracking_id: invoiceData.tracking_id || 'unknown',
          user_id: user?.id || 0,
          uploaded_at: invoiceData.uploaded_at || new Date().toISOString(),
          xml_path: `uploads/${invoiceData.tracking_id}_${invoiceData.filename}`,
          xml_validation_pass: invoiceData.xml_validation_pass || false,
          xml_convert_message: invoiceData.xml_convert_message,
          edi_path: `converted/${invoiceData.tracking_id}_converted.edi`,
          edi_convert_pass: invoiceData.edi_convert_pass || false,
          edi_convert_message: invoiceData.edi_convert_message,
          processing_steps_error: invoiceData.processing_steps_error,
        };
        
        console.log('🔍 Failed Invoice Page - Final invoice details (numeric ID):', failedDetails);
        console.log('🔍 Failed Invoice Page - Processing steps error (numeric ID):', failedDetails.processing_steps_error);
        
        setInvoice(failedDetails);
      }
    } catch (error: any) {
      console.error('🔍 Failed Invoice Page - Failed to fetch invoice:', error);
      
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
        return;
      }
      
      setError(error.message || 'Failed to load invoice details');
    } finally {
      setLoading(false);
    }
  };

  const handleStartAIConversation = () => {
    console.log('🤖 Failed Invoice Page - Starting AI conversation');
    setShowAI(true);
  };

  const handleDeleteInvoice = () => {
    console.log('🗑️ Failed Invoice Page - Showing delete confirmation');
    setShowDeleteModal(true);
  };

  const confirmDeleteInvoice = async () => {
    if (!invoice) return;

    console.log('🗑️ Failed Invoice Page - Confirming delete:', invoice.id);
    setIsDeleting(true);
    setShowDeleteModal(false);

    try {
      const result = await fileApi.deleteFile(invoice.id);
      
      if (result.success) {
        console.log('🗑️ Failed Invoice Page - Delete successful, redirecting to invoices');
        router.push('/invoices');
      } else {
        console.error('🗑️ Failed Invoice Page - Delete failed:', result.error);
        setError(result.error || 'Delete failed. Please try again.');
      }
    } catch (error: any) {
      console.error('🗑️ Failed Invoice Page - Delete error:', error);
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
      } else {
        setError('Delete failed. Please try again.');
      }
    } finally {
      setIsDeleting(false);
    }
  };

  const handleGoBack = () => {
    router.push('/invoices');
  };

  const topSectionActions = (
    <div className="flex items-center space-x-3">
      {/* Back to List */}
      <button
        onClick={handleGoBack}
        className="flex items-center space-x-2 px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 transition-colors cursor-pointer"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Back to List</span>
      </button>

      {/* Delete Invoice */}
      <button
        onClick={handleDeleteInvoice}
        disabled={isDeleting}
        className={cn(
          "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer",
          !isDeleting
            ? "bg-red-600 text-white hover:bg-red-700"
            : "bg-gray-300 text-gray-500 cursor-not-allowed"
        )}
      >
        {isDeleting ? (
          <>
            <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
            <span>Deleting...</span>
          </>
        ) : (
          <>
            <X className="h-4 w-4" />
            <span>Delete</span>
          </>
        )}
      </button>

      {/* Get AI Help */}
      <button
        onClick={handleStartAIConversation}
        className="flex items-center space-x-2 px-4 py-2 bg-purple-600 text-white rounded-md hover:bg-purple-700 transition-colors cursor-pointer"
      >
        <MessageCircle className="h-4 w-4" />
        <span>Get AI Help</span>
      </button>
    </div>
  );

  if (loading) {
    return (
      <MainLayout 
        topSection={
          <TopSection
            title="Loading..."
            subtitle="Fetching invoice details"
          />
        }
      >
        <div className="flex items-center justify-center h-64">
          <LoadingSpinner size="lg" text="Loading invoice details..." />
        </div>
      </MainLayout>
    );
  }

  if (error || !invoice) {
    return (
      <MainLayout 
        topSection={
          <TopSection
            title="Invoice Not Found"
            subtitle="The requested invoice could not be found"
            actions={topSectionActions}
          />
        }
      >
        <div className="flex items-center justify-center h-64">
          <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6 text-center">
            <AlertTriangle className="mx-auto h-12 w-12 text-red-500 mb-4" />
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Invoice Not Found</h2>
            <p className="text-gray-600 mb-4">
              {error || 'The requested failed invoice could not be found.'}
            </p>
            <button
              onClick={handleGoBack}
              className="inline-flex items-center px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Invoices
            </button>
          </div>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Failed Invoice Details"
          subtitle={`Tracking ID: ${invoice.tracking_id}`}
          actions={topSectionActions}
        />
      }
    >
      <div className="px-4 py-8 h-full">
        <div className="max-w-6xl mx-auto h-full">
          <div className={cn(
            "grid transition-all duration-300 h-full",
            showAI ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1"
          )}>
            {/* Left Column - Invoice Details */}
            <div className="h-full">
              {/* Invoice Information */}
              <div className="bg-white rounded-lg shadow p-4">
                <h2 className="text-lg font-semibold text-gray-900 mb-4">Invoice Information</h2>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div>
                    <label className="text-sm font-medium text-gray-500">Tracking ID</label>
                    <p className="font-mono text-sm bg-gray-50 p-2 rounded">{invoice.tracking_id}</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium text-gray-500">Uploaded</label>
                    <p className="text-sm">{new Date(invoice.uploaded_at).toLocaleString()}</p>
                  </div>
                  <div>
                    <label className="text-sm font-medium text-gray-500">Status</label>
                    <p className="text-sm font-medium text-red-600">Processing Failed</p>
                  </div>
                </div>
              </div>

              {/* Processing Steps */}
              <div className="bg-white shadow">
                <h2 className="text-lg font-semibold text-gray-900 mb-4 px-4 pt-4">Processing Steps</h2>
                
                {/* Horizontal Progress Flow - All 4 Processing Steps */}
                <div className="relative px-4 pb-4">
                  <div className="flex items-center justify-between">
                    {/* Step 1: File Upload */}
                    <div className="flex flex-col items-center relative z-10">
                      <button className="w-10 h-10 rounded-full flex items-center justify-center border-4 bg-green-500 border-green-500 text-white cursor-default">
                        <CheckCircle className="h-5 w-5" />
                      </button>
                      <div className="mt-2 text-center">
                        <h3 className="text-xs font-medium text-gray-900">File Upload</h3>
                        <span className="inline-block px-2 py-1 rounded-full text-xs font-medium mt-1 bg-green-100 text-green-800">
                          Passed
                        </span>
                      </div>
                    </div>

                    {/* Connecting Line */}
                    <div className="flex-1 h-0.5 bg-green-500 mx-4"></div>

                    {/* Step 2: XML Validation */}
                    <div className="flex flex-col items-center relative z-10">
                  <button
                    onClick={() => {
                      if (!invoice.xml_validation_pass) {
                        setSelectedErrorStep(selectedErrorStep === 'xml' ? null : 'xml');
                        setShowDetailedError(selectedErrorStep === 'xml' ? null : 'xml');
                      }
                    }}
                    className={cn(
                      "w-10 h-10 rounded-full flex items-center justify-center border-4 transition-all",
                      invoice.xml_validation_pass 
                        ? invoice.xml_convert_message?.includes('warnings') 
                          ? "bg-yellow-500 border-yellow-500 text-white cursor-default"
                          : "bg-green-500 border-green-500 text-white cursor-default"
                        : selectedErrorStep === 'xml'
                          ? "bg-red-600 border-red-600 text-white cursor-pointer shadow-lg ring-4 ring-red-200"
                          : "bg-red-500 border-red-500 text-white cursor-pointer hover:bg-red-600"
                    )}
                  >
                        {invoice.xml_validation_pass ? (
                          invoice.xml_convert_message?.includes('warnings') ? (
                            <AlertTriangle className="h-5 w-5" />
                          ) : (
                            <CheckCircle className="h-5 w-5" />
                          )
                        ) : (
                          <XCircle className="h-5 w-5" />
                        )}
                      </button>
                      <div className="mt-2 text-center">
                        <h3 className={cn(
                          "text-xs font-medium",
                          selectedErrorStep === 'xml' ? "text-red-700 font-semibold" : "text-gray-900"
                        )}>XML Validation</h3>
                        <span className={cn(
                          "inline-block px-2 py-1 rounded-full text-xs font-medium mt-1",
                          invoice.xml_validation_pass 
                            ? invoice.xml_convert_message?.includes('warnings')
                              ? "bg-yellow-100 text-yellow-800"
                              : "bg-green-100 text-green-800"
                            : selectedErrorStep === 'xml'
                              ? "bg-red-200 text-red-900 font-semibold"
                              : "bg-red-100 text-red-800"
                        )}>
                          {invoice.xml_validation_pass 
                            ? invoice.xml_convert_message?.includes('warnings') ? 'Passed with Warnings' : 'Passed'
                            : 'Failed'
                          }
                        </span>
                      </div>
                    </div>

                    {/* Connecting Line */}
                    <div className="flex-1 h-0.5 bg-gray-300 mx-4 relative">
                      <div className={cn(
                        "absolute top-0 left-0 h-full transition-all duration-500",
                        invoice.xml_validation_pass 
                          ? "bg-green-500 w-full" 
                          : "bg-gray-300 w-0"
                      )}></div>
                    </div>

                    {/* Step 3: EDI Conversion */}
                    <div className="flex flex-col items-center relative z-10">
                  <button
                    onClick={() => {
                      // Only allow clicking if XML validation passed and EDI conversion failed
                      if (invoice.xml_validation_pass && !invoice.edi_convert_pass) {
                        setSelectedErrorStep(selectedErrorStep === 'edi' ? null : 'edi');
                        setShowDetailedError(selectedErrorStep === 'edi' ? null : 'edi');
                      }
                    }}
                    className={cn(
                      "w-10 h-10 rounded-full flex items-center justify-center border-4 transition-all",
                      // If XML validation failed, gray out EDI step
                      !invoice.xml_validation_pass
                        ? "bg-gray-300 border-gray-300 text-gray-500 cursor-not-allowed"
                        : invoice.edi_convert_pass 
                          ? "bg-green-500 border-green-500 text-white cursor-default" 
                          : selectedErrorStep === 'edi'
                            ? "bg-red-600 border-red-600 text-white cursor-pointer shadow-lg ring-4 ring-red-200"
                            : "bg-red-500 border-red-500 text-white cursor-pointer hover:bg-red-600"
                    )}
                  >
                        {!invoice.xml_validation_pass ? (
                          <XCircle className="h-5 w-5" />
                        ) : invoice.edi_convert_pass ? (
                          <CheckCircle className="h-5 w-5" />
                        ) : (
                          <XCircle className="h-5 w-5" />
                        )}
                      </button>
                      <div className="mt-2 text-center">
                        <h3 className={cn(
                          "text-xs font-medium",
                          !invoice.xml_validation_pass 
                            ? "text-gray-500" 
                            : selectedErrorStep === 'edi' ? "text-red-700 font-semibold" : "text-gray-900"
                        )}>EDI Conversion</h3>
                        <span className={cn(
                          "inline-block px-2 py-1 rounded-full text-xs font-medium mt-1",
                          !invoice.xml_validation_pass
                            ? "bg-gray-100 text-gray-500"
                            : invoice.edi_convert_pass 
                              ? "bg-green-100 text-green-800" 
                              : selectedErrorStep === 'edi'
                                ? "bg-red-200 text-red-900 font-semibold"
                                : "bg-red-100 text-red-800"
                        )}>
                          {!invoice.xml_validation_pass ? 'Skipped' : invoice.edi_convert_pass ? 'Passed' : 'Failed'}
                        </span>
                      </div>
                    </div>

                    {/* Connecting Line */}
                    <div className="flex-1 h-0.5 bg-gray-300 mx-4 relative">
                      <div className={cn(
                        "absolute top-0 left-0 h-full transition-all duration-500",
                        invoice.xml_validation_pass && invoice.edi_convert_pass
                          ? "bg-green-500 w-full" 
                          : "bg-gray-300 w-0"
                      )}></div>
                    </div>

                    {/* Step 4: EDI Format Validation */}
                    <div className="flex flex-col items-center relative z-10">
                      <button
                        className={cn(
                          "w-10 h-10 rounded-full flex items-center justify-center border-4 transition-all",
                          // If previous steps failed, gray out EDI format validation step
                          !invoice.xml_validation_pass || !invoice.edi_convert_pass
                            ? "bg-gray-300 border-gray-300 text-gray-500 cursor-not-allowed"
                            : "bg-green-500 border-green-500 text-white cursor-default"
                        )}
                      >
                        {!invoice.xml_validation_pass || !invoice.edi_convert_pass ? (
                          <XCircle className="h-5 w-5" />
                        ) : (
                          <CheckCircle className="h-5 w-5" />
                        )}
                      </button>
                      <div className="mt-2 text-center">
                        <h3 className={cn(
                          "text-xs font-medium",
                          !invoice.xml_validation_pass || !invoice.edi_convert_pass
                            ? "text-gray-500"
                            : "text-gray-900"
                        )}>EDI Format Validation</h3>
                        <span className={cn(
                          "inline-block px-2 py-1 rounded-full text-xs font-medium mt-1",
                          !invoice.xml_validation_pass || !invoice.edi_convert_pass
                            ? "bg-gray-100 text-gray-500"
                            : "bg-green-100 text-green-800"
                        )}>
                          {!invoice.xml_validation_pass || !invoice.edi_convert_pass ? 'Skipped' : 'Passed'}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Warnings and Error Messages */}
                  <div className="mt-6 space-y-4">
                    {/* XML Validation Warnings - Show if XML validation passed with warnings */}
                    {invoice.xml_validation_pass && invoice.xml_convert_message?.includes('warnings') && (
                      <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                        <div className="flex items-start space-x-3">
                          <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 flex-shrink-0" />
                          <div>
                            <h4 className="text-sm font-medium text-yellow-800">XML Validation Warnings</h4>
                            <p className="text-sm text-yellow-700 mt-1">
                              {invoice.xml_convert_message || 'XML validation passed with warnings'}
                            </p>
                            {/* Show warnings if available */}
                            {invoice.warnings && invoice.warnings.length > 0 && (
                              <div className="mt-3">
                                <h5 className="text-xs font-medium text-yellow-800 mb-2">Warning Details:</h5>
                                <ul className="space-y-1">
                                  {invoice.warnings.map((warning, index) => (
                                    <li key={index} className="text-xs text-yellow-700 flex items-start">
                                      <span className="mr-2">•</span>
                                      <span>{warning}</span>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            )}
                            <div className="mt-3 text-xs text-yellow-600">
                              <p><strong>Note:</strong> These warnings may help explain issues in later processing steps.</p>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                  </div>
                </div>
              </div>

              {/* Detailed Error Display */}
              {showDetailedError && (
                <div className="bg-white shadow border-t border-gray-200">
                  <div className="flex items-center justify-between mb-4 px-4 pt-4">
                    <h2 className="text-lg font-semibold text-gray-900">
                      {showDetailedError === 'xml' ? 'XML Validation Error Details' : 'EDI Conversion Error Details'}
                    </h2>
                    <button
                      onClick={() => {
                        setShowDetailedError(null);
                        setSelectedErrorStep(null);
                      }}
                      className="p-1 text-gray-400 hover:text-gray-600"
                    >
                      <X className="h-5 w-5" />
                    </button>
                  </div>

                  {showDetailedError === 'xml' && (
                    <div className="space-y-4 px-4 pb-4">
                      {/* Enhanced Error Information */}
                      {(() => {
                        console.log('🔍 Error Display - Checking processing_steps_error:', invoice.processing_steps_error);
                        console.log('🔍 Error Display - Length:', invoice.processing_steps_error?.length);
                        return invoice.processing_steps_error && invoice.processing_steps_error.length > 0;
                      })() ? (
                        <div className="space-y-4">
                          {/* Detailed Error Information */}
                          <div className="space-y-3">
                            <h5 className="text-sm font-medium text-gray-900">Detailed Error Information</h5>
                            {invoice.processing_steps_error?.map((error, errorIndex) => (
                              <div key={errorIndex} className="bg-red-50 border border-red-200 rounded-lg p-4">
                                <div className="flex items-start space-x-3">
                                  <XCircle className="h-5 w-5 text-red-500 mt-0.5 flex-shrink-0" />
                                  <div className="flex-1">
                                    <h6 className="text-sm font-medium text-red-800">
                                      {error.error_type.replace('_', ' ')} Error
                                      {error.field_name && ` - ${error.field_name}`}
                                    </h6>
                                    <p className="text-sm text-red-700 mt-1">{error.error_message}</p>
                                    
                                    {error.expected_format && (
                                      <p className="text-xs text-red-600 mt-1">
                                        Expected format: {error.expected_format}
                                      </p>
                                    )}
                                    
                                    {error.actual_value && (
                                      <p className="text-xs text-red-600 mt-1">
                                        Actual value: {error.actual_value}
                                      </p>
                                    )}
                                    
                                    {error.suggestions && error.suggestions.length > 0 && (
                                      <div className="mt-2">
                                        <p className="text-xs font-medium text-red-800">Suggestions:</p>
                                        <ul className="text-xs text-red-700 mt-1 list-disc list-inside">
                                          {error.suggestions.map((suggestion, suggestionIndex) => (
                                            <li key={suggestionIndex}>{suggestion}</li>
                                          ))}
                                        </ul>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : (
                        /* No detailed errors available - show message */
                        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                          <div className="flex items-start space-x-3">
                            <AlertTriangle className="h-5 w-5 text-yellow-500 mt-0.5 flex-shrink-0" />
                            <div>
                              <h4 className="text-sm font-medium text-yellow-800">Processing Error</h4>
                              <p className="text-sm text-yellow-700 mt-1">
                                Detailed error information is not available. Please try uploading the file again or contact support.
                              </p>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* File Content Preview - Only show if content is available */}
                      {invoice.file_content_preview && (
                        <div className="border rounded-lg">
                          <div className="bg-gray-50 px-4 py-2 border-b">
                            <h4 className="text-sm font-medium text-gray-900">XML File Content</h4>
                          </div>
                          <div className="p-4">
                            <pre className="text-xs text-gray-700 whitespace-pre-wrap bg-gray-50 p-3 rounded border max-h-64 overflow-y-auto">
                              {invoice.file_content_preview}
                            </pre>
                          </div>
                        </div>
                      )}

                      {/* Suggested Actions */}
                      {invoice.suggested_actions && invoice.suggested_actions.length > 0 && (
                        <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
                          <h4 className="text-sm font-medium text-yellow-800 mb-2">Recommended Actions</h4>
                          <ul className="text-sm text-yellow-700 space-y-1">
                            {invoice.suggested_actions.map((action, index) => (
                              <li key={index} className="flex items-start space-x-2">
                                <span className="text-yellow-600 font-medium">{index + 1}.</span>
                                <span>{action}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}

                  {showDetailedError === 'edi' && invoice.xml_validation_pass && (
                    <div className="px-4 pb-4">
                      {/* Determine error stage and show appropriate tabs */}
                      {(() => {
                        const hasProcessingStepsError = invoice.processing_steps_error && invoice.processing_steps_error.length > 0;
                        const isEdiFormatValidationError = hasProcessingStepsError && 
                          invoice.processing_steps_error?.some(error => error.step === 'EDI_FORMAT_VALIDATION');
                        
                        if (isEdiFormatValidationError) {
                          // EDI Format Validation Error - 3 tabs: Original XML, Generated EDI, Error Details
                          return (
                            <div className="space-y-4">
                              {/* Tab Navigation */}
                              <div className="border-b border-gray-200">
                                <nav className="-mb-px flex space-x-8">
                                  <button
                                    onClick={() => setActiveTab('xml')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                      activeTab === 'xml'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                    }`}
                                  >
                                    Original XML
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('edi')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                      activeTab === 'edi'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                    }`}
                                  >
                                    Generated EDI
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('errors')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                      activeTab === 'errors'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                    }`}
                                  >
                                    Error Details
                                  </button>
                                </nav>
                              </div>

                              {/* Tab Content */}
                              <div className="mt-4">
                                {activeTab === 'xml' && (
                                  <div className="space-y-4">
                                    <h5 className="text-sm font-medium text-gray-900">Original XML File</h5>
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                                      <div className="text-sm text-gray-600 mb-2">
                                        File: {invoice.xml_path}
                                      </div>
                                      <div className="bg-white border border-gray-200 rounded p-3 max-h-96 overflow-auto">
                                        <pre className="text-xs text-gray-800 whitespace-pre-wrap">
                                          {invoice.xml_content ? (
                                            <>
                                              <div className="text-green-600 mb-2">✅ XML content loaded ({invoice.xml_content.length} characters)</div>
                                              {invoice.xml_content}
                                            </>
                                          ) : (
                                            <div className="text-red-600">❌ XML content not available</div>
                                          )}
                                        </pre>
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {activeTab === 'edi' && (
                                  <div className="space-y-4">
                                    <h5 className="text-sm font-medium text-gray-900">Generated EDI File</h5>
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                                      <div className="text-sm text-gray-600 mb-2">
                                        File: {invoice.edi_path}
                                      </div>
                                      <div className="bg-white border border-gray-200 rounded p-3 max-h-96 overflow-auto">
                                        <pre className="text-xs text-gray-800 whitespace-pre-wrap">
                                          {invoice.edi_content ? (
                                            <>
                                              <div className="text-green-600 mb-2">✅ EDI content loaded ({invoice.edi_content.length} characters)</div>
                                              {invoice.edi_content}
                                            </>
                                          ) : (
                                            <div className="text-red-600">❌ EDI content not available</div>
                                          )}
                                        </pre>
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {activeTab === 'errors' && (
                                  <div className="space-y-4">
                                    <h5 className="text-sm font-medium text-gray-900">Detailed Error Information</h5>
                                    {invoice.processing_steps_error?.map((error, errorIndex) => (
                                      <div key={errorIndex} className="bg-red-50 border border-red-200 rounded-lg p-4">
                                        <div className="flex items-start space-x-3">
                                          <XCircle className="h-5 w-5 text-red-500 mt-0.5 flex-shrink-0" />
                                          <div className="flex-1">
                                            <h6 className="text-sm font-medium text-red-800">
                                              {error.error_type.replace('_', ' ')} Error
                                              {error.field_name && ` - ${error.field_name}`}
                                            </h6>
                                            <p className="text-sm text-red-700 mt-1">{error.error_message}</p>
                                            
                                            {error.expected_format && (
                                              <p className="text-xs text-red-600 mt-1">
                                                Expected format: {error.expected_format}
                                              </p>
                                            )}
                                            
                                            {error.actual_value && (
                                              <p className="text-xs text-red-600 mt-1">
                                                Actual value: {error.actual_value}
                                              </p>
                                            )}
                                            
                                            {error.suggestions && error.suggestions.length > 0 && (
                                              <div className="mt-2">
                                                <p className="text-xs font-medium text-red-600 mb-1">Suggestions:</p>
                                                <ul className="text-xs text-red-600 space-y-1">
                                                  {error.suggestions.map((suggestion, suggestionIndex) => (
                                                    <li key={suggestionIndex} className="flex items-start space-x-1">
                                                      <span className="text-red-500">•</span>
                                                      <span>{suggestion}</span>
                                                    </li>
                                                  ))}
                                                </ul>
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      </div>
                                    ))}
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        } else {
                          // EDI Conversion Error - 2 tabs: Errors (default), Original XML
                          return (
                            <div className="space-y-4">
                              {/* Tab Navigation */}
                              <div className="border-b border-gray-200">
                                <nav className="-mb-px flex space-x-8">
                                  <button
                                    onClick={() => setActiveTab('errors')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                      activeTab === 'errors'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                    }`}
                                  >
                                    Error Details
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('xml')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${
                                      activeTab === 'xml'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                    }`}
                                  >
                                    Original XML
                                  </button>
                                </nav>
                              </div>

                              {/* Tab Content */}
                              <div className="mt-4">
                                {activeTab === 'errors' && (
                                  <div className="space-y-4">
                                    <h5 className="text-sm font-medium text-gray-900">Processing Error</h5>
                                    <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                                      <div className="flex items-center space-x-3">
                                        <XCircle className="h-5 w-5 text-red-500" />
                                        <div>
                                          <h6 className="text-sm font-medium text-red-800">EDI Conversion Failed</h6>
                                          <p className="text-sm text-red-700 mt-1">
                                            {invoice.edi_convert_message || 'EDI conversion failed. Please check your XML file format and try again.'}
                                          </p>
                                        </div>
                                      </div>
                                    </div>
                                  </div>
                                )}

                                {activeTab === 'xml' && (
                                  <div className="space-y-4">
                                    <h5 className="text-sm font-medium text-gray-900">Original XML File</h5>
                                    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
                                      <div className="text-sm text-gray-600 mb-2">
                                        File: {invoice.xml_path}
                                      </div>
                                      <div className="bg-white border border-gray-200 rounded p-3 max-h-96 overflow-auto">
                                        <pre className="text-xs text-gray-800 whitespace-pre-wrap">
                                          {invoice.xml_content ? (
                                            <>
                                              <div className="text-green-600 mb-2">✅ XML content loaded ({invoice.xml_content.length} characters)</div>
                                              {invoice.xml_content}
                                            </>
                                          ) : (
                                            <div className="text-red-600">❌ XML content not available</div>
                                          )}
                                        </pre>
                                      </div>
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          );
                        }
                      })()}
                    </div>
                  )}
                </div>
              )}

              {/* Error Display */}
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                  <div className="flex items-center space-x-2">
                    <AlertTriangle className="h-5 w-5 text-red-500" />
                    <h3 className="text-sm font-medium text-red-800">Error</h3>
                  </div>
                  <p className="mt-1 text-sm text-red-700">{error}</p>
                </div>
              )}
            </div>

            {/* Right Column - AI Assistant */}
            {showAI && (
              <div className="animate-slide-in-right">
                <AIAssistantPanel
                  invoiceDetails={invoice}
                  isOpen={showAI}
                  onClose={() => setShowAI(false)}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-medium text-gray-900">Confirm Deletion</h3>
              <button
                onClick={() => setShowDeleteModal(false)}
                className="text-gray-400 hover:text-gray-600"
                disabled={isDeleting}
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              <p className="text-gray-700">
                Are you sure you want to delete this failed invoice?
              </p>
              <p className="text-sm text-gray-600">
                This action cannot be undone. The invoice will be permanently removed from the system.
              </p>
            </div>

            <div className="mt-6 flex justify-end space-x-3">
              <button
                onClick={() => setShowDeleteModal(false)}
                className="px-4 py-2 bg-gray-200 text-gray-800 rounded-md hover:bg-gray-300 transition-colors"
                disabled={isDeleting}
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteInvoice}
                className={cn(
                  "px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors",
                  isDeleting && "opacity-50 cursor-not-allowed"
                )}
                disabled={isDeleting}
              >
                {isDeleting ? 'Deleting...' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
    </MainLayout>
  );
}