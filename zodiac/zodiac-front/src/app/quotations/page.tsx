'use client';

import { FileText } from 'lucide-react';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

/**
 * Quotations is outside the BridgeEDI first-customer invoice bridge.
 * Production-ready empty state — not a "Coming Soon" placeholder.
 */
export default function QuotationsPage() {
  const router = useRouter();

  return (
    <MainLayout
      topSection={
        <TopSection title="Quotations" subtitle="Not part of the BridgeEDI invoice bridge" />
      }
    >
      <div className="px-4 py-8">
        <div className="mx-auto max-w-xl rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
            <FileText className="h-7 w-7 text-slate-500" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900">Quotations not enabled</h2>
          <p className="mt-2 text-sm text-slate-600">
            This environment focuses on customer onboarding, invoice processing, government
            submission, monitoring, and AI Ops. Quotation management is not included in the
            BridgeEDI first-customer package.
          </p>
          <button
            type="button"
            onClick={() => router.push('/invoices-v2')}
            className="mt-6 rounded-lg bg-blue-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
          >
            Go to Invoices
          </button>
        </div>
      </div>
    </MainLayout>
  );
}
