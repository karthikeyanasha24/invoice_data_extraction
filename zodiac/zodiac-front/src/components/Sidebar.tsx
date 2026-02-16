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
  Key
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';

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

  const menuItems = [
    {
      id: 'dashboard',
      label: 'Dashboard',
      icon: LayoutDashboard,
      path: '/dashboard',
      description: 'Overview and analytics'
    },
    {
      id: 'invoices',
      label: 'Invoices',
      icon: FileText,
      path: '/invoices-v2',
      description: 'Manage and validate invoices'
    },
    {
      id: 'quotations',
      label: 'Quotations',
      icon: Receipt,
      path: '/quotations',
      description: 'Manage quotation files'
    },
    {
      id: 'customers',
      label: 'Customers',
      icon: Building2,
      path: '/customers',
      description: 'Manage EDI customers'
    },
    {
      id: 'sat-documents',
      label: 'SAT Documents',
      icon: Receipt,
      path: '/sat-documents',
      description: 'CFDI documents & SAP integration'
    },
    {
      id: 'account-mapping',
      label: 'Account Mapping',
      icon: Settings,
      path: '/admin/account-mapping',
      description: 'RFC to SAP G/L mapping'
    },
    {
      id: 'supplier-tokens',
      label: 'Supplier Tokens',
      icon: Key,
      path: '/admin/supplier-tokens',
      description: 'Manage supplier API tokens'
    },
    {
      id: 'settings',
      label: 'Settings',
      icon: Settings,
      path: '/settings',
      description: 'Account and preferences'
    }
  ];

  const handleNavigation = (path: string) => {
    router.push(path);
  };

  const handleLogout = () => {
    logout();
    // Redirect to sign-in page after logout
    router.push('/');
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
                <span className="font-semibold text-slate-900 text-sm sm:text-base truncate block">Zodiac</span>
                <p className="text-xs text-slate-500 truncate">Document Management</p>
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
            const isActive = pathname === item.path || pathname.startsWith(item.path + '/');
            
            return (
              <button
                key={item.id}
                onClick={() => handleNavigation(item.path)}
                className={cn(
                  "w-full flex items-center space-x-3 px-3 py-2.5 rounded-lg text-left transition-all duration-200 group cursor-pointer",
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
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm truncate">{item.label}</div>
                    <div className="text-xs text-slate-500 truncate">{item.description}</div>
                  </div>
                )}
              </button>
            );
          })}
        </div>
      </nav>

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
