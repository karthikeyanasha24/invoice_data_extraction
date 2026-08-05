'use client';

import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import CustomerSATDocumentsTab from '@/components/SATDocuments/CustomerSATDocumentsTab';

export default function CustomerSatPortalPage() {
  const { customerId } = useCustomerPortal();
  if (!customerId) {
    return <p className="text-sm text-slate-600">No workspace assigned.</p>;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        SAT / CFDI documents for{' '}
        <span className="font-mono text-slate-800">{customerId}</span>.
      </p>
      <CustomerSATDocumentsTab />
    </div>
  );
}
