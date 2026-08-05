'use client';

import { useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useRouter } from 'next/navigation';
import { Loader } from 'lucide-react';
import { CUSTOMER_HOME_PATH } from '@/lib/customerPortal';

/**
 * Legacy route: redirect to the dedicated customer portal (no admin shell).
 */
export default function CustomerDashboardPage() {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (!user) {
      router.replace('/customer/login');
      return;
    }
    if (user.is_customer_user && !user.is_admin) {
      router.replace(CUSTOMER_HOME_PATH);
      return;
    }
    router.replace('/dashboard');
  }, [user, loading, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <Loader className="h-8 w-8 animate-spin text-emerald-600" aria-label="Redirecting" />
    </div>
  );
}
