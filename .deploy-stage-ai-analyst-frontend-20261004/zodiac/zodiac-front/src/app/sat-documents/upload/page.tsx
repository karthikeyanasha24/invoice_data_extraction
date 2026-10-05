'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { satApi } from '@/lib/api';
import { Upload, FileText, CheckCircle, XCircle, ArrowLeft, Trash2, FileX } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';

interface SelectedFile {
  file: File;
  id: string;
  preview?: string;
}

interface UploadResult {
  filename: string;
  success: boolean;
  status: string;
  cfdi_uuid?: string;
  doc_type?: string;
  supplier_rfc?: string;
  error?: string;
}

export default function SATDocumentUploadPage() {
  const router = useRouter();
  const { user } = useAuth();
  const [selectedFiles, setSelectedFiles] = useState<SelectedFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadResults, setUploadResults] = useState<UploadResult[]>([]);
  const [dragActive, setDragActive] = useState(false);

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingSpinner />
      </div>
    );
  }

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
    }
  };

  const handleFiles = (files: FileList) => {
    const newFiles: SelectedFile[] = [];
    
    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      
      // Validate file type
      if (!file.name.toLowerCase().endsWith('.xml')) {
        alert(`File "${file.name}" is not an XML file. Only XML files are allowed.`);
        continue;
      }

      // Validate file size (10MB max)
      if (file.size > 10 * 1024 * 1024) {
        alert(`File "${file.name}" is too large. Maximum size is 10MB.`);
        continue;
      }

      newFiles.push({
        file,
        id: `${Date.now()}-${i}`,
      });
    }

    setSelectedFiles(prev => [...prev, ...newFiles]);
  };

  const removeFile = (id: string) => {
    setSelectedFiles(prev => prev.filter(f => f.id !== id));
  };

  const clearAll = () => {
    setSelectedFiles([]);
    setUploadResults([]);
  };

  const handleUpload = async () => {
    if (selectedFiles.length === 0) {
      alert('Please select at least one file to upload.');
      return;
    }

    setUploading(true);
    setUploadResults([]);

    try {
      // Create FileList-like object
      const dataTransfer = new DataTransfer();
      selectedFiles.forEach(sf => dataTransfer.items.add(sf.file));
      const fileList = dataTransfer.files;

      const result = await satApi.uploadFiles(fileList);
      
      console.log('Upload result:', result);
      
      if (result.results) {
        setUploadResults(result.results);
      }

      // Show success message if any files were uploaded successfully
      if (result.successful_count > 0) {
        // Wait a bit then redirect back to documents tab
        setTimeout(() => {
          router.push('/sat-documents');
        }, 3000);
      }

    } catch (error: any) {
      console.error('Upload error:', error);
      alert(error.message || 'Failed to upload files. Please try again.');
    } finally {
      setUploading(false);
    }
  };

  const getDocTypeBadge = (filename: string) => {
    const name = filename.toLowerCase();
    if (name.includes('invoice') || name.includes('factura')) {
      return <span className="px-2 py-1 bg-green-100 text-green-800 text-xs rounded-full">Invoice</span>;
    } else if (name.includes('payment') || name.includes('pago')) {
      return <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">Payment</span>;
    } else if (name.includes('credit') || name.includes('nota')) {
      return <span className="px-2 py-1 bg-orange-100 text-orange-800 text-xs rounded-full">Credit Note</span>;
    }
    return <span className="px-2 py-1 bg-gray-100 text-gray-800 text-xs rounded-full">Unknown</span>;
  };

  const successCount = uploadResults.filter(r => r.success).length;
  const failedCount = uploadResults.filter(r => !r.success).length;

  return (
    <MainLayout
      topSection={
        <div className="px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-3">
              <FileText className="w-6 h-6 sm:w-8 sm:h-8 text-blue-600" />
              <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">
                Upload SAT Documents
              </h1>
            </div>
            <button
              onClick={() => router.push('/sat-documents')}
              className="flex items-center gap-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" />
              <span className="hidden sm:inline">Back to Documents</span>
              <span className="sm:hidden">Back</span>
            </button>
          </div>
          <p className="text-sm sm:text-base text-gray-600">
            Upload multiple CFDI XML files at once (Invoice, Payment, Credit Note)
          </p>
        </div>
      }
    >
      <div className="px-4 sm:px-6 lg:px-8 py-8">
        <div className="max-w-5xl mx-auto space-y-6">
          
          {/* Upload Results */}
          {uploadResults.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">Upload Results</h2>
                <div className="flex gap-4 text-sm">
                  <span className="text-green-600 font-medium">✓ {successCount} successful</span>
                  <span className="text-red-600 font-medium">✗ {failedCount} failed</span>
                </div>
              </div>
              <div className="space-y-3">
                {uploadResults.map((result, index) => (
                  <div
                    key={index}
                    className={`p-4 rounded-lg border ${
                      result.success
                        ? 'bg-green-50 border-green-200'
                        : 'bg-red-50 border-red-200'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {result.success ? (
                        <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
                      ) : (
                        <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="font-medium text-gray-900">{result.filename}</span>
                          {result.success && result.doc_type && (
                            <span className={`px-2 py-1 text-xs rounded-full ${
                              result.doc_type === 'INVOICE' ? 'bg-green-100 text-green-800' :
                              result.doc_type === 'PAYMENT' ? 'bg-blue-100 text-blue-800' :
                              'bg-orange-100 text-orange-800'
                            }`}>
                              {result.doc_type}
                            </span>
                          )}
                        </div>
                        {result.success ? (
                          <div className="text-sm text-gray-600 space-y-1">
                            <div>UUID: {result.cfdi_uuid}</div>
                            <div>Supplier RFC: {result.supplier_rfc}</div>
                          </div>
                        ) : (
                          <div className="text-sm text-red-700">
                            {result.error || 'Upload failed'}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              {successCount > 0 && (
                <div className="mt-4 text-center text-sm text-gray-600">
                  Redirecting to documents page in 3 seconds...
                </div>
              )}
            </div>
          )}

          {/* Drag and Drop Zone */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">
              Select Files
            </h2>
            
            <div
              className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors ${
                dragActive
                  ? 'border-blue-400 bg-blue-50'
                  : 'border-gray-300 hover:border-gray-400'
              } ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
              onDragEnter={handleDrag}
              onDragLeave={handleDrag}
              onDragOver={handleDrag}
              onDrop={handleDrop}
            >
              <label htmlFor="file-upload" className="cursor-pointer">
                <Upload className="mx-auto h-16 w-16 text-gray-400 hover:text-blue-500 transition-colors" />
                <div className="mt-6">
                  <span className="text-lg font-medium text-gray-900">
                    Drop XML files here or click to browse
                  </span>
                  <p className="mt-2 text-sm text-gray-500">
                    Upload Invoice, Payment, and Credit Note XML files (max 10MB each)
                  </p>
                </div>
              </label>
              <input
                id="file-upload"
                name="file-upload"
                type="file"
                multiple
                accept=".xml"
                className="sr-only"
                onChange={handleFileInput}
                disabled={uploading}
              />
            </div>
          </div>

          {/* Selected Files */}
          {selectedFiles.length > 0 && (
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-lg font-semibold text-gray-900">
                  Selected Files ({selectedFiles.length})
                </h2>
                <button
                  onClick={clearAll}
                  className="text-sm text-red-600 hover:text-red-700 font-medium"
                  disabled={uploading}
                >
                  Clear All
                </button>
              </div>

              <div className="space-y-3">
                {selectedFiles.map((selectedFile) => (
                  <div
                    key={selectedFile.id}
                    className="flex items-center gap-3 p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors"
                  >
                    <FileText className="w-8 h-8 text-blue-600 flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-gray-900 truncate">
                          {selectedFile.file.name}
                        </span>
                        {getDocTypeBadge(selectedFile.file.name)}
                      </div>
                      <span className="text-sm text-gray-500">
                        {(selectedFile.file.size / 1024).toFixed(2)} KB
                      </span>
                    </div>
                    <button
                      onClick={() => removeFile(selectedFile.id)}
                      className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                      disabled={uploading}
                    >
                      <Trash2 className="w-5 h-5" />
                    </button>
                  </div>
                ))}
              </div>

              <div className="mt-6 flex gap-3">
                <button
                  onClick={handleUpload}
                  disabled={uploading || selectedFiles.length === 0}
                  className="flex-1 px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed font-medium transition-colors flex items-center justify-center gap-2"
                >
                  {uploading ? (
                    <>
                      <div className="w-5 h-5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-5 h-5" />
                      Upload {selectedFiles.length} File{selectedFiles.length !== 1 ? 's' : ''}
                    </>
                  )}
                </button>
              </div>
            </div>
          )}

          {/* Instructions */}
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              Upload Instructions
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div>
                <h4 className="font-medium text-gray-900 mb-2">File Types</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• Invoice (Factura) - CFDI 3.3/4.0</li>
                  <li>• Payment Complement (Complemento de Pago)</li>
                  <li>• Credit Note (Nota de Crédito)</li>
                </ul>
              </div>
              <div>
                <h4 className="font-medium text-gray-900 mb-2">Requirements</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• Only XML files (.xml)</li>
                  <li>• Maximum 10MB per file</li>
                  <li>• Valid CFDI structure required</li>
                </ul>
              </div>
            </div>

            <div className="mt-6 p-4 bg-blue-50 rounded-lg">
              <div className="flex gap-3">
                <FileText className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
                <div className="text-sm text-blue-800">
                  <p className="font-medium mb-1">Tip: Upload All 3 Files Together</p>
                  <p className="text-blue-700">
                    For best results, select all related documents (Invoice, Payment, Credit Note) 
                    from the same period and upload them in one batch. This makes it easier to merge 
                    them later in the Simple Merge tab.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
