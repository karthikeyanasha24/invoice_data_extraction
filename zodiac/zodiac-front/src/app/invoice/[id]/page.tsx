'use client';

import { useEffect, useState } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Invoice } from '@/types';
import { ArrowLeft, CheckCircle, Download, Share2, FileText, Calendar, User, Building2, AlertTriangle, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

export default function InvoiceDetailsPage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const { user, handleAuthError } = useAuth();
  const invoiceId = params.id;

  const [invoice, setInvoice] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [sharing, setSharing] = useState(false);

  useEffect(() => {
    if (invoiceId) {
      fetchInvoiceDetails();
    }
  }, [invoiceId]);

  const fetchInvoiceDetails = async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch all invoices and find the one with matching ID
      const allInvoices = await fileApi.getFiles();
      const foundInvoice = allInvoices.find(
        (inv: Invoice) => inv.id.toString() === invoiceId
      );

      if (foundInvoice) {
        setInvoice(foundInvoice);
      } else {
        setError('Invoice not found.');
      }
    } catch (err: any) {
      console.error('Failed to fetch invoice details:', err);
      if (err.message?.includes('Session expired') || err.message?.includes('log in again')) {
        handleAuthError();
      } else {
        setError(err.message || 'Failed to load invoice details.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleDownload = async () => {
    if (!invoice) return;
    
    setDownloading(true);
    try {
      // In a real implementation, this would download the actual EDI file
      console.log('Downloading invoice:', invoice.filename);
      // For now, just simulate download
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (error) {
      console.error('Download failed:', error);
    } finally {
      setDownloading(false);
    }
  };

  const handleShare = async () => {
    if (!invoice) return;
    
    setSharing(true);
    try {
      // In a real implementation, this would share the invoice
      console.log('Sharing invoice:', invoice.filename);
      // For now, just simulate sharing
      await new Promise(resolve => setTimeout(resolve, 1000));
    } catch (error) {
      console.error('Share failed:', error);
    } finally {
      setSharing(false);
    }
  };

  const handleGoBack = () => {
    router.push('/invoices');
  };

  const topSectionActions = (
    <div className="flex items-center space-x-3">
      <button
        onClick={handleGoBack}
        className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        <span>Back to Invoices</span>
      </button>
    </div>
  );

  if (loading) {
    return (
      <MainLayout
        topSection={
          <TopSection
            title="Invoice Details"
            subtitle="Loading invoice details..."
            actions={topSectionActions}
          />
        }
      >
        <div className="px-4 py-8">
          <div className="flex items-center justify-center h-64">
            <LoadingSpinner size="lg" text="Loading invoice details..." />
          </div>
        </div>
      </MainLayout>
    );
  }

  if (error || !invoice) {
    return (
      <MainLayout
        topSection={
          <TopSection
            title="Invoice Details"
            subtitle="Error loading invoice"
            actions={topSectionActions}
          />
        }
      >
        <div className="px-4 py-8">
          <div className="flex items-center justify-center h-64">
            <div className="max-w-md w-full bg-white rounded-lg shadow-lg p-6 text-center">
              <FileText className="mx-auto h-12 w-12 text-gray-400 mb-4" />
              <h2 className="text-xl font-semibold text-gray-900 mb-2">Invoice Not Found</h2>
              <p className="text-gray-600 mb-4">
                {error || 'The requested invoice could not be found.'}
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
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout
      topSection={
        <TopSection
          title="Invoice Details"
          subtitle={`${invoice.filename} - ${invoice.status}`}
          actions={topSectionActions}
        />
      }
    >
      <div className="px-4 py-8">
        <div className="max-w-4xl mx-auto space-y-8">
          {/* Invoice Status */}
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div className="flex items-center space-x-3">
                <CheckCircle className="h-8 w-8 text-green-500" />
                <div>
                  <h2 className="text-lg font-semibold text-gray-900">Processing Complete</h2>
                  <p className="text-sm text-gray-600">Invoice successfully processed and converted</p>
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <span className={cn(
                  'px-3 py-1 rounded-full text-sm font-medium',
                  invoice.status === 'successful' || invoice.status === 'completed'
                    ? 'bg-green-100 text-green-800'
                    : 'bg-gray-100 text-gray-800'
                )}>
                  {invoice.status}
                </span>
              </div>
            </div>
          </div>

          {/* Invoice Information */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Invoice Information</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="space-y-4">
                <div>
                  <span className="text-sm font-medium text-gray-500">File Name:</span>
                  <p className="text-sm text-gray-900 break-all">{invoice.filename}</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-gray-500">Tracking ID:</span>
                  <p className="font-mono text-sm text-gray-900">{invoice.tracking_id || 'N/A'}</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-gray-500">Uploaded:</span>
                  <p className="text-sm text-gray-900">
                    {invoice.uploaded_at ? new Date(invoice.uploaded_at).toLocaleString() : 'N/A'}
                  </p>
                </div>
              </div>
              <div className="space-y-4">
                <div>
                  <span className="text-sm font-medium text-gray-500">Customer:</span>
                  <p className="text-sm text-gray-900">{invoice.customerName || 'Unknown'}</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-gray-500">Format:</span>
                  <p className="text-sm text-gray-900">{invoice.formate || 'XML'}</p>
                </div>
                <div>
                  <span className="text-sm font-medium text-gray-500">Export Format:</span>
                  <p className="text-sm text-gray-900">{invoice.export ? 'EDI' : 'N/A'}</p>
                </div>
              </div>
            </div>
          </div>

          {/* Processing Steps */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Processing Steps</h2>
            <div className="space-y-4">
              {/* Display actual processing steps if available, otherwise show default */}
              {invoice.processing_steps && invoice.processing_steps.length > 0 ? (
                invoice.processing_steps.map((step, index) => (
                  <div key={index} className="border rounded-lg p-4">
                    <div className="flex items-center space-x-3 mb-2">
                      {step.step_name === 'XML Validation' && invoice.xml_convert_message?.includes('warnings') ? (
                        <AlertTriangle className="h-5 w-5 text-yellow-500" />
                      ) : step.success ? (
                        <CheckCircle className="h-5 w-5 text-green-500" />
                      ) : (
                        <XCircle className="h-5 w-5 text-red-500" />
                      )}
                      <span className="font-medium text-gray-900">
                        {step.step_number}. {step.step_name}
                      </span>
                      <span className={cn(
                        "px-2 py-1 rounded-full text-xs font-medium",
                        step.step_name === 'XML Validation' && invoice.xml_convert_message?.includes('warnings')
                          ? "bg-yellow-100 text-yellow-800"
                          : step.success
                            ? "bg-green-100 text-green-800"
                            : "bg-red-100 text-red-800"
                      )}>
                        {step.step_name === 'XML Validation' && invoice.xml_convert_message?.includes('warnings')
                          ? 'Passed with Warnings'
                          : step.success ? 'Passed' : 'Failed'
                        }
                      </span>
                      {step.duration_seconds && (
                        <span className="text-xs text-gray-500">
                          ({step.duration_seconds.toFixed(2)}s)
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600">
                      {step.message || (step.success ? 'Step completed successfully' : 'Step failed')}
                    </p>
                    {step.error_details && step.error_details.length > 0 && (
                      <div className="mt-2 text-xs text-red-600">
                        <p className="font-medium">Errors:</p>
                        <ul className="list-disc list-inside mt-1">
                          {step.error_details.map((error, errorIndex) => (
                            <li key={errorIndex}>{error.error_message}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                ))
              ) : (
                /* Fallback to default steps if processing_steps not available */
                <>
                  {/* Step 1: File Upload */}
                  <div className="border rounded-lg p-4">
                    <div className="flex items-center space-x-3 mb-2">
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <span className="font-medium text-gray-900">1. File Upload</span>
                      <span className="px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Passed
                      </span>
                    </div>
                    <p className="text-sm text-gray-600">File uploaded successfully</p>
                  </div>

                  {/* Step 2: XML Validation */}
                  <div className="border rounded-lg p-4">
                    <div className="flex items-center space-x-3 mb-2">
                      {invoice.xml_convert_message?.includes('warnings') ? (
                        <AlertTriangle className="h-5 w-5 text-yellow-500" />
                      ) : (
                        <CheckCircle className="h-5 w-5 text-green-500" />
                      )}
                      <span className="font-medium text-gray-900">2. XML Validation</span>
                      <span className={cn(
                        "px-2 py-1 rounded-full text-xs font-medium",
                        invoice.xml_convert_message?.includes('warnings')
                          ? "bg-yellow-100 text-yellow-800"
                          : "bg-green-100 text-green-800"
                      )}>
                        {invoice.xml_convert_message?.includes('warnings') ? 'Passed with Warnings' : 'Passed'}
                      </span>
                    </div>
                    <p className="text-sm text-gray-600">
                      {invoice.xml_convert_message || 'XML structure validated successfully'}
                    </p>
                    {invoice.warnings && invoice.warnings.length > 0 && (
                      <div className="mt-2 text-xs text-yellow-600">
                        <p className="font-medium">Warnings:</p>
                        <ul className="list-disc list-inside mt-1">
                          {invoice.warnings.map((warning, index) => (
                            <li key={index}>{warning}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>

                  {/* Step 3: EDI Conversion */}
                  <div className="border rounded-lg p-4">
                    <div className="flex items-center space-x-3 mb-2">
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <span className="font-medium text-gray-900">3. EDI Conversion</span>
                      <span className="px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Passed
                      </span>
                    </div>
                    <p className="text-sm text-gray-600">
                      {invoice.edi_convert_message || 'Successfully converted to EDI format'}
                    </p>
                  </div>

                  {/* Step 4: EDI Format Validation */}
                  <div className="border rounded-lg p-4">
                    <div className="flex items-center space-x-3 mb-2">
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <span className="font-medium text-gray-900">4. EDI Format Validation</span>
                      <span className="px-2 py-1 rounded-full text-xs font-medium bg-green-100 text-green-800">
                        Passed
                      </span>
                    </div>
                    <p className="text-sm text-gray-600">EDI format validation completed successfully</p>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Action Buttons */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-4">Actions</h2>
            <div className="flex flex-wrap gap-4">
              <button
                onClick={handleDownload}
                disabled={downloading}
                className={cn(
                  'flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium',
                  downloading
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-green-600 text-white hover:bg-green-700'
                )}
              >
                <Download className="h-4 w-4" />
                <span>{downloading ? 'Downloading...' : 'Download EDI'}</span>
              </button>

              <button
                onClick={handleShare}
                disabled={sharing}
                className={cn(
                  'flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium',
                  sharing
                    ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-700'
                )}
              >
                <Share2 className="h-4 w-4" />
                <span>{sharing ? 'Sharing...' : 'Share Invoice'}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
