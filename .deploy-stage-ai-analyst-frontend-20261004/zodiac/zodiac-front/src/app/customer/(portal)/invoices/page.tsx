'use client';

import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import CustomerInvoicesDocumentsTab from '@/components/InvoicesV2/CustomerInvoicesDocumentsTab';

export default function CustomerInvoicesPortalPage() {
  const { customerId } = useCustomerPortal();
  if (!customerId) {
    return <p className="text-sm text-slate-600">No workspace assigned.</p>;
  }
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        Invoices for your organization{' '}
        <span className="font-mono text-slate-800">{customerId}</span>. Upload and receive are
        managed with your BridgeEDI administrator.
      </p>
      <CustomerInvoicesDocumentsTab />
    </div>
  );
}
