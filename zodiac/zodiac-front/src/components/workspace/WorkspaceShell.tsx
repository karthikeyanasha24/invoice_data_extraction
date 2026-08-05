'use client';

import Link from 'next/link';
import { ReactNode } from 'react';
import { Activity, Brain, Building2, FileText, Receipt, Settings2 } from 'lucide-react';
import { cn } from '@/lib/utils';

const tabs = [
  { id: 'overview', label: 'Overview', href: '', icon: Building2 },
  { id: 'invoices', label: 'Invoices', href: '/invoices', icon: FileText },
  { id: 'sat', label: 'SAT / CFDI', href: '/sat', icon: Receipt },
  { id: 'monitoring', label: 'Monitoring', href: '/monitoring', icon: Activity },
  { id: 'ai', label: 'AI Ops', href: '/ai', icon: Brain },
  { id: 'settings', label: 'Settings', href: '/settings', icon: Settings2 },
] as const;

interface WorkspaceShellProps {
  customerId: string;
  displayName?: string | null;
  activeTab: 'overview' | 'invoices' | 'sat' | 'monitoring' | 'ai' | 'settings';
  children: ReactNode;
}

export default function WorkspaceShell({
  customerId,
  displayName,
  activeTab,
  children,
}: WorkspaceShellProps) {
  const base = `/workspace/${encodeURIComponent(customerId)}`;

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-slate-200 bg-gradient-to-r from-slate-50 to-blue-50 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-blue-700">
              Customer Workspace
            </p>
            <h1 className="mt-1 text-2xl font-semibold text-slate-900">
              {displayName || customerId}
            </h1>
            <p className="mt-1 text-sm text-slate-600">
              Exclusive space for <span className="font-mono text-slate-800">{customerId}</span>.
            </p>
          </div>
          <Link
            href="/workspace"
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Back to Workspaces
          </Link>
        </div>
      </div>

      <nav className="-mb-px flex flex-wrap gap-2 border-b border-slate-200" aria-label="Workspace tabs">
        {tabs.map((tab) => {
          const href = tab.href ? `${base}${tab.href}` : base;
          const active = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <Link
              key={tab.id}
              href={href}
              className={cn(
                'inline-flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors',
                active
                  ? 'border-blue-600 text-blue-700'
                  : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800'
              )}
            >
              <Icon className="h-4 w-4" />
              {tab.label}
            </Link>
          );
        })}
      </nav>

      <div>{children}</div>
    </div>
  );
}
