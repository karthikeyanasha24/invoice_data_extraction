'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import CustomerInvoicesDocumentsTab from '@/components/InvoicesV2/CustomerInvoicesDocumentsTab';
import ValidationTab from '@/components/InvoicesV2/ValidationTab';
import FailedInvoicesTab from '@/components/InvoicesV2/FailedInvoicesTab';
import SuccessfulInvoicesTab from '@/components/InvoicesV2/SuccessfulInvoicesTab';
import ConvertTab from '@/components/InvoicesV2/ConvertTab';
import ConvertedInvoicesTab from '@/components/InvoicesV2/ConvertedInvoicesTab';
import { FileText, CheckSquare, CheckCircle, XCircle, FileType, RefreshCw, Loader } from 'lucide-react';
import { cn } from '@/lib/utils';

type TabType = 'documents' | 'validation' | 'failed' | 'successful' | 'convert' | 'converted';

function CustomerInvoicesContent() {
  const router = useRouter();
  const { user, loading } = useAuth();
  const searchParams = useSearchParams();
  const tabParam = searchParams.get('tab') as TabType | null;
  const [activeTab, setActiveTab] = useState<TabType>(tabParam || 'documents');

  useEffect(() => {
    if (!loading && user && !user.is_customer_user) {
      router.replace('/dashboard');
      return;
    }
  }, [user, loading, router]);

  useEffect(() => {
    if (tabParam && ['documents', 'validation', 'failed', 'successful', 'convert', 'converted'].includes(tabParam)) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  const authSettled = !loading;
  const isCustomerUser = user?.is_customer_user === true;
  const showContent = authSettled && !!user && isCustomerUser;

  if (!authSettled || !showContent) {
    return (
      <MainLayout>
        <div className="flex items-center justify-center min-h-[50vh]">
          <Loader className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      </MainLayout>
    );
  }

  return (
    <div className="space-y-6">
      <div className="border-b border-gray-200 min-w-0 overflow-hidden">
        <nav className="-mb-px flex flex-wrap gap-x-4 gap-y-1 sm:gap-x-6 md:gap-x-8" aria-label="Tabs">
          <button
            onClick={() => setActiveTab('documents')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'documents'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <FileText className={cn('mr-2 h-5 w-5', activeTab === 'documents' ? 'text-blue-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Documents
          </button>
          <button
            onClick={() => setActiveTab('validation')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'validation'
                ? 'border-amber-500 text-amber-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <CheckSquare className={cn('mr-2 h-5 w-5', activeTab === 'validation' ? 'text-amber-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Validation
          </button>
          <button
            onClick={() => setActiveTab('failed')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'failed'
                ? 'border-red-500 text-red-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <XCircle className={cn('mr-2 h-5 w-5', activeTab === 'failed' ? 'text-red-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Failed
          </button>
          <button
            onClick={() => setActiveTab('successful')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'successful'
                ? 'border-green-500 text-green-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <CheckCircle className={cn('mr-2 h-5 w-5', activeTab === 'successful' ? 'text-green-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Successful
          </button>
          <button
            onClick={() => setActiveTab('convert')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'convert'
                ? 'border-purple-500 text-purple-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <RefreshCw className={cn('mr-2 h-5 w-5', activeTab === 'convert' ? 'text-purple-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Convert
          </button>
          <button
            onClick={() => setActiveTab('converted')}
            className={cn(
              'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
              activeTab === 'converted'
                ? 'border-purple-500 text-purple-600'
                : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
            )}
          >
            <FileType className={cn('mr-2 h-5 w-5', activeTab === 'converted' ? 'text-purple-500' : 'text-gray-400 group-hover:text-gray-500')} />
            Converted
          </button>
        </nav>
      </div>
      <div className="mt-6">
        {activeTab === 'documents' && <CustomerInvoicesDocumentsTab />}
        {activeTab === 'validation' && <ValidationTab customerUserMode />}
        {activeTab === 'failed' && <FailedInvoicesTab customerUserMode />}
        {activeTab === 'successful' && <SuccessfulInvoicesTab customerUserMode />}
        {activeTab === 'convert' && <ConvertTab customerUserMode />}
        {activeTab === 'converted' && <ConvertedInvoicesTab customerUserMode />}
      </div>
    </div>
  );
}

export default function CustomerInvoicesPage() {
  return (
    <MainLayout>
      <TopSection
        title="Invoices"
        subtitle="View and process your invoices (assigned customers only)"
      />
      <Suspense
        fallback={
          <div className="flex items-center justify-center min-h-[400px]">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600" />
          </div>
        }
      >
        <CustomerInvoicesContent />
      </Suspense>
    </MainLayout>
  );
}
