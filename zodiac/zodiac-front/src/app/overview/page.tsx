'use client';

import MainLayout from '@/components/MainLayout';
import OverviewCommandCenter from '@/components/OverviewCommandCenter';

export default function OverviewPage() {
  return (
    <MainLayout>
      <div className="mx-auto max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
        <OverviewCommandCenter />
      </div>
    </MainLayout>
  );
}
