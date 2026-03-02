'use client';

import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import DashboardAIAnalysis from '@/components/DashboardAIAnalysis';

export default function DashboardAIPage() {
  return (
    <MainLayout
      topSection={
        <TopSection
          title="Generative AI"
          subtitle="Ask questions about your dashboard and get AI-powered analysis"
        />
      }
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 p-6">
          <DashboardAIAnalysis />
        </div>
      </div>
    </MainLayout>
  );
}
