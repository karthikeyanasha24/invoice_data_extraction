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
      <DashboardLanding />
    </MainLayout>
  );
}
