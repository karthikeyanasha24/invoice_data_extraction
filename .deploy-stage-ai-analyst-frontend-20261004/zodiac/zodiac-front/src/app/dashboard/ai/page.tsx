'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import DashboardAIAnalysis from '@/components/DashboardAIAnalysis';

function AIAnalystFromQuery() {
  const searchParams = useSearchParams();
  const q = (searchParams.get('q') || '').trim() || undefined;
  return <DashboardAIAnalysis initialQuestion={q} />;
}

export default function DashboardAIPage() {
  return (
    <MainLayout fillViewport>
      <Suspense fallback={<div className="p-6 text-sm text-slate-600">Loading AI Analyst…</div>}>
        <AIAnalystFromQuery />
      </Suspense>
    </MainLayout>
  );
}
