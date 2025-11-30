'use client';

import { useState, useEffect } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import api, { fileApi } from '@/lib/api';
import { FailedInvoiceDetails, Invoice } from '@/types';
import { ArrowLeft, CheckCircle, XCircle, Edit3, MessageCircle, Upload, AlertTriangle, FileText, X, Clock, ExternalLink, BookOpen, AlertCircle, Info } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import AIAssistantPanel from '@/components/AIAssistantPanel';
import vkbeautify from "vkbeautify";

// Helper function to normalize processing steps from API response
// The API returns each processing step as a flat object with error details embedded
// We need to transform this into the expected ProcessingStepResult structure
const normalizeProcessingSteps = (rawSteps: any[] | undefined): any[] => {
  if (!rawSteps || !Array.isArray(rawSteps)) {
    return [];
  }

  return rawSteps.map((step) => {
    // If the step already has the correct structure, return it as is
    if (step.step_name !== undefined && step.step_number !== undefined) {
      return step;
    }

    // Otherwise, transform the flat error structure into step format
    // Extract step_number from error_context if available
    const stepNumber = step.error_context?.step_number || 2; // Default to 2 if not found
    const stepName = step.error_context?.step_name || "Unknown Step";

    // Convert this single error into an error_details array
    const errorDetail: any = {
      error_code: step.error_context?.error_code || step.error_code || "UNKNOWN",
      error_category: step.error_context?.error_category || "UNKNOWN",
      error_message: step.error_context?.error_message || step.user_message || "Unknown error",
      severity: step.error_context?.severity || "ERROR",
      user_message: step.user_message || step.error_context?.error_message || "Unknown error",
      technical_details: step.technical_details || step.error_context?.error_message || "No details available",
      suggested_actions: step.suggested_actions || [],
      file_name: step.error_context?.file_name,
      timestamp: step.error_context?.timestamp,
      additional_context: step.error_context?.additional_context || step.error_context,
      documentation_links: step.documentation_links || [],
      is_recoverable: step.is_recoverable !== undefined ? step.is_recoverable : true,
      estimated_fix_time: step.estimated_fix_time,
    };

    return {
      step_name: stepName,
      step_number: stepNumber,
      success: false,
      message: step.user_message,
      error_details: [errorDetail],
      duration_seconds: step.error_context?.duration_seconds,
    };
  });
};

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
  var filename = '';
  console.log(invoice);
  console.log("INVOCIE SHOULD BE PRINTED");
  // try
  // {
  //   alert(invoice.xml_content);
  // }
  // catch
  // {
  //   alert("JAPANIU");
  // }
  const [xmlContent, setXmlContent] = useState("");
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const invoiceId = params.id as string;
  const shouldShowAI = searchParams.get('ai') === 'true';
  const handleEditToggle = () => {
    setIsEditing((prev) => !prev);
  };
  useEffect(() => {
    if (invoice?.xml_content) {
      setXmlContent(invoice.xml_content);
    }
  }, [invoice]);
  // Toggle edit/view mode


  // Beautify / pretty print XML
  const handleBeautify = () => {
    try {
      const formatted = new DOMParser()
        .parseFromString(xmlContent, "application/xml");
      const serializer = new XMLSerializer();
      const pretty = vkbeautify.xml(serializer.serializeToString(formatted));
      setXmlContent(pretty);
    } catch (e) {
      alert("⚠️ Invalid XML, cannot beautify.");
    }
  };

  const highlightXml = (xml: any) => {
    if (!xml) return "";
    return xml
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(
        /(&lt;\/?)([\w:-]+)(.*?)(\/?&gt;)/g,
        (_: any, open: any, tag: any, attrs: any, close: any) =>
          `${open}<span class='text-blue-600 font-semibold'>${tag}</span>${attrs}${close}`
      )
      .replace(
        /([\w:-]+)="(.*?)"/g,
        `<span class='text-purple-600'>$1</span>=<span class='text-green-600'>"${"$2"}</span>"`
      );
  };

  // Optional: Minify XML
  const handleMinify = () => {
    const minified = xmlContent
      .replace(/>\s+</g, "><")
      .replace(/\n/g, "")
      .trim();
    setXmlContent(minified);
  };

  // Save XML to backend file system
  const handleSave = async () => {
    if (!invoice || !xmlContent) {
      alert("No invoice or XML content to save");
      return;
    }

    try {
      setIsSaving(true);
      setSaveSuccess(false);
      setError(null);

      console.log("Saving edited XML to backend...", xmlContent.length, "characters");
      
      const originalFilename = invoice.xml_path?.split('/').pop() || 'edited_invoice.xml';
      const xmlBlob = new Blob([xmlContent], { type: 'text/xml' });
      
      const formData = new FormData();
      formData.append("file", xmlBlob, originalFilename);

      console.log('Sending save request to:', `/api/v1/invoices/${invoice.tracking_id}/save-xml`);
      const response = await api.post(`/api/v1/invoices/${invoice.tracking_id}/save-xml`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });
      
      console.log("Save response:", response.data);
      
      if (response.data.success) {
        setIsEditing(false);
        setSaveSuccess(true);
        
        setTimeout(() => setSaveSuccess(false), 3000);
        console.log("XML file saved successfully to backend");
      }
      
      setIsSaving(false);
    } catch (error: any) {
      console.error("Error saving XML:", error);
      setError(error.response?.data?.detail || error.message || "Failed to save the file");
      setIsSaving(false);
    }
  };
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
      // If using new processing_steps structure
      if (invoice.processing_steps && invoice.processing_steps.length > 0) {
        const firstFailedStep = invoice.processing_steps.find(
          step => !step.success && step.error_details && step.error_details.length > 0
        );
        if (firstFailedStep) {
          const stepKey = `step-${firstFailedStep.step_number}`;
          setSelectedErrorStep(stepKey);
          setShowDetailedError(stepKey);
        }
      } else {
        // Fallback to old structure
        if (!invoice.xml_validation_pass) {
          setSelectedErrorStep('xml');
          setShowDetailedError('xml');
        } else if (!invoice.edi_convert_pass) {
          setSelectedErrorStep('edi');
          setShowDetailedError('edi');
          setActiveTab('errors');
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
        console.log('🔍 Failed Invoice Page - Raw processing_steps:', invoiceData.processing_steps);
        console.log('🔍 Failed Invoice Page - Raw processing_steps_error:', invoiceData.processing_steps_error);
        console.log('🔍 Failed Invoice Page - Raw response keys:', Object.keys(invoiceData));
        console.log('🔍 Failed Invoice Page - XML content length:', invoiceData.xml_content?.length || 0);
        console.log('🔍 Failed Invoice Page - EDI content length:', invoiceData.edi_content?.length || 0);

        // Convert API response to FailedInvoiceDetails format
        // Prioritize blob URLs when available, fall back to local paths
        const xmlPath = invoiceData.blob_xml_path || invoiceData.xml_path;
        const ediPath = invoiceData.blob_edi_path || invoiceData.edi_path;

        console.log('🔍 Failed Invoice Page - Path resolution:', {
          blob_xml_path: invoiceData.blob_xml_path,
          xml_path: invoiceData.xml_path,
          final_xml_path: xmlPath,
          blob_edi_path: invoiceData.blob_edi_path,
          edi_path: invoiceData.edi_path,
          final_edi_path: ediPath,
          use_blob_storage: invoiceData.use_blob_storage
        });

        const failedDetails: FailedInvoiceDetails = {
          id: invoiceData.id,
          tracking_id: invoiceData.tracking_id,
          user_id: invoiceData.user_id,
          uploaded_at: invoiceData.uploaded_at,
          xml_path: xmlPath,
          xml_validation_pass: invoiceData.xml_validation_pass,
          xml_convert_message: invoiceData.xml_convert_message,
          xml_content: invoiceData.xml_content,
          edi_path: ediPath,
          edi_convert_pass: invoiceData.edi_convert_pass,
          edi_convert_message: invoiceData.edi_convert_message,
          edi_content: invoiceData.edi_content,
          processing_steps: normalizeProcessingSteps(invoiceData.processing_steps), // Normalize API response
          processing_steps_error: invoiceData.processing_steps_error, // Keep for backward compatibility
        };

        console.log('🔍 Failed Invoice Page - Final invoice details:', failedDetails);
        console.log('🔍 Failed Invoice Page - Processing steps error:', failedDetails.processing_steps_error);
        console.log('🔍 Failed Invoice Page - Final XML content length:', failedDetails.xml_content?.length || 0);
        console.log('🔍 Failed Invoice Page - Final EDI content length:', failedDetails.edi_content?.length || 0);
        console.log('🔍 Failed Invoice Page - Normalized processing steps:', JSON.stringify(failedDetails.processing_steps, null, 2));
        filename = invoiceData.filename;

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

        // If we have a tracking_id, fetch full details using the tracking ID endpoint
        // This ensures we get processing_steps and all other detailed information
        if (invoiceData.tracking_id) {
          try {
            console.log('🔍 Failed Invoice Page - Fetching full details by tracking ID:', invoiceData.tracking_id);
            const fullInvoiceData = await fileApi.getFailedInvoiceByTrackingId(invoiceData.tracking_id);
            
            // Convert API response to FailedInvoiceDetails format
            const xmlPath = fullInvoiceData.blob_xml_path || fullInvoiceData.xml_path;
            const ediPath = fullInvoiceData.blob_edi_path || fullInvoiceData.edi_path;

            const failedDetails: FailedInvoiceDetails = {
              id: fullInvoiceData.id,
              tracking_id: fullInvoiceData.tracking_id,
              user_id: fullInvoiceData.user_id,
              uploaded_at: fullInvoiceData.uploaded_at,
              xml_path: xmlPath,
              xml_validation_pass: fullInvoiceData.xml_validation_pass,
              xml_convert_message: fullInvoiceData.xml_convert_message,
              xml_content: fullInvoiceData.xml_content,
              edi_path: ediPath,
              edi_convert_pass: fullInvoiceData.edi_convert_pass,
              edi_convert_message: fullInvoiceData.edi_convert_message,
              edi_content: fullInvoiceData.edi_content,
              processing_steps: normalizeProcessingSteps(fullInvoiceData.processing_steps),
              processing_steps_error: fullInvoiceData.processing_steps_error,
            };

            console.log('🔍 Failed Invoice Page - Full details fetched by tracking ID:', failedDetails);
            console.log('🔍 Failed Invoice Page - Processing steps count:', failedDetails.processing_steps?.length || 0);
            console.log('🔍 Failed Invoice Page - Processing steps:', JSON.stringify(failedDetails.processing_steps, null, 2));
            setInvoice(failedDetails);
            return;
          } catch (trackingError: any) {
            console.warn('🔍 Failed Invoice Page - Could not fetch by tracking ID, falling back to basic data:', trackingError);
            // Fall through to use basic invoice data
          }
        }

        // Fallback: Convert Invoice to FailedInvoiceDetails format (without full details)
        const xmlPath = invoiceData.blob_xml_path || invoiceData.xml_path;
        const ediPath = invoiceData.blob_edi_path || invoiceData.edi_path;

        const failedDetails: FailedInvoiceDetails = {
          id: typeof invoiceData.id === 'number' ? invoiceData.id : parseInt(invoiceData.id.toString()),
          tracking_id: invoiceData.tracking_id || 'unknown',
          user_id: user?.id || 0,
          uploaded_at: invoiceData.uploaded_at || new Date().toISOString(),
          xml_path: xmlPath || `uploads/${invoiceData.tracking_id}_${invoiceData.filename}`,
          xml_validation_pass: invoiceData.xml_validation_pass || false,
          xml_convert_message: invoiceData.xml_convert_message,
          edi_path: ediPath || `converted/${invoiceData.tracking_id}_converted.edi`,
          edi_convert_pass: invoiceData.edi_convert_pass || false,
          edi_convert_message: invoiceData.edi_convert_message,
          processing_steps: normalizeProcessingSteps(invoiceData.processing_steps), // Normalize if available
          processing_steps_error: invoiceData.processing_steps_error,
          xml_content: invoiceData.xml_content,
          edi_content: invoiceData.edi_content,
        };

        console.log('🔍 Failed Invoice Page - Final invoice details (numeric ID, fallback):', failedDetails);
        console.log('🔍 Failed Invoice Page - Processing steps (numeric ID):', failedDetails.processing_steps);

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

                {/* Use processing_steps from API if available, otherwise fallback to old structure */}
                {invoice.processing_steps && invoice.processing_steps.length > 0 ? (
                  <div className="px-4 pb-4 space-y-4">
                    {invoice.processing_steps.map((step, stepIndex) => {
                      const hasErrors = step.error_details && step.error_details.length > 0;
                      const isSelected = selectedErrorStep === `step-${step.step_number}`;
                      const stepKey = `step-${step.step_number}`;
                      
                      return (
                        <div
                          key={stepIndex}
                          className={cn(
                            "border rounded-lg p-4 transition-all",
                            !step.success && hasErrors
                              ? isSelected
                                ? "border-red-500 bg-red-50 shadow-md"
                                : "border-red-200 bg-red-50/50 hover:border-red-300 cursor-pointer"
                              : step.success
                                ? "border-green-200 bg-green-50/30"
                                : "border-gray-200 bg-gray-50"
                          )}
                          onClick={() => {
                            if (!step.success && hasErrors) {
                              setSelectedErrorStep(isSelected ? null : stepKey);
                              setShowDetailedError(isSelected ? null : stepKey);
                            }
                          }}
                        >
                          <div className="flex items-start justify-between">
                            <div className="flex items-start space-x-3 flex-1">
                              {/* Step Icon */}
                              <div className={cn(
                                "w-10 h-10 rounded-full flex items-center justify-center border-2 flex-shrink-0",
                                step.success
                                  ? "bg-green-100 border-green-500 text-green-700"
                                  : hasErrors
                                    ? isSelected
                                      ? "bg-red-100 border-red-500 text-red-700"
                                      : "bg-red-50 border-red-300 text-red-600"
                                    : "bg-gray-100 border-gray-300 text-gray-600"
                              )}>
                                {step.success ? (
                                  <CheckCircle className="h-5 w-5" />
                                ) : hasErrors ? (
                                  <XCircle className="h-5 w-5" />
                                ) : (
                                  <AlertCircle className="h-5 w-5" />
                                )}
                              </div>

                              {/* Step Content */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center space-x-2 mb-1">
                                  <h3 className="text-sm font-semibold text-gray-900">
                                    {step.step_number}. {step.step_name}
                                  </h3>
                                  <span className={cn(
                                    "px-2 py-0.5 rounded-full text-xs font-medium",
                                    step.success
                                      ? "bg-green-100 text-green-800"
                                      : hasErrors
                                        ? "bg-red-100 text-red-800"
                                        : "bg-gray-100 text-gray-600"
                                  )}>
                                    {step.success ? 'Passed' : hasErrors ? 'Failed' : 'Skipped'}
                                  </span>
                                  {step.duration_seconds !== undefined && (
                                    <span className="text-xs text-gray-500 flex items-center">
                                      <Clock className="h-3 w-3 mr-1" />
                                      {step.duration_seconds.toFixed(2)}s
                                    </span>
                                  )}
                                </div>
                                
                                {step.message && (
                                  <p className="text-sm text-gray-600 mb-2">{step.message}</p>
                                )}

                                {/* Error Count Badge */}
                                {hasErrors && (
                                  <div className="mt-2">
                                    <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-red-100 text-red-800">
                                      <AlertTriangle className="h-3 w-3 mr-1" />
                                      {step.error_details!.length} {step.error_details!.length === 1 ? 'Error' : 'Errors'}
                                    </span>
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Expanded Error Details */}
                          {isSelected && hasErrors && step.error_details && (
                            <div className="mt-4 pt-4 border-t border-red-200 space-y-3">
                              {step.error_details.map((error, errorIndex) => (
                                <div
                                  key={errorIndex}
                                  className={cn(
                                    "bg-white border rounded-lg p-4",
                                    error.severity === 'CRITICAL'
                                      ? "border-red-300 bg-red-50/50"
                                      : error.severity === 'ERROR'
                                        ? "border-orange-300 bg-orange-50/50"
                                        : "border-yellow-300 bg-yellow-50/50"
                                  )}
                                >
                                  {/* Error Header */}
                                  <div className="flex items-start justify-between mb-3">
                                    <div className="flex items-start space-x-2 flex-1">
                                      <div className={cn(
                                        "px-2 py-1 rounded text-xs font-mono font-semibold",
                                        error.severity === 'CRITICAL'
                                          ? "bg-red-200 text-red-900"
                                          : error.severity === 'ERROR'
                                            ? "bg-orange-200 text-orange-900"
                                            : "bg-yellow-200 text-yellow-900"
                                      )}>
                                        {error.error_code}
                                      </div>
                                      <span className={cn(
                                        "px-2 py-1 rounded text-xs font-medium",
                                        error.severity === 'CRITICAL'
                                          ? "bg-red-100 text-red-800"
                                          : error.severity === 'ERROR'
                                            ? "bg-orange-100 text-orange-800"
                                            : "bg-yellow-100 text-yellow-800"
                                      )}>
                                        {error.severity}
                                      </span>
                                      <span className="px-2 py-1 rounded text-xs font-medium bg-gray-100 text-gray-700">
                                        {error.error_category.replace(/_/g, ' ')}
                                      </span>
                                    </div>
                                  </div>

                                  {/* User-Friendly Message */}
                                  <div className="mb-3">
                                    <h4 className="text-sm font-semibold text-gray-900 mb-1 flex items-center">
                                      <Info className="h-4 w-4 mr-1.5 text-blue-600" />
                                      What went wrong?
                                    </h4>
                                    <p className="text-sm text-gray-700 leading-relaxed">{error.user_message}</p>
                                  </div>

                                  {/* Technical Details */}
                                  <div className="mb-3">
                                    <h4 className="text-xs font-semibold text-gray-700 mb-1">Technical Details:</h4>
                                    <p className="text-xs text-gray-600 leading-relaxed font-mono bg-gray-50 p-2 rounded border">
                                      {error.technical_details}
                                    </p>
                                  </div>

                                  {/* Suggested Actions */}
                                  {error.suggested_actions && error.suggested_actions.length > 0 && (
                                    <div className="mb-3">
                                      <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center">
                                        <AlertCircle className="h-4 w-4 mr-1.5 text-blue-600" />
                                        Suggested Actions:
                                      </h4>
                                      <ul className="space-y-1.5">
                                        {error.suggested_actions.map((action, actionIndex) => (
                                          <li key={actionIndex} className="flex items-start text-xs text-gray-700">
                                            <span className="text-blue-600 font-semibold mr-2 mt-0.5">
                                              {actionIndex + 1}.
                                            </span>
                                            <span className="flex-1">{action}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}

                                  {/* Additional Info */}
                                  <div className="flex flex-wrap items-center gap-3 mt-3 pt-3 border-t border-gray-200">
                                    {error.is_recoverable !== undefined && (
                                      <div className="flex items-center text-xs">
                                        <span className={cn(
                                          "px-2 py-1 rounded font-medium",
                                          error.is_recoverable
                                            ? "bg-green-100 text-green-800"
                                            : "bg-gray-100 text-gray-600"
                                        )}>
                                          {error.is_recoverable ? '✓ Recoverable' : '✗ Not Recoverable'}
                                        </span>
                                      </div>
                                    )}
                                    {error.estimated_fix_time && (
                                      <div className="flex items-center text-xs text-gray-600">
                                        <Clock className="h-3 w-3 mr-1" />
                                        Est. fix time: {error.estimated_fix_time}
                                      </div>
                                    )}
                                  </div>

                                  {/* Documentation Links */}
                                  {error.documentation_links && error.documentation_links.length > 0 && (
                                    <div className="mt-3 pt-3 border-t border-gray-200">
                                      <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center">
                                        <BookOpen className="h-4 w-4 mr-1.5 text-blue-600" />
                                        Documentation:
                                      </h4>
                                      <div className="flex flex-wrap gap-2">
                                        {error.documentation_links.map((link, linkIndex) => (
                                          <a
                                            key={linkIndex}
                                            href={link}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-50 text-blue-700 hover:bg-blue-100 transition-colors"
                                          >
                                            <ExternalLink className="h-3 w-3 mr-1" />
                                            Learn More
                                          </a>
                                        ))}
                                      </div>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  /* Fallback to old structure if processing_steps not available */
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
                            if (invoice.xml_validation_pass && !invoice.edi_convert_pass) {
                              setSelectedErrorStep(selectedErrorStep === 'edi' ? null : 'edi');
                              setShowDetailedError(selectedErrorStep === 'edi' ? null : 'edi');
                            }
                          }}
                          className={cn(
                            "w-10 h-10 rounded-full flex items-center justify-center border-4 transition-all",
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

                      {/* Connecting Line */}
                      <div className="flex-1 h-0.5 bg-gray-300 mx-4 relative">
                        <div className={cn(
                          "absolute top-0 left-0 h-full transition-all duration-500",
                          "bg-gray-300 w-0"
                        )}></div>
                      </div>

                      {/* Step 5: 3rd Party Endpoint */}
                      <div className="flex flex-col items-center relative z-10">
                        <button
                          className={cn(
                            "w-10 h-10 rounded-full flex items-center justify-center border-4 transition-all",
                            "bg-gray-300 border-gray-300 text-gray-500 cursor-not-allowed"
                          )}
                        >
                          <XCircle className="h-5 w-5" />
                        </button>
                        <div className="mt-2 text-center">
                          <h3 className={cn(
                            "text-xs font-medium text-gray-500"
                          )}>3rd Party Endpoint</h3>
                          <span className={cn(
                            "inline-block px-2 py-1 rounded-full text-xs font-medium mt-1",
                            "bg-gray-100 text-gray-500"
                          )}>
                            Skipped
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Detailed Error Display - Only show for old structure (xml/edi) */}
              {showDetailedError && (showDetailedError === 'xml' || showDetailedError === 'edi') && (
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

                      {/* File Content Preview - Fallback if xml_content is not available */}
                      {!invoice.xml_validation_pass && !invoice.xml_content && invoice.file_content_preview && (
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
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'xml'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                      }`}
                                  >
                                    Original XML
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('edi')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'edi'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                      }`}
                                  >
                                    Generated EDI
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('errors')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'errors'
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
                                        {invoice.xml_path?.startsWith('http') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                            🌐 Blob Storage
                                          </span>
                                        )}
                                        {invoice.xml_path?.startsWith('uploads') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                                            📁 Local Storage
                                          </span>
                                        )}
                                      </div>
                                      <div className="bg-white border border-gray-200 rounded-lg p-3 max-h-96 overflow-auto transition-all duration-300 shadow-sm">
                                        <div className="flex justify-between items-center mb-2">
                                          <span className="font-semibold text-blue-700">XML Content</span>
                                          <div className="flex space-x-2">
                                            {/* Only show Edit button if XML validation failed */}
                                            {!invoice.xml_validation_pass && (
                                              <button
                                                onClick={() => setIsEditing(!isEditing)}
                                                className="text-blue-600 hover:underline text-xs"
                                              >
                                                {isEditing ? "🔒 View" : "✏️ Edit"}
                                              </button>
                                            )}
                                            <button
                                              onClick={handleBeautify}
                                              disabled={!xmlContent}
                                              className="text-purple-600 hover:underline text-xs"
                                            >
                                              🪄 Pretty Print
                                            </button>
                                            <button
                                              onClick={handleMinify}
                                              disabled={!xmlContent}
                                              className="text-orange-600 hover:underline text-xs"
                                            >
                                              🗜 Minify
                                            </button>
                                            {isEditing && !invoice.xml_validation_pass && (
                                              <>
                                                <button
                                                  onClick={handleSave}
                                                  className="text-green-600 hover:underline text-xs"
                                                >
                                                  💾 Save
                                                </button>
                                                <button
                                                  onClick={() => {
                                                    setXmlContent(invoice?.xml_content || "");
                                                    setIsEditing(false);
                                                  }}
                                                  className="text-gray-600 hover:underline text-xs"
                                                >
                                                  ❌ Cancel
                                                </button>
                                              </>
                                            )}
                                          </div>
                                        </div>

                                        {/* ✅ View Mode */}
                                        {!isEditing || invoice.xml_validation_pass ? (
                                          <pre
                                            className="whitespace-pre-wrap text-xs font-mono bg-gray-50 p-2 rounded overflow-x-auto border border-gray-100"
                                            dangerouslySetInnerHTML={{
                                              __html: highlightXml(xmlContent || ""),
                                            }}
                                          />
                                        ) : (
                                          <textarea
                                            value={xmlContent}
                                            onChange={(e) => setXmlContent(e.target.value)}
                                            className="w-full h-72 border rounded p-2 bg-white text-sm resize-vertical focus:ring-2 focus:ring-blue-400 font-mono"
                                          />
                                        )}

                                        <div className="mt-2 text-xs">
                                          {xmlContent ? (
                                            <span className="text-green-600">
                                              ✅ XML loaded ({xmlContent.length} characters)
                                            </span>
                                          ) : (
                                            <span className="text-red-600">❌ XML not available</span>
                                          )}
                                        </div>
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
                                        {invoice.edi_path?.startsWith('http') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                            🌐 Blob Storage
                                          </span>
                                        )}
                                        {invoice.edi_path?.startsWith('converted') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                                            📁 Local Storage
                                          </span>
                                        )}
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
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'errors'
                                        ? 'border-blue-500 text-blue-600'
                                        : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                                      }`}
                                  >
                                    Error Details
                                  </button>
                                  <button
                                    onClick={() => setActiveTab('xml')}
                                    className={`py-2 px-1 border-b-2 font-medium text-sm ${activeTab === 'xml'
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
                                        {invoice.xml_path?.startsWith('http') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                                            🌐 Blob Storage
                                          </span>
                                        )}
                                        {invoice.xml_path?.startsWith('uploads') && (
                                          <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                                            📁 Local Storage
                                          </span>
                                        )}
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

              {/* XML Editor - Always show when XML validation fails */}
              {!invoice.xml_validation_pass && invoice.xml_content && (
                <div className="bg-white rounded-lg shadow border border-gray-200 p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-4">📝 Edit XML File</h2>
                  
                  <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-4">
                    <div className="text-sm text-gray-600 mb-3">
                      <span className="font-medium">File:</span> {invoice.xml_path}
                      {invoice.xml_path?.startsWith('http') && (
                        <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-blue-100 text-blue-800">
                          🌐 Blob Storage
                        </span>
                      )}
                      {invoice.xml_path?.startsWith('uploads') && (
                        <span className="ml-2 inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
                          📁 Local Storage
                        </span>
                      )}
                    </div>

                    {/* Success Message */}
                    {saveSuccess && (
                      <div className="mb-3 p-3 bg-green-100 border border-green-300 rounded-lg flex items-center space-x-2">
                        <CheckCircle className="h-5 w-5 text-green-700" />
                        <span className="text-sm font-medium text-green-800">✅ File saved and reprocessed successfully!</span>
                      </div>
                    )}

                    {/* XML Editor Controls */}
                    <div className="bg-white border border-gray-200 rounded-lg p-4">
                      <div className="flex justify-between items-center mb-3 pb-3 border-b border-gray-200">
                        <span className="font-semibold text-blue-700 flex items-center">
                          <FileText className="h-4 w-4 mr-2" />
                          XML Content ({xmlContent.length} characters)
                        </span>
                        <div className="flex space-x-2 flex-wrap gap-2">
                          <button
                            onClick={() => setIsEditing(!isEditing)}
                            disabled={isSaving}
                            className={`text-sm px-3 py-1 rounded transition-colors ${
                              isEditing
                                ? "bg-blue-100 text-blue-700 hover:bg-blue-200"
                                : "text-blue-600 hover:text-blue-800"
                            } disabled:opacity-50 disabled:cursor-not-allowed`}
                          >
                            {isEditing ? "🔒 View Mode" : "✏️ Edit Mode"}
                          </button>
                          <button
                            onClick={handleBeautify}
                            disabled={!xmlContent || !isEditing}
                            className="text-sm px-3 py-1 rounded text-purple-600 hover:text-purple-800 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            🪄 Pretty Print
                          </button>
                          <button
                            onClick={handleMinify}
                            disabled={!xmlContent || !isEditing}
                            className="text-sm px-3 py-1 rounded text-orange-600 hover:text-orange-800 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            🗜️ Minify
                          </button>
                        </div>
                      </div>

                      {/* View Mode - Full Content Display */}
                      {!isEditing ? (
                        <div className="space-y-3">
                          <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 font-mono text-xs overflow-auto" style={{ maxHeight: '600px' }}>
                            <pre
                              className="whitespace-pre-wrap break-words text-gray-800"
                              dangerouslySetInnerHTML={{
                                __html: highlightXml(xmlContent || ""),
                              }}
                            />
                          </div>
                        </div>
                      ) : (
                        /* Edit Mode - Textarea with Full Content */
                        <div className="space-y-3">
                          <textarea
                            value={xmlContent}
                            onChange={(e) => setXmlContent(e.target.value)}
                            className="w-full border rounded p-3 bg-white text-sm resize-vertical focus:ring-2 focus:ring-blue-400 focus:border-transparent font-mono"
                            style={{ minHeight: '600px', maxHeight: '800px' }}
                            placeholder="Paste your XML content here..."
                          />
                          <div className="flex justify-end space-x-2">
                            <button
                              onClick={() => {
                                setXmlContent(invoice?.xml_content || "");
                                setIsEditing(false);
                              }}
                              disabled={isSaving}
                              className="px-4 py-2 bg-gray-300 text-gray-800 rounded-md hover:bg-gray-400 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              ❌ Cancel
                            </button>
                            <button
                              onClick={handleSave}
                              disabled={isSaving || !xmlContent}
                              className={`px-4 py-2 rounded-md font-medium transition-colors flex items-center space-x-2 ${
                                isSaving
                                  ? "bg-gray-300 text-gray-600 cursor-not-allowed"
                                  : "bg-green-600 text-white hover:bg-green-700"
                              }`}
                            >
                              {isSaving ? (
                                <>
                                  <div className="animate-spin rounded-full h-4 w-4 border-2 border-white border-t-transparent"></div>
                                  <span>Saving...</span>
                                </>
                              ) : (
                                <>
                                  <span>💾 Save</span>
                                </>
                              )}
                            </button>
                          </div>
                        </div>
                      )}

                      {/* Info Footer */}
                      <div className="mt-3 pt-3 border-t border-gray-200 flex justify-between items-center text-xs text-gray-600">
                        <div>
                          {xmlContent ? (
                            <span>
                              Total content: <span className="font-mono font-semibold">{xmlContent.length}</span> characters
                            </span>
                          ) : (
                            <span className="text-red-600">❌ No XML content available</span>
                          )}
                        </div>
                        {isEditing && (
                          <div className="text-blue-600 font-medium">
                            Editing mode enabled - Make your changes and click "Save"
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
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