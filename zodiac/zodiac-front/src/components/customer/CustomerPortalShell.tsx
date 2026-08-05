'use client';

import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  Activity,
  Brain,
  Building2,
  FileText,
  LogOut,
  Receipt,
  Settings2,
} from 'lucide-react';
import { ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useCustomerPortal } from '@/contexts/CustomerPortalContext';
import { CUSTOMER_LOGIN_PATH } from '@/lib/customerPortal';
import { cn } from '@/lib/utils';

const nav = [
  { href: '/customer/overview', label: 'Overview', icon: Building2 },
  { href: '/customer/invoices', label: 'Invoices', icon: FileText },
  { href: '/customer/sat', label: 'SAT', icon: Receipt },
  { href: '/customer/monitoring', label: 'Monitoring', icon: Activity },
  { href: '/customer/ai', label: 'AI Ops', icon: Brain },
  { href: '/customer/settings', label: 'Settings', icon: Settings2 },
] as const;

export default function CustomerPortalShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { logout, user } = useAuth();
  const { customerId, displayName, error } = useCustomerPortal();

  const handleLogout = () => {
    logout();
    router.replace(CUSTOMER_LOGIN_PATH);
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 md:px-6">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">
              Customer Portal
            </p>
            <h1 className="text-xl font-semibold text-slate-900">
              {displayName || customerId || 'Your workspace'}
            </h1>
            {customerId && (
              <p className="mt-0.5 font-mono text-xs text-slate-500">{customerId}</p>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <span className="hidden sm:inline">{user?.email}</span>
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              <LogOut className="h-4 w-4" />
              Logout
            </button>
          </div>
        </div>
        <nav
          className="mx-auto flex max-w-6xl flex-wrap gap-1 px-4 pb-0 md:px-6"
          aria-label="Customer portal"
        >
          {nav.map((item) => {
            const active = pathname === item.href || pathname?.startsWith(item.href + '/');
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  'inline-flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
                  active
                    ? 'border-emerald-600 text-emerald-800'
                    : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-6 md:px-6">
        {error && (
          <div className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            {error}
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
