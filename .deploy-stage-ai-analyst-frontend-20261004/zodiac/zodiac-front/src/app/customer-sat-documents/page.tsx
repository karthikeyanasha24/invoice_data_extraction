'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import LoadingSpinner from '@/components/LoadingSpinner';

/** Legacy customer SAT route → dedicated portal. */
export default function LegacyCustomerSatRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace('/customer/sat');
  }, [router]);
  return (
    <div className="flex min-h-screen items-center justify-center">
      <LoadingSpinner size="lg" text="Opening Customer Portal…" />
    </div>
  );
}
