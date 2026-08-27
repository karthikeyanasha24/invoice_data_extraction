'use client';

import { Suspense } from 'react';
import MainLayout from '@/components/MainLayout';
import IntelligencePage from '@/components/IntelligencePage';

export default function DashboardAIPage() {
  return (
    <MainLayout fillViewport>
      <Suspense fallback={<div className="p-6 text-sm text-slate-600">Loading AI Analyst…</div>}>
        <IntelligencePage />
      </Suspense>
    </MainLayout>
  );
}
