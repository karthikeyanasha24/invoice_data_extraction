'use client';

import { useState, useEffect, useCallback, Suspense } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { invoicesV2Api } from '@/lib/api';
import { Loader2, CheckCircle, XCircle, ArrowLeft, FileText } from 'lucide-react';
import { cn } from '@/lib/utils';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

interface DocumentProgress {
  document_id: number;
  filename: string;
  validation_status: 'not_validated' | 'processing' | 'validated';
  is_complete: boolean;
  result_status?: 'success' | 'failed';
  result_id?: number;
}

interface ValidationProgress {
  progress: DocumentProgress[];
  completed: number;
  total: number;
  all_done: boolean;
}

function ProcessingContent() {
  const router = useRouter();
  const { user } = useAuth();
  const searchParams = useSearchParams();
  const documentIdsParam = searchParams.get('ids');
  const invoicesBasePath = user?.is_customer_user ? '/customer-invoices' : '/invoices-v2';

  const [progress, setProgress] = useState<ValidationProgress | null>(null);
  const [polling, setPolling] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProgress = useCallback(async () => {
    if (!documentIdsParam) {
      setError('No document IDs provided');
      setPolling(false);
      return;
    }

    try {
      const ids = documentIdsParam.split(',').map(Number);
      const data = await invoicesV2Api.getValidationProgress(ids);
      setProgress(data);

      // Stop polling if all documents are done
      if (data.all_done) {
        setPolling(false);
      }
    } catch (err: any) {
      console.error('Failed to fetch progress:', err);
      setError(err.message || 'Failed to fetch validation progress');
      setPolling(false);
    }
  }, [documentIdsParam]);

  useEffect(() => {
    fetchProgress();
  }, [fetchProgress]);

  useEffect(() => {
    if (!polling) return;

    const interval = setInterval(() => {
      fetchProgress();
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(interval);
  }, [polling, fetchProgress]);

  const getStatusIcon = (doc: DocumentProgress) => {
    if (doc.is_complete) {
      return doc.result_status === 'success' ? (
        <CheckCircle className="h-6 w-6 text-green-500" />
      ) : (
        <XCircle className="h-6 w-6 text-red-500" />
      );
    }
    return <Loader2 className="h-6 w-6 text-blue-500 animate-spin" />;
  };

  const getStatusText = (doc: DocumentProgress) => {
    if (doc.is_complete) {
      return doc.result_status === 'success' ? 'Validation Successful' : 'Validation Failed';
    }
    if (doc.validation_status === 'processing') {
      return 'Processing...';
    }
    return 'Queued';
  };

  const handleGoToFailed = () => {
    router.push(`${invoicesBasePath}?tab=failed`);
  };

  const handleGoToSuccessful = () => {
    router.push(`${invoicesBasePath}?tab=successful`);
  };

  const handleBack = () => {
    router.push(`${invoicesBasePath}?tab=validation`);
  };

  if (error) {
    return (
      <MainLayout>
        <TopSection title="Validation Processing" subtitle="Processing invoice validation" />
        <div className="max-w-4xl mx-auto mt-8">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-center">
            <XCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-red-900 mb-2">Error</h3>
            <p className="text-sm text-red-700 mb-4">{error}</p>
            <button
              onClick={handleBack}
              className="inline-flex items-center px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors"
            >
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Validation
            </button>
          </div>
        </div>
      </MainLayout>
    );
  }

  if (!progress) {
    return (
      <MainLayout>
        <TopSection title="Validation Processing" subtitle="Processing invoice validation" />
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <Loader2 className="h-12 w-12 text-blue-500 animate-spin mx-auto mb-4" />
            <p className="text-gray-600">Loading validation progress...</p>
          </div>
        </div>
      </MainLayout>
    );
  }

  const successCount = progress.progress.filter(p => p.result_status === 'success').length;
  const failedCount = progress.progress.filter(p => p.result_status === 'failed').length;

  return (
    <MainLayout>
      <TopSection title="Validation Processing" subtitle="Processing invoice validation" />
      
      <div className="max-w-4xl mx-auto mt-8 space-y-6">
        {/* Progress Summary */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-gray-900">
              Processing {progress.total} Invoice{progress.total !== 1 ? 's' : ''}
            </h3>
            <div className="text-sm text-gray-600">
              {progress.completed} of {progress.total} completed
            </div>
          </div>

          {/* Progress Bar */}
          <div className="w-full bg-gray-200 rounded-full h-2.5 mb-4">
            <div
              className="bg-blue-600 h-2.5 rounded-full transition-all duration-500"
              style={{ width: `${(progress.completed / progress.total) * 100}%` }}
            ></div>
          </div>

          {/* Results Summary (only show when complete) */}
          {progress.all_done && (
            <div className="grid grid-cols-2 gap-4 mt-4">
              <div className="bg-green-50 border border-green-200 rounded-md p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-green-900">Successful</span>
                  <span className="text-lg font-bold text-green-600">{successCount}</span>
                </div>
              </div>
              <div className="bg-red-50 border border-red-200 rounded-md p-3">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-red-900">Failed</span>
                  <span className="text-lg font-bold text-red-600">{failedCount}</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Individual Document Progress */}
        <div className="space-y-3">
          {progress.progress.map((doc) => (
            <div
              key={doc.document_id}
              className={cn(
                'bg-white rounded-lg border p-4 transition-all',
                doc.is_complete
                  ? doc.result_status === 'success'
                    ? 'border-green-200 bg-green-50'
                    : 'border-red-200 bg-red-50'
                  : 'border-gray-200'
              )}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-3 flex-1 min-w-0">
                  {getStatusIcon(doc)}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <FileText className="h-4 w-4 text-gray-400 flex-shrink-0" />
                      <p className="text-sm font-medium text-gray-900 truncate">
                        {doc.filename}
                      </p>
                    </div>
                    <p className={cn(
                      'text-xs mt-1',
                      doc.is_complete
                        ? doc.result_status === 'success'
                          ? 'text-green-600'
                          : 'text-red-600'
                        : 'text-blue-600'
                    )}>
                      {getStatusText(doc)}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Action Buttons */}
        <div className="flex justify-between items-center pt-4">
          <button
            onClick={handleBack}
            className="inline-flex items-center px-4 py-2 border border-gray-300 text-sm font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 transition-colors"
          >
            <ArrowLeft className="h-4 w-4 mr-2" />
            Back to Validation
          </button>

          {progress.all_done && (
            <div className="flex gap-3">
              {failedCount > 0 && (
                <button
                  onClick={handleGoToFailed}
                  className="inline-flex items-center px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-md hover:bg-red-700 transition-colors"
                >
                  <XCircle className="h-4 w-4 mr-2" />
                  View Failed ({failedCount})
                </button>
              )}
              {successCount > 0 && (
                <button
                  onClick={handleGoToSuccessful}
                  className="inline-flex items-center px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-md hover:bg-green-700 transition-colors"
                >
                  <CheckCircle className="h-4 w-4 mr-2" />
                  View Successful ({successCount})
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
}

export default function ProcessingPage() {
  return (
    <Suspense fallback={
      <MainLayout>
        <TopSection title="Validation Processing" subtitle="Processing invoice validation" />
        <div className="flex items-center justify-center min-h-[400px]">
          <div className="text-center">
            <Loader2 className="h-12 w-12 text-blue-500 animate-spin mx-auto mb-4" />
            <p className="text-gray-600">Loading validation progress...</p>
          </div>
        </div>
      </MainLayout>
    }>
      <ProcessingContent />
    </Suspense>
  );
}
