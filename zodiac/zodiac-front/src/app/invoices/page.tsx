'use client';

import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import InvoicesLanding from '@/components/InvoicesLanding';

export default function InvoicesPage() {
  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Invoices"
          subtitle="Manage and track your invoice files"
        />
      }
    >
      <div className="px-4 py-8">
        <InvoicesLanding />
      </div>
    </MainLayout>
  );
}
