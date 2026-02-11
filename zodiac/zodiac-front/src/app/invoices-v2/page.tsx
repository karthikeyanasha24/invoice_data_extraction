'use client';

import { useState, useEffect } from 'react';
import { useSearchParams } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import DocumentsTab from '@/components/InvoicesV2/DocumentsTab';
import ValidationTab from '@/components/InvoicesV2/ValidationTab';
import FailedInvoicesTab from '@/components/InvoicesV2/FailedInvoicesTab';
import SuccessfulInvoicesTab from '@/components/InvoicesV2/SuccessfulInvoicesTab';
import { FileText, CheckCircle, ClipboardList, XCircle } from 'lucide-react';
import { cn } from '@/lib/utils';

type TabType = 'documents' | 'validation' | 'failed' | 'successful';

export default function InvoicesV2Page() {
  const searchParams = useSearchParams();
  const tabParam = searchParams.get('tab') as TabType | null;
  const [activeTab, setActiveTab] = useState<TabType>(tabParam || 'documents');

  useEffect(() => {
    if (tabParam && ['documents', 'validation', 'failed', 'successful'].includes(tabParam)) {
      setActiveTab(tabParam);
    }
  }, [tabParam]);

  return (
    <MainLayout>
      <TopSection
        title="Invoices V2"
        subtitle="Manage and validate invoice documents"
      />

      <div className="space-y-6">
        {/* Tab Navigation */}
        <div className="border-b border-gray-200 overflow-x-auto">
          <nav className="-mb-px flex space-x-8" aria-label="Tabs">
            <button
              onClick={() => setActiveTab('documents')}
              className={cn(
                'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
                activeTab === 'documents'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              )}
            >
              <FileText
                className={cn(
                  'mr-2 h-5 w-5',
                  activeTab === 'documents'
                    ? 'text-blue-500'
                    : 'text-gray-400 group-hover:text-gray-500'
                )}
              />
              Documents
            </button>

            <button
              onClick={() => setActiveTab('validation')}
              className={cn(
                'group inline-flex items-center border-b-2 py-4 px-1 text-sm font-medium transition-colors whitespace-nowrap',
                activeTab === 'validation'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              )}
            >
              <ClipboardList
                className={cn(
                  'mr-2 h-5 w-5',
                  activeTab === 'validation'
                    ? 'text-blue-500'
                    : 'text-gray-400 group-hover:text-gray-500'
                )}
              />
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
              <XCircle
                className={cn(
                  'mr-2 h-5 w-5',
                  activeTab === 'failed'
                    ? 'text-red-500'
                    : 'text-gray-400 group-hover:text-gray-500'
                )}
              />
              Failed Invoices
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
              <CheckCircle
                className={cn(
                  'mr-2 h-5 w-5',
                  activeTab === 'successful'
                    ? 'text-green-500'
                    : 'text-gray-400 group-hover:text-gray-500'
                )}
              />
              Successful Invoices
            </button>
          </nav>
        </div>

        {/* Tab Content */}
        <div className="mt-6">
          {activeTab === 'documents' && <DocumentsTab />}
          {activeTab === 'validation' && <ValidationTab />}
          {activeTab === 'failed' && <FailedInvoicesTab />}
          {activeTab === 'successful' && <SuccessfulInvoicesTab />}
        </div>
      </div>
    </MainLayout>
  );
}
