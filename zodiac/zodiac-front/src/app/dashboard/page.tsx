'use client';

import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import DashboardLanding from '@/components/DashboardLanding';

export default function DashboardPage() {
  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Dashboard"
          subtitle="Overview and analytics for your invoice processing"
        />
      }
    >
      <div className="px-4 py-8">
        <DashboardLanding />
      </div>
    </MainLayout>
  );
}
