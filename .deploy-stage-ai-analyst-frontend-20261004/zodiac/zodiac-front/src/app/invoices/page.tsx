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
      <InvoicesLanding />
    </MainLayout>
  );
}
