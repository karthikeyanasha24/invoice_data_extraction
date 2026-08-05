'use client';

import { ReactNode } from 'react';
import { Loader } from 'lucide-react';
import { CustomerPortalProvider, useCustomerPortal } from '@/contexts/CustomerPortalContext';
import CustomerPortalShell from '@/components/customer/CustomerPortalShell';

function PortalFrame({ children }: { children: ReactNode }) {
  const { loading } = useCustomerPortal();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" />
      </div>
    );
  }
  return <CustomerPortalShell>{children}</CustomerPortalShell>;
}

export default function CustomerPortalLayout({ children }: { children: ReactNode }) {
  return (
    <CustomerPortalProvider>
      <PortalFrame>{children}</PortalFrame>
    </CustomerPortalProvider>
  );
}
