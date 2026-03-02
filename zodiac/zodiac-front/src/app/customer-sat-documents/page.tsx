'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import CustomerSATDocumentsTab from '@/components/SATDocuments/CustomerSATDocumentsTab';
import SATSimpleMergeTab from '@/components/SATSimpleMergeTab';
import SAPSendTab from '@/components/SAPSendTab';
import { FileText, Merge, Send, Loader } from 'lucide-react';
import { cn } from '@/lib/utils';

type TabType = 'documents' | 'simple-merge' | 'send-to-sap';

export default function CustomerSATDocumentsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabType>('documents');

  useEffect(() => {
    if (!loading && user && !user.is_customer_user) {
      router.replace('/dashboard');
      return;
    }
  }, [user, loading, router]);

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
    <MainLayout
      topSection={
        <div className="px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3 mb-2">
            <FileText className="w-6 h-6 sm:w-8 sm:h-8 text-blue-600" />
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">SAT Documents</h1>
          </div>
          <p className="text-sm sm:text-base text-gray-600">
            View CFDI documents for your assigned RFC(s), merge and send to SAP. Upload and receive are managed by your administrator.
          </p>
          <div className="mt-4">
            <div className="flex flex-wrap gap-x-2 gap-y-1 sm:gap-x-4 border-b border-gray-200 min-w-0 overflow-hidden">
              <button
                onClick={() => setActiveTab('documents')}
                className={cn(
                  'px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap',
                  activeTab === 'documents'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                Documents
              </button>
              <button
                onClick={() => setActiveTab('simple-merge')}
                className={cn(
                  'px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap',
                  activeTab === 'simple-merge'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                Simple Merge
              </button>
              <button
                onClick={() => setActiveTab('send-to-sap')}
                className={cn(
                  'px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap',
                  activeTab === 'send-to-sap'
                    ? 'text-green-600 border-b-2 border-green-600'
                    : 'text-gray-600 hover:text-gray-900'
                )}
              >
                Send to SAP
              </button>
            </div>
          </div>
        </div>
      }
    >
      <div className="px-4 sm:px-6 lg:px-8 py-4">
        {activeTab === 'documents' && <CustomerSATDocumentsTab />}
        {activeTab === 'simple-merge' && <SATSimpleMergeTab customerUserMode />}
        {activeTab === 'send-to-sap' && <SAPSendTab />}
      </div>
    </MainLayout>
  );
}
