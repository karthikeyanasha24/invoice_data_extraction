'use client';

import { use } from 'react';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import SATDocumentDetail from '@/components/SATDocumentDetail';

export default function SATDocumentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const resolvedParams = use(params);
  
  return (
    <MainLayout 
      topSection={
        <TopSection
          title="SAT Document Details"
          subtitle="View CFDI document information and processing logs"
        />
      }
    >
      <SATDocumentDetail documentId={resolvedParams.id} />
    </MainLayout>
  );
}

