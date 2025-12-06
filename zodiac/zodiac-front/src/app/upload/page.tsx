'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Upload, FileText, CheckCircle, XCircle, ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import LoadingSpinner from '@/components/LoadingSpinner';
import ProcessingStatusTracker from '@/components/ProcessingStatusTracker';

export default function UploadPage() {
    const router = useRouter();
    const { user } = useAuth();
    const [uploading, setUploading] = useState(false);
    const [uploadError, setUploadError] = useState('');
    const [uploadSuccess, setUploadSuccess] = useState('');
    const [trackingId, setTrackingId] = useState<string | null>(null);
    const [showStatusTracker, setShowStatusTracker] = useState(false);
    const [dragActive, setDragActive] = useState(false);
    const [isReprocessing, setIsReprocessing] = useState(false);

    // Check URL parameters for reprocessing
    useEffect(() => {
        if (typeof window !== 'undefined') {
            const urlParams = new URLSearchParams(window.location.search);
            const urlTrackingId = urlParams.get('trackingId');
            const isReprocess = urlParams.get('reprocess') === 'true';
            const source = urlParams.get('source');

            if (urlTrackingId && isReprocess) {
                console.log('🔄 Upload Page - Reprocessing mode detected:', {
                    trackingId: urlTrackingId,
                    source: source
                });

                setTrackingId(urlTrackingId);
                setShowStatusTracker(true);
                setIsReprocessing(true);
                setUploadSuccess('Reprocessing your edited invoice...');
            }
        }
    }, []);

    const handleFileUpload = async (file: File) => {
        console.log('📤 Upload Page - File upload started:', {
            fileName: file.name,
            fileSize: file.size,
            fileType: file.type,
            lastModified: new Date(file.lastModified).toISOString(),
            fileConstructor: file.constructor.name,
            fileIsFile: file instanceof File
        });

        setUploading(true);
        setUploadError('');
        setUploadSuccess('');

        try {
            // Client-side validation
            const allowedTypes = ['.edi', '.xml', '.txt', '.x12'];
            const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();

            console.log('📤 Upload Page - File validation:', {
                fileName: file.name,
                fileExtension,
                allowedTypes,
                isValidExtension: allowedTypes.includes(fileExtension),
                fileSize: file.size,
                maxSize: 10 * 1024 * 1024,
                isValidSize: file.size <= 10 * 1024 * 1024
            });

            if (!allowedTypes.includes(fileExtension)) {
                setUploadError('Please upload EDI, XML, TXT, or X12 files only.');
                return;
            }

            if (file.size > 10 * 1024 * 1024) {
                setUploadError('File size must be less than 10MB.');
                return;
            }

            console.log('📤 Upload Page - Calling fileApi.uploadFile...');
            const result = await fileApi.uploadFile(file);
            console.log('📤 Upload Page - Upload result:', JSON.stringify(result, null, 2));

            // Extract tracking ID from response (InvoiceProcessingResponse format)
            // The response.data is InvoiceProcessingResponse with tracking_id directly
            const responseData = result.data;
            const resultTrackingId = responseData?.tracking_id;
            const responseStatus = (result as any).status;

            console.log('📤 Upload Page - Full result object:', result);
            console.log('📤 Upload Page - Response data:', responseData);
            console.log('📤 Upload Page - Response data type:', typeof responseData);
            console.log('📤 Upload Page - Response data keys:', responseData ? Object.keys(responseData) : 'null');
            console.log('📤 Upload Page - Extracted tracking ID:', resultTrackingId);
            console.log('📤 Upload Page - Response status:', responseStatus);
            console.log('📤 Upload Page - Result success:', result.success);

            // Check if we have a 202 response or tracking_id
            const is202Response = responseStatus === 202;

            if (result.success && (is202Response || resultTrackingId)) {
                // 202 Accepted means processing started, or we have a tracking_id
                if (resultTrackingId) {
                    console.log('✅ Upload Page - Setting up status tracker with tracking ID:', resultTrackingId);
                    setTrackingId(resultTrackingId);
                    setShowStatusTracker(true);
                    setUploading(false); // Stop showing upload spinner, show status tracker instead
                    // Don't return here - let the rest of the code handle success message
                } else if (is202Response) {
                    console.warn('⚠️ Upload Page - 202 response but no tracking ID found in expected location');
                    console.warn('⚠️ Upload Page - Attempting alternative extraction methods...');
                    // Try alternative extraction methods
                    const altTrackingId = (responseData as any)?.tracking_id ||
                        (result as any)?.tracking_id;
                    if (altTrackingId) {
                        console.log('✅ Upload Page - Found tracking ID via alternative method:', altTrackingId);
                        setTrackingId(altTrackingId);
                        setShowStatusTracker(true);
                        setUploading(false);
                    } else {
                        console.error('❌ Upload Page - 202 response but could not extract tracking_id');
                        console.error('❌ Upload Page - Response data structure:', JSON.stringify(responseData, null, 2));
                        setUploadError('Processing started but tracking ID not found. Please check the console for details.');
                        setUploading(false);
                        return;
                    }
                }

                // Processing started - status tracker will show progress
                console.log('📤 Upload Page - Processing started, showing status tracker');
            } else {
                // Handle error responses
                if (result.isProcessingError) {
                    // File upload succeeded but processing failed
                    // Show status tracker to see what failed - no redirect, user can see details
                    if (!resultTrackingId) {
                        console.error('📤 Upload Page - No tracking ID found in processing error data');
                        setUploadError('Processing failed but unable to locate invoice details. Please check your invoices list.');
                        setTimeout(() => setUploadError(''), 10000);
                    }
                } else {
                    // Handle actual upload failures
                    let errorMessage = result.error || 'Upload failed. Please try again.';

                    // If we have structured error data, provide more specific feedback
                    if (result.data) {
                        const errorData = result.data;
                        console.log('📤 Upload Page - Structured error data:', errorData);

                        // Use enhanced error information if available
                        if (result.errorDetails && result.errorDetails.length > 0) {
                            console.log('📤 Upload Page - Enhanced error details available:', result.errorDetails);

                            // Create detailed error message with suggestions
                            const errorDetails = result.errorDetails.map((detail: any) => {
                                let detailMessage = `${detail.step}: ${detail.error_message}`;
                                if (detail.suggestions && detail.suggestions.length > 0) {
                                    detailMessage += `\nSuggestions: ${detail.suggestions.join(', ')}`;
                                }
                                return detailMessage;
                            }).join('\n\n');

                            errorMessage = `Upload failed with the following issues:\n\n${errorDetails}`;

                            // If there are suggested actions, add them
                            if (result.suggestedActions && result.suggestedActions.length > 0) {
                                errorMessage += `\n\nRecommended actions:\n${result.suggestedActions.map((action: string, index: number) => `${index + 1}. ${action}`).join('\n')}`;
                            }
                        } else {
                            // Fallback to basic error data parsing
                            if (!errorData.file_upload_pass) {
                                errorMessage = `File upload failed: ${errorData.file_upload_message || 'Unknown error'}`;
                            } else if (!errorData.xml_validation_pass) {
                                errorMessage = `XML validation failed: ${errorData.xml_convert_message || 'Invalid XML format'}`;
                                // Add helpful suggestions for XML validation errors
                                if (errorData.xml_convert_message?.includes('Missing required elements')) {
                                    errorMessage += '\n\nPlease ensure your XML file contains all required elements: InvoiceNumber, InvoiceDate, and TotalAmount.';
                                }
                            } else if (!errorData.edi_convert_pass) {
                                errorMessage = `EDI conversion failed: ${errorData.edi_convert_message || 'Conversion error'}`;
                            }
                        }
                    }

                    console.log('📤 Upload Page - Final error message:', errorMessage);
                    setUploadError(errorMessage);
                    setTimeout(() => setUploadError(''), 15000); // Show error for 15 seconds
                }
            }
        } catch (error: any) {
            console.error('📤 Upload Page - Upload error:', error);
            console.error('📤 Upload Page - Error type:', typeof error);
            console.error('📤 Upload Page - Error constructor:', error?.constructor?.name);
            console.error('📤 Upload Page - Error is Error:', error instanceof Error);
            setUploadError('Upload failed. Please try again.');
            setTimeout(() => setUploadError(''), 10000);
            setUploading(false);
        }
        // Don't reset uploading in finally if we're showing status tracker
        // The status tracker will handle its own state
    };

    const handleDrag = (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        if (e.type === "dragenter" || e.type === "dragover") {
            setDragActive(true);
        } else if (e.type === "dragleave") {
            setDragActive(false);
        }
    };

    const handleDrop = async (e: React.DragEvent) => {
        e.preventDefault();
        e.stopPropagation();
        setDragActive(false);

        if (e.dataTransfer.files && e.dataTransfer.files[0]) {
            await handleFileUpload(e.dataTransfer.files[0]);
        }
    };

    const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        e.preventDefault();
        if (e.target.files && e.target.files[0]) {
            await handleFileUpload(e.target.files[0]);
        }
    };

    const topSectionActions = (
        <button
            onClick={() => router.push('/invoices')}
            className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors"
        >
            <ArrowLeft className="h-4 w-4" />
            <span>Back to Documents</span>
        </button>
    );

    return (
        <MainLayout
            topSection={
                <TopSection
                    title={isReprocessing ? "Reprocessing Invoice" : "Upload Document"}
                    subtitle={isReprocessing ? "Processing your edited invoice file" : "Upload and process your document files"}
                    actions={topSectionActions}
                />
            }
        >
            <div className="px-4 py-8">
                <div className="max-w-4xl mx-auto space-y-8">
                    {/* Upload Area */}
                    <div className="bg-white rounded-lg shadow p-8">
                        {/* Real-time Status Tracker */}
                        {showStatusTracker && trackingId && (
                            <div className="mb-6">
                                <ProcessingStatusTracker
                                    trackingId={trackingId}
                                    onComplete={(finalSteps) => {
                                        console.log('📊 Upload Page - Processing completed:', finalSteps);
                                        // Check if processing was successful
                                        const hasFailures = finalSteps.some(step => step.success === false);

                                        if (isReprocessing) {
                                            // Handle reprocessing completion
                                            if (hasFailures) {
                                                // Still has errors - redirect back to failed invoice with message
                                                setUploadError('Reprocessing completed but invoice still contains errors. Please review and fix the remaining issues.');
                                                setTimeout(() => {
                                                    router.push('/invoices');
                                                }, 3000);
                                            } else {
                                                // Successfully reprocessed - show success and redirect to invoices
                                                setUploadSuccess('✅ Invoice reprocessed successfully! Moved to successful invoices.');
                                                setTimeout(() => {
                                                    router.push('/invoices');
                                                }, 2000);
                                            }
                                        } else {
                                            // Handle normal upload completion
                                            if (hasFailures) {
                                                // Show error message but stay on page
                                                setUploadError('Processing completed with errors. Please review the details below.');
                                            } else {
                                                // Show success message but stay on page
                                                setUploadSuccess(`File processed successfully! You can view it in the invoices list.`);
                                            }
                                        }
                                        // Don't redirect - let user stay on page to see results
                                    }}
                                    onError={(error) => {
                                        console.error('📊 Upload Page - Status tracker error:', error);
                                        setUploadError(error);
                                    }}
                                    pollInterval={500} // Poll every 500ms for faster updates
                                    autoStopPolling={false} // Keep polling to show final status
                                />
                            </div>
                        )}

                        {/* Upload Progress - Only show if not showing status tracker */}
                        {uploading && !showStatusTracker && (
                            <div className="mb-6 rounded-md bg-blue-50 p-6">
                                <div className="text-center">
                                    <div className="mx-auto h-12 w-12 text-blue-500 animate-spin mb-4">
                                        <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24">
                                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                                        </svg>
                                    </div>
                                    <h3 className="text-lg font-medium text-blue-800 mb-2">Uploading Invoice...</h3>
                                    <p className="mt-3 text-sm text-blue-600">Please wait while we upload your file...</p>
                                </div>
                            </div>
                        )}

                        {/* Error Message */}
                        {uploadError && (
                            <div className="mb-6 rounded-md bg-red-50 p-4">
                                <div className="flex">
                                    <div className="flex-shrink-0">
                                        <XCircle className="h-5 w-5 text-red-400" />
                                    </div>
                                    <div className="ml-3 flex-1">
                                        <h3 className="text-sm font-medium text-red-800">Upload Error</h3>
                                        <div className="mt-2 text-sm text-red-700 whitespace-pre-line">{uploadError}</div>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Success Message */}
                        {uploadSuccess && (
                            <div className="mb-6 rounded-md bg-green-50 p-4">
                                <div className="flex">
                                    <div className="flex-shrink-0">
                                        <CheckCircle className="h-5 w-5 text-green-400" />
                                    </div>
                                    <div className="ml-3 flex-1">
                                        <h3 className="text-sm font-medium text-green-800">Upload Successful</h3>
                                        <div className="mt-2 text-sm text-green-700">{uploadSuccess}</div>
                                    </div>
                                </div>
                            </div>
                        )}

                        <div
                            className={cn(
                                "border-2 border-dashed rounded-lg p-12 text-center",
                                dragActive ? "border-blue-400 bg-blue-50" : "border-gray-300",
                                uploading && "opacity-50"
                            )}
                            onDragEnter={handleDrag}
                            onDragLeave={handleDrag}
                            onDragOver={handleDrag}
                            onDrop={handleDrop}
                        >
                            <label htmlFor="file-upload" className="cursor-pointer">
                                <Upload className="mx-auto h-16 w-16 text-gray-400 hover:text-blue-500 transition-colors" />
                                <div className="mt-6">
                                    <span className="mt-2 block text-lg font-medium text-gray-900">
                                        {uploading ? 'Uploading...' : 'Drop files here or click to upload'}
                                    </span>
                                    <span className="mt-2 block text-sm text-gray-500">
                                        Supports EDI, XML, TXT, and X12 files (max 10MB)
                                    </span>
                                </div>
                            </label>
                            <input
                                id="file-upload"
                                name="file-upload"
                                type="file"
                                className="sr-only"
                                onChange={handleChange}
                                disabled={uploading}
                                accept=".xml"
                            />
                        </div>
                    </div>

                    {/* File Requirements */}
                    <div className="bg-white rounded-lg shadow p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">File Requirements</h3>
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                            <div>
                                <h4 className="font-medium text-gray-900 mb-2">Supported Input Format</h4>
                                <ul className="text-sm text-gray-600 space-y-1">
                                    <li>• XML (.xml) only</li>
                                    <li className="text-xs text-gray-500 mt-2 ml-4">Output format is determined by customer settings</li>
                                </ul>
                            </div>
                            <div>
                                <h4 className="font-medium text-gray-900 mb-2">File Limits</h4>
                                <ul className="text-sm text-gray-600 space-y-1">
                                    <li>• Maximum file size: 10MB</li>
                                    <li>• One file per upload</li>
                                    <li>• Valid invoice format required</li>
                                </ul>
                            </div>
                        </div>
                    </div>

                    {/* Processing Steps */}
                    <div className="bg-white rounded-lg shadow p-6">
                        <h3 className="text-lg font-semibold text-gray-900 mb-4">Processing Steps</h3>
                        <div className="space-y-4">
                            <div className="flex items-center space-x-3">
                                <div className="flex-shrink-0 w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                    <span className="text-blue-600 font-medium text-sm">1</span>
                                </div>
                                <div>
                                    <h4 className="font-medium text-gray-900">File Upload</h4>
                                    <p className="text-sm text-gray-600">Your file is securely uploaded to our servers</p>
                                </div>
                            </div>
                            <div className="flex items-center space-x-3">
                                <div className="flex-shrink-0 w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                    <span className="text-blue-600 font-medium text-sm">2</span>
                                </div>
                                <div>
                                    <h4 className="font-medium text-gray-900">XML Validation</h4>
                                    <p className="text-sm text-gray-600">We validate the XML structure and content</p>
                                </div>
                            </div>
                            <div className="flex items-center space-x-3">
                                <div className="flex-shrink-0 w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                    <span className="text-blue-600 font-medium text-sm">3</span>
                                </div>
                                <div>
                                    <h4 className="font-medium text-gray-900">EDI Conversion</h4>
                                    <p className="text-sm text-gray-600">Convert XML to EDI format for processing</p>
                                </div>
                            </div>
                            <div className="flex items-center space-x-3">
                                <div className="flex-shrink-0 w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center">
                                    <span className="text-blue-600 font-medium text-sm">4</span>
                                </div>
                                <div>
                                    <h4 className="font-medium text-gray-900">Completion</h4>
                                    <p className="text-sm text-gray-600">Your processed invoice is ready for download</p>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </MainLayout>
    );
}
