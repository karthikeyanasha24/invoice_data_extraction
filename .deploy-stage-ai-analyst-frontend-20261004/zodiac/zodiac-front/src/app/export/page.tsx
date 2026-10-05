'use client';

import { Download } from 'lucide-react';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

/**
 * Standalone export hub is not part of the BridgeEDI first-customer package.
 * Production-ready empty state — not a "Coming Soon" placeholder.
 */
export default function ExportPage() {
  const router = useRouter();

  return (
    <MainLayout
      topSection={
        <TopSection title="Export" subtitle="Use invoice and SAT screens for operational exports" />
      }
    >
      <div className="px-4 py-8">
        <div className="mx-auto max-w-xl rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-slate-100">
            <Download className="h-7 w-7 text-slate-500" />
          </div>
          <h1 className="text-lg font-semibold text-slate-900">Centralized export not enabled</h1>
          <p className="mt-2 text-sm text-slate-600">
            Export invoices and SAT documents from their respective operational screens. A
            standalone bulk-export console is not part of the first-customer BridgeEDI package.
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
