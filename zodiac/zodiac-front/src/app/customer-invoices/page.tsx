'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import LoadingSpinner from '@/components/LoadingSpinner';

/** Legacy customer invoices route → dedicated portal. */
export default function LegacyCustomerInvoicesRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/customer/invoices');
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <LoadingSpinner size="lg" text="Opening Customer Portal…" />
    </div>
  );
}
