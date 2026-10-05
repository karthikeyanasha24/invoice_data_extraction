'use client';

import { Suspense, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import OverviewCommandCenter from '@/components/OverviewCommandCenter';

function OverviewQueryHandoff({ children }: { children: React.ReactNode }) {
  const params = useSearchParams();
  const router = useRouter();
  useEffect(() => {
    const q = (params.get('q') || '').trim();
    if (q) {
      router.replace(`/dashboard/ai?q=${encodeURIComponent(q)}`);
    }
  }, [params, router]);
  return <>{children}</>;
}

export default function OverviewPage() {
  return (
    <MainLayout>
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <Suspense fallback={<p className="text-sm text-slate-600">Loading overview…</p>}>
          <OverviewQueryHandoff>
            <OverviewCommandCenter />
          </OverviewQueryHandoff>
        </Suspense>
      </div>
    </MainLayout>
  );
}
