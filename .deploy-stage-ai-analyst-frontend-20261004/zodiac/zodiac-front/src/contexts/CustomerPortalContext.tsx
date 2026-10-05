'use client';

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { customerUsersApi, workspaceApi } from '@/lib/api';
import {
  CUSTOMER_LOGIN_PATH,
  isCustomerPortalUser,
  resolvePortalCustomerId,
} from '@/lib/customerPortal';

type PortalContextValue = {
  customerId: string | null;
  displayName: string | null;
  assignedCustomerIds: string[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
};

const CustomerPortalContext = createContext<PortalContextValue | undefined>(undefined);

export function CustomerPortalProvider({ children }: { children: ReactNode }) {
  const { user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [assignedCustomerIds, setAssignedCustomerIds] = useState<string[]>([]);
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const customerId = useMemo(
    () => resolvePortalCustomerId(assignedCustomerIds),
    [assignedCustomerIds]
  );

  const refresh = useCallback(async () => {
    if (!user || !isCustomerPortalUser(user)) return;
    setError(null);
    try {
      const ids = await customerUsersApi.getMyCustomers();
      const list = Array.isArray(ids) ? ids : [];
      setAssignedCustomerIds(list);
      const primary = resolvePortalCustomerId(list);
      if (!primary) {
        setDisplayName(null);
        setError('No customer workspace is assigned to your account. Contact your administrator.');
        return;
      }
      try {
        const ws = await workspaceApi.getWorkspace(primary);
        setDisplayName(ws?.display_name || primary);
      } catch {
        setDisplayName(primary);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Failed to resolve your workspace');
      setAssignedCustomerIds([]);
      setDisplayName(null);
    }
  }, [user]);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      router.replace(CUSTOMER_LOGIN_PATH);
      return;
    }
    if (!isCustomerPortalUser(user)) {
      // Admins / non-customer users must not use the customer portal.
      router.replace('/');
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      await refresh();
      if (!cancelled) setLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [user, authLoading, router, refresh]);

  const value = useMemo(
    () => ({
      customerId,
      displayName,
      assignedCustomerIds,
      loading: authLoading || loading,
      error,
      refresh,
    }),
    [customerId, displayName, assignedCustomerIds, authLoading, loading, error, refresh]
  );

  return (
    <CustomerPortalContext.Provider value={value}>{children}</CustomerPortalContext.Provider>
  );
}

export function useCustomerPortal() {
  const ctx = useContext(CustomerPortalContext);
  if (!ctx) {
    throw new Error('useCustomerPortal must be used within CustomerPortalProvider');
  }
  return ctx;
}
