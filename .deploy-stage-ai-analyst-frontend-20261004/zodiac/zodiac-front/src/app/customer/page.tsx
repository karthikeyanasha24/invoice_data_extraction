'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import {
  CUSTOMER_HOME_PATH,
  CUSTOMER_LOGIN_PATH,
  isCustomerPortalUser,
} from '@/lib/customerPortal';
import LoadingSpinner from '@/components/LoadingSpinner';

/** /customer → portal home or login */
export default function CustomerIndexPage() {
  const { user, loading, isAuthenticated } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (loading) return;
    if (isAuthenticated && isCustomerPortalUser(user)) {
      router.replace(CUSTOMER_HOME_PATH);
    } else if (isAuthenticated) {
      router.replace('/');
    } else {
      router.replace(CUSTOMER_LOGIN_PATH);
    }
  }, [loading, isAuthenticated, user, router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <LoadingSpinner size="lg" text="Opening Customer Portal…" />
    </div>
  );
}
