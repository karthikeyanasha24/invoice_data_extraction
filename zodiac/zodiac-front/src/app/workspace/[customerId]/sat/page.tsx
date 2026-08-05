'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Loader } from 'lucide-react';
import MainLayout from '@/components/MainLayout';
import { useAuth } from '@/contexts/AuthContext';
import { workspaceApi } from '@/lib/api';
import WorkspaceShell from '@/components/workspace/WorkspaceShell';
import CustomerSATDocumentsTab from '@/components/SATDocuments/CustomerSATDocumentsTab';

export default function WorkspaceSatPage() {
  const params = useParams();
  const customerId = decodeURIComponent(String(params.customerId || ''));
  const { user, loading } = useAuth();
  const router = useRouter();
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [allowed, setAllowed] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace('/');
  }, [loading, user, router]);

  useEffect(() => {
    if (!user || !customerId) return;
    (async () => {
      try {
        const access = await workspaceApi.accessCheck(customerId);
        setAllowed(!!access.allowed);
        if (access.allowed) {
          const ws = await workspaceApi.getWorkspace(customerId);
          setDisplayName(ws.display_name || customerId);
        }
      } catch {
        setAllowed(false);
      } finally {
        setReady(true);
      }
    })();
  }, [user, customerId]);

  if (loading || !user || !ready) {
    return (
      <MainLayout>
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader className="h-8 w-8 animate-spin text-blue-500" />
        </div>
      </MainLayout>
    );
  }

  const isCustomerUser = user.is_customer_user && !user.is_admin;

  return (
    <MainLayout>
      <div className="p-4 md:p-6">
        <WorkspaceShell customerId={customerId} displayName={displayName} activeTab="sat">
          {!allowed ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
              Not authorized for this workspace.
            </div>
          ) : isCustomerUser ? (
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                SAT/CFDI documents via existing customer-scoped SAT APIs.
              </p>
              <CustomerSATDocumentsTab />
            </div>
          ) : (
            <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-700">
              <p>Admin: use existing SAT tools; this workspace does not replace them.</p>
              <Link className="text-blue-700 underline" href="/sat-documents">
                Open SAT Documents
              </Link>
            </div>
          )}
        </WorkspaceShell>
      </div>
    </MainLayout>
  );
}
