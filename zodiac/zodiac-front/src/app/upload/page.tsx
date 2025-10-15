'use client';

import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Upload, FileText, CheckCircle, XCircle, ArrowLeft } from 'lucide-react';
import { cn } from '@/lib/utils';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import LoadingSpinner from '@/components/LoadingSpinner';
import { useRouter } from 'next/navigation';

export default function UploadPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState('');
  const [dragActive, setDragActive] = useState(false);

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
      console.log('📤 Upload Page - Upload result:', result);
      
      if (result.success && result.data) {
        setUploadSuccess(`File "${file.name}" uploaded and processed successfully!`);
        setTimeout(() => {
          setUploadSuccess('');
          router.push('/invoices');
        }, 2000);
      } else {
        // Handle error responses
        if (result.isProcessingError) {
          // File upload succeeded but processing failed - redirect to failed invoice page
          console.log('📤 Upload Page - Processing error detected, redirecting to failed invoice page');
          console.log('📤 Upload Page - Error data:', result.data);
          
          // Extract tracking ID from the error data
          const trackingId = result.data?.tracking_id;
          if (trackingId) {
            console.log('📤 Upload Page - Redirecting to failed invoice page with tracking ID:', trackingId);
            router.push(`/failed-invoice/${trackingId}`);
          } else {
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
    } finally {
      setUploading(false);
    }
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
          title="Upload Document"
          subtitle="Upload and process your document files"
          actions={topSectionActions}
        />
      }
    >
      <div className="px-4 py-8">
        <div className="max-w-4xl mx-auto space-y-8">
          {/* Upload Area */}
          <div className="bg-white rounded-lg shadow p-8">
            {/* Upload Progress */}
            {uploading && (
              <div className="mb-6 rounded-md bg-blue-50 p-6">
                <div className="text-center">
                  <div className="mx-auto h-12 w-12 text-blue-500 animate-spin mb-4">
                    <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                  </div>
                  <h3 className="text-lg font-medium text-blue-800 mb-2">Processing Invoice...</h3>
                  <div className="space-y-2">
                    <div className="flex items-center justify-center space-x-2 text-sm text-blue-700">
                      <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                      <span>Uploading file</span>
                    </div>
                    <div className="flex items-center justify-center space-x-2 text-sm text-gray-500">
                      <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                      <span>Validating XML format</span>
                    </div>
                    <div className="flex items-center justify-center space-x-2 text-sm text-gray-500">
                      <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                      <span>Converting to EDI</span>
                    </div>
                    <div className="flex items-center justify-center space-x-2 text-sm text-gray-500">
                      <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                      <span>Validating EDI format</span>
                    </div>
                  </div>
                  <p className="mt-3 text-sm text-blue-600">This may take a few moments...</p>
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
                accept=".edi,.xml,.txt,.x12"
              />
            </div>
          </div>

          {/* File Requirements */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">File Requirements</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium text-gray-900 mb-2">Supported Formats</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• EDI (.edi)</li>
                  <li>• XML (.xml)</li>
                  <li>• Text (.txt)</li>
                  <li>• X12 (.x12)</li>
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
