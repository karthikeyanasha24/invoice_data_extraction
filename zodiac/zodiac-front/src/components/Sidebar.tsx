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
  AlertCircle,
  MapPin,
  Boxes,
  ArrowDownToLine,
  type LucideIcon,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import { adminNavGroups, isNavActive, type NavItem } from '@/lib/navConfig';

// ── Environment detection ─────────────────────────────────────────────────────
const API_URL = (process.env.NEXT_PUBLIC_API_URL || '').trim();
const IS_LOCAL  = !API_URL || API_URL.includes('localhost') || API_URL.includes('127.0.0.1');
const ENV_COLOR = 'bg-amber-100 text-amber-800 border-amber-300';
const ENV_DOT   = 'bg-amber-400';
const ENV_TIP   =
  `Connecting to: ${API_URL || 'localhost:8000'}\nLocal API. The database behind this API may still contain SAP demo data.`;
const ENV_LABEL = 'Local development';

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
  const workspaceUiEnabled = process.env.NEXT_PUBLIC_WORKSPACE_UI !== 'false';
  const ICONS: Record<string, LucideIcon> = {
    LayoutDashboard,
    Sparkles,
    ArrowDownToLine,
    FileText,
    Receipt,
    Building2,
    Boxes,
    Users,
    MapPin,
    Key,
    Settings,
  };
  const navGroups = adminNavGroups({
    isAdmin: !!user?.is_admin,
    workspaceUi: workspaceUiEnabled,
  });
  const customerUserMenuItems: NavItem[] = [
    { id: 'customer-portal', label: 'Customer Portal', icon: 'Boxes', path: '/customer/overview', description: 'Your exclusive workspace' },
  ];

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
              <div className="w-7 h-7 sm:w-8 sm:h-8 bg-emerald-800 rounded-lg flex items-center justify-center flex-shrink-0">
                <span className="text-white font-bold text-sm">B</span>
              </div>
              <div className="min-w-0">
                <span className="font-semibold text-slate-900 text-sm sm:text-base truncate block">BridgeEDI</span>
                <p className="text-xs text-slate-500 truncate">Governed SAP intelligence</p>
              </div>
            </div>
          )}
          {!isMobile && (
            <button
              onClick={onToggle}
              className="p-1.5 rounded-md hover:bg-slate-200 transition-colors flex-shrink-0 cursor-pointer"
              aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
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
              aria-label="Close menu"
              title="Close menu"
            >
              <ChevronLeft className="h-5 w-5 text-slate-500" />
            </button>
          )}
        </div>
      </div>

      {/* Navigation Menu */}
      <nav className="flex-1 p-3 sm:p-4 overflow-y-auto" aria-label="Main">
        {isCustomerUser ? (
          <div className="space-y-1">
            {customerUserMenuItems.map((item) => {
              const Icon = ICONS[item.icon] || Boxes;
              return (
                <button
                  key={item.id}
                  onClick={() => handleNavigation(item.path)}
                  className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-left text-slate-700 hover:bg-slate-50"
                >
                  <Icon className="h-5 w-5 text-slate-500" />
                  {(!isCollapsed || isMobile) && <span className="text-sm font-medium">{item.label}</span>}
                </button>
              );
            })}
          </div>
        ) : (
          <div className="space-y-4">
            {navGroups.map((group) => (
              <div key={group.id}>
                {(!isCollapsed || isMobile) && (
                  <p className="px-3 mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                    {group.label}
                  </p>
                )}
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const Icon = ICONS[item.icon] || LayoutDashboard;
                    const isActive = isNavActive(pathname, item);
                    return (
                      <button
                        key={item.id}
                        onClick={() => handleNavigation(item.path)}
                        className={cn(
                          'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors min-w-0',
                          isActive
                            ? 'bg-emerald-50 text-emerald-900 border border-emerald-200'
                            : 'text-slate-700 hover:bg-slate-50'
                        )}
                        title={isCollapsed && !isMobile ? item.label : item.description}
                      >
                        <Icon className={cn('h-5 w-5 flex-shrink-0', isActive ? 'text-emerald-800' : 'text-slate-500')} />
                        {(!isCollapsed || isMobile) && (
                          <div className="flex-1 min-w-0 overflow-hidden">
                            <div className="font-medium text-sm truncate">{item.label}</div>
                          </div>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </nav>

      {/* Environment Indicator — local only; do not show production/debug chrome to business users */}
      {IS_LOCAL && (!isCollapsed || isMobile) && (
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
            <AlertCircle className="h-3 w-3 flex-shrink-0 text-amber-600" />
          </div>
          <p className="text-[10px] text-amber-700 mt-1 px-1 leading-tight">
            Connecting to local API. SAP demo data may still be present in the configured database.
          </p>
        </div>
      )}
      {IS_LOCAL && isCollapsed && !isMobile && (
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
