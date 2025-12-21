'use client';

import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import DashboardNew from '@/components/DashboardNew';
import { BarChart3 } from 'lucide-react';

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
      <DashboardNew />
    </MainLayout>
  );
}
