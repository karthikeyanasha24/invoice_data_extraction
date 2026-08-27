'use client';

import { useEffect, useState } from 'react';
import MainLayout from '@/components/MainLayout';
import SATDocumentsTab from '@/components/SATDocumentsTab';
import SATSimpleMergeTab from '@/components/SATSimpleMergeTab';
import SATCanonicalTab from '@/components/SATCanonicalTab';
import SAPSendTab from '@/components/SAPSendTab';
import { FileText } from 'lucide-react';
import { dashboardApi } from '@/lib/api';

export default function SATDocumentsPage() {
  const [activeTab, setActiveTab] = useState('documents');
  const [summary, setSummary] = useState<any>(null);

  useEffect(() => {
    let cancelled = false;
    dashboardApi.getV2Inbound(0).then((res) => {
      if (!cancelled) setSummary(res?.summary || null);
    }).catch(() => {
      if (!cancelled) setSummary(null);
    });
    return () => { cancelled = true; };
  }, []);

  const docs = Number(summary?.total_documents || 0);
  const pending = Number(summary?.merges_pending || 0);
  const sent = Number(summary?.merges_sent_to_sap || 0);

  return (
    <MainLayout
      topSection={
        <div className="px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-3 mb-2">
            <FileText className="w-6 h-6 sm:w-8 sm:h-8 text-emerald-800" />
            <h1 className="text-2xl sm:text-3xl font-bold text-gray-900">SAT documents</h1>
          </div>
          <p className="text-sm sm:text-base text-gray-600">
            CFDI intake, merge, and send to SAP. Status counts below are inbound SAT activity, not a live ERP push.
          </p>
          {summary && (
            <div className="mt-3 grid grid-cols-3 gap-2 max-w-xl text-xs">
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-slate-500">Documents</p>
                <p className="text-base font-semibold tabular-nums text-slate-900">{docs}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-slate-500">Waiting to send</p>
                <p className="text-base font-semibold tabular-nums text-slate-900">{pending}</p>
              </div>
              <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
                <p className="text-slate-500">Sent to SAP</p>
                <p className="text-base font-semibold tabular-nums text-slate-900">{sent}</p>
              </div>
            </div>
          )}

          <div className="mt-4">
            <div className="flex gap-2 sm:gap-4 border-b border-gray-200 overflow-x-auto" role="tablist" aria-label="SAT workflow">
              {[
                { id: 'documents', label: 'Documents' },
                { id: 'simple-merge', label: 'Merge' },
                { id: 'canonical', label: 'Merged invoices' },
                { id: 'send-to-sap', label: 'Send to SAP' },
              ].map((tab) => (
                <button
                  key={tab.id}
                  role="tab"
                  aria-selected={activeTab === tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-3 sm:px-4 py-2 sm:py-3 font-medium transition-colors relative text-sm sm:text-base whitespace-nowrap ${
                    activeTab === tab.id
                      ? 'text-emerald-800 border-b-2 border-emerald-800'
                      : 'text-gray-600 hover:text-gray-900'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
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
