'use client';

import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import SATDocumentsTab from '@/components/SATDocumentsTab';
import SATSimpleMergeTab from '@/components/SATSimpleMergeTab';
import SATCanonicalTab from '@/components/SATCanonicalTab';
import SAPSendTab from '@/components/SAPSendTab';
import { FileText } from 'lucide-react';

export default function SATDocumentsPage() {
  const { user } = useAuth();
  const [activeTab, setActiveTab] = useState('documents');

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingSpinner />
      </div>
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
            Manage CFDI documents and canonical merging for SAP integration
          </p>

          {/* Tabs */}
          <div className="mt-4">
            <div className="flex gap-2 sm:gap-4 border-b border-gray-200 overflow-x-auto">
              <button
                onClick={() => setActiveTab('documents')}
                className={`px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap ${
                  activeTab === 'documents'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Documents
              </button>
              <button
                onClick={() => setActiveTab('simple-merge')}
                className={`px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap ${
                  activeTab === 'simple-merge'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Simple Merge
              </button>
              <button
                onClick={() => setActiveTab('canonical')}
                className={`px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap ${
                  activeTab === 'canonical'
                    ? 'text-blue-600 border-b-2 border-blue-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Canonical Merged
              </button>
              <button
                onClick={() => setActiveTab('send-to-sap')}
                className={`px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap ${
                  activeTab === 'send-to-sap'
                    ? 'text-green-600 border-b-2 border-green-600'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                Send to SAP
              </button>
            </div>
          </div>
        </div>
      }
    >
      {activeTab === 'documents' && <SATDocumentsTab />}
      {activeTab === 'simple-merge' && <SATSimpleMergeTab />}
      {activeTab === 'canonical' && <SATCanonicalTab />}
      {activeTab === 'send-to-sap' && <SAPSendTab />}
    </MainLayout>
  );
}

