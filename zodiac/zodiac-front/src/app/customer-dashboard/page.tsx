'use client';

import { useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import { Loader } from 'lucide-react';

/**
 * Legacy route: redirect to customer invoices (new default for customer users).
 */
export default function CustomerDashboardPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace('/');
      return;
    }
    if (!loading && user && !user.is_customer_user) {
      router.replace('/dashboard');
      return;
    }
    if (!loading && user?.is_customer_user) {
      router.replace('/customer-invoices');
    }
  }, [user, loading, router]);

  return (
    <MainLayout>
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader className="h-8 w-8 animate-spin text-blue-500" />
      </div>
    </MainLayout>
  );
}