'use client';

import { useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  FileText,
  Receipt,
  Settings,
  ChevronLeft,
  ChevronRight,
  User,
  LogOut,
  Building2,
  Key,
  Users,
  Sparkles,
  Wifi,
  WifiOff,
  AlertCircle,
  MapPin,
  Boxes,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

// ── Environment detection ─────────────────────────────────────────────────────
const API_URL = (process.env.NEXT_PUBLIC_API_URL || '').trim();
const IS_LOCAL  = !API_URL || API_URL.includes('localhost') || API_URL.includes('127.0.0.1');
const IS_PROD   = API_URL.includes('vercel.app') || (!!API_URL && !IS_LOCAL);
const ENV_LABEL = IS_LOCAL ? '⚠ LOCAL DEV' : IS_PROD ? '● PRODUCTION' : 'UNKNOWN';
const ENV_COLOR = IS_LOCAL
  ? 'bg-amber-100 text-amber-800 border-amber-300'
  : IS_PROD
  ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
  : 'bg-slate-100 text-slate-600 border-slate-200';
const ENV_DOT   = IS_LOCAL ? 'bg-amber-400' : 'bg-emerald-400';
const ENV_TIP   = IS_LOCAL
  ? `Connecting to: ${API_URL || 'localhost:8000'}\nLocal API. The database behind this API may still contain SAP demo data.`
  : `Connecting to: ${API_URL}\n✓ Production database — real SAP data.`;

interface SidebarProps {
  isCollapsed: boolean;
  onToggle: () => void;
  isMobile?: boolean;
  mobileOpen?: boolean;
}

export default function Sidebar({ isCollapsed, onToggle, isMobile = false, mobileOpen = false }: SidebarProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, logout } = useAuth();

  const isCustomerUser = user?.is_customer_user && !user?.is_admin;
  // Phase 2: workspace nav — default on; set NEXT_PUBLIC_WORKSPACE_UI=false to hide
  const workspaceUiEnabled = process.env.NEXT_PUBLIC_WORKSPACE_UI !== 'false';
  const workspaceMenuItem = {
    id: 'workspaces',
    label: 'Workspaces',
    icon: Boxes,
    path: '/workspace',
    description: 'Per-customer workspace',
  };
  const adminMenuItems = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard, path: '/dashboard', description: 'Inbound, outbound, and business operations' },
    { id: 'generative-ai', label: 'Intelligence', icon: Sparkles, path: '/dashboard/ai', description: 'Ask questions about SAP business data' },
    { id: 'invoices', label: 'Invoices', icon: FileText, path: '/invoices-v2', description: 'Validate and convert invoices' },
    { id: 'customers', label: 'Customers', icon: Building2, path: '/customers', description: 'Manage EDI customers' },
    ...(workspaceUiEnabled ? [workspaceMenuItem] : []),
    ...(user?.is_admin ? [{ id: 'customer-users', label: 'Customer users', icon: Users, path: '/customer-users', description: 'Users & customer assignments' }] : []),
    { id: 'sat-documents', label: 'SAT Documents', icon: Receipt, path: '/sat-documents', description: 'CFDI documents and SAP send' },
    { id: 'account-mapping', label: 'Account Mapping', icon: MapPin, path: '/admin/account-mapping', description: 'RFC to SAP G/L mapping' },
    { id: 'supplier-tokens', label: 'Supplier Tokens', icon: Key, path: '/admin/supplier-tokens', description: 'Manage supplier API tokens' },
    { id: 'settings', label: 'Settings', icon: Settings, path: '/settings', description: 'Account and API access' }
  ];
  // Phase 11 — customer users are redirected to /customer/* (see MainLayout).
  // Keep a minimal fallback menu pointing at the dedicated portal only.
  const customerUserMenuItems = [
    { id: 'customer-portal', label: 'Customer Portal', icon: Boxes, path: '/customer/overview', description: 'Your exclusive workspace' },
  ];
  const menuItems = isCustomerUser ? customerUserMenuItems : adminMenuItems;

  const handleNavigation = (path: string) => {
    router.push(path);
  };

  const handleLogout = () => {
    logout();
    // Customer portal users return to dedicated login
    router.push(isCustomerUser ? '/customer/login' : '/');
  };

  return (
    <div className={cn(
      "bg-white border-r border-gray-200 transition-all duration-300 flex flex-col h-screen fixed left-0 top-0 z-50",
      isMobile ? "w-64" : (isCollapsed ? "w-16" : "w-64"),
      isMobile && !mobileOpen && "-translate-x-full"
    )}>
      {/* Header */}
      <div className="p-3 sm:p-4 border-b border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100">
        <div className="flex items-center justify-between">
          {(!isCollapsed || isMobile) && (
            <div className="flex items-center space-x-2 sm:space-x-3 min-w-0">
              <div className="w-7 h-7 sm:w-8 sm:h-8 bg-gradient-to-br from-blue-600 to-indigo-700 rounded-full flex items-center justify-center shadow-sm flex-shrink-0">
                <span className="text-white font-bold text-sm">Z</span>
              </div>
              <div className="min-w-0">
                <span className="font-semibold text-slate-900 text-sm sm:text-base truncate block">BridgeEDI</span>
                <p className="text-xs text-slate-500 truncate">Invoice ops + SAP Q&amp;A</p>
              </div>
            </div>
          )}
          {!isMobile && (
            <button
              onClick={onToggle}
              className="p-1.5 rounded-md hover:bg-slate-200 transition-colors flex-shrink-0 cursor-pointer"
              title={isCollapsed ? "Expand sidebar" : "Collapse sidebar"}
            >
              {isCollapsed ? (
                <ChevronRight className="h-4 w-4 text-slate-500" />
              ) : (
                <ChevronLeft className="h-4 w-4 text-slate-500" />
              )}
            </button>
          )}
          {isMobile && (
            <button
              onClick={onToggle}
              className="p-1.5 rounded-md hover:bg-slate-200 transition-colors flex-shrink-0 cursor-pointer lg:hidden"
              title="Close menu"
            >
              <ChevronLeft className="h-5 w-5 text-slate-500" />
            </button>
          )}
        </div>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 p-3 sm:p-4 overflow-y-auto">
        <div className="space-y-1 sm:space-y-2">
          {menuItems.map((item) => {
            const Icon = item.icon;
            const isActive = item.path === '/dashboard'
              ? pathname === '/dashboard'
              : pathname === item.path || pathname.startsWith(item.path + '/');
            
            return (
              <button
                key={item.id}
                onClick={() => handleNavigation(item.path)}
                className={cn(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left transition-all duration-200 group cursor-pointer min-w-0",
                  isActive 
                    ? "bg-gradient-to-r from-blue-50 to-indigo-50 text-blue-700 border border-blue-200 shadow-sm" 
                    : "text-slate-700 hover:bg-slate-50 hover:text-slate-900"
                )}
                title={isCollapsed && !isMobile ? item.label : undefined}
              >
                <Icon className={cn(
                  "h-5 w-5 flex-shrink-0",
                  isActive ? "text-blue-600" : "text-slate-500 group-hover:text-slate-700"
                )} />
                {(!isCollapsed || isMobile) && (
                  <div className="flex-1 min-w-0 overflow-hidden">
                    <div className="font-medium text-sm truncate">{item.label}</div>
                    <div className="text-xs text-slate-500 truncate">{item.description}</div>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </nav>

      {/* Environment Indicator */}
      {(!isCollapsed || isMobile) && (
        <div className="px-3 pb-2">
          <div
            className={cn(
              'flex items-center gap-2 px-2.5 py-1.5 rounded-lg border text-[11px] font-semibold cursor-help select-none',
              ENV_COLOR,
            )}
            title={ENV_TIP}
          >
            <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0 animate-pulse', ENV_DOT)} />
            <span className="flex-1 truncate">{ENV_LABEL}</span>
            {IS_LOCAL && <AlertCircle className="h-3 w-3 flex-shrink-0 text-amber-600" />}
          </div>
          {IS_LOCAL && (
            <p className="text-[10px] text-amber-700 mt-1 px-1 leading-tight">
              Connecting to local API. SAP demo data may still be present in the configured database.
            </p>
          )}
        </div>
      )}
      {isCollapsed && !isMobile && (
        <div className="flex justify-center pb-2">
          <div
            className={cn('w-2 h-2 rounded-full animate-pulse', ENV_DOT)}
            title={ENV_TIP}
          />
        </div>
      )}

      {/* User Section */}
      <div className="p-3 sm:p-4 border-t border-slate-200 bg-gradient-to-r from-slate-50 to-slate-100">
        {(!isCollapsed || isMobile) ? (
          <div className="space-y-3">
            {/* User Info */}
            <div className="flex items-center space-x-3 min-w-0">
              <div className="w-8 h-8 bg-gradient-to-br from-slate-200 to-slate-300 rounded-full flex items-center justify-center flex-shrink-0">
                <User className="h-4 w-4 text-slate-600" />
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-900 truncate">
                  {user?.username || 'User'}
                </div>
                <div className="text-xs text-slate-500 truncate">
                  {user?.email || 'user@example.com'}
                </div>
              </div>
            </div>

            {/* Logout Button */}
            <button
              onClick={handleLogout}
              className="w-full flex items-center space-x-3 px-3 py-2 rounded-lg text-left text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
            >
              <LogOut className="h-5 w-5 text-slate-500 flex-shrink-0" />
              <span className="font-medium text-sm">Logout</span>
            </button>
          </div>
        ) : (
          <div className="space-y-2">
            <div className="w-8 h-8 bg-gradient-to-br from-slate-200 to-slate-300 rounded-full flex items-center justify-center mx-auto">
              <User className="h-4 w-4 text-slate-600" />
            </div>
            <button
              onClick={handleLogout}
              className="w-full flex items-center justify-center p-2 rounded-lg text-slate-700 hover:bg-slate-200 transition-colors cursor-pointer"
              title="Logout"
            >
              <LogOut className="h-5 w-5 text-slate-500" />
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
