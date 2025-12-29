'use client';

import { useState } from 'react';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import SATDocumentsLanding from '@/components/SATDocumentsLanding';
import SATCanonicalTab from '@/components/SATCanonicalTab';
import { FileText, Layers } from 'lucide-react';

export default function SATDocumentsPage() {
  const [activeTab, setActiveTab] = useState<'documents' | 'canonical'>('documents');

  return (
    <MainLayout 
      topSection={
        <TopSection
          title="SAT Documents"
          subtitle="SAT (CFDI) documents - Invoice, Payment, and Credit Note management"
        />
      }
    >
      {/* Tabs */}
      <div className="bg-white border-b border-gray-200 mb-6">
        <div className="flex space-x-8">
          <button
            onClick={() => setActiveTab('documents')}
            className={`flex items-center gap-2 px-4 py-3 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'documents'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <FileText className="h-5 w-5" />
            Individual Documents
          </button>
          
          <button
            onClick={() => setActiveTab('canonical')}
            className={`flex items-center gap-2 px-4 py-3 border-b-2 font-medium text-sm transition-colors ${
              activeTab === 'canonical'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            <Layers className="h-5 w-5" />
            Canonical Merged
          </button>
        </div>
      </div>

      {/* Tab content */}
      {activeTab === 'documents' ? (
        <SATDocumentsLanding />
      ) : (
        <SATCanonicalTab />
      )}
    </MainLayout>
  );
}

