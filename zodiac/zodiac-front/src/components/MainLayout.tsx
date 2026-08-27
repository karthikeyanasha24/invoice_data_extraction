'use client';

import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import { cn } from '@/lib/utils';
import { Menu, Loader } from 'lucide-react';
import { useAuth } from '@/contexts/AuthContext';
import { CUSTOMER_HOME_PATH, isCustomerPortalUser } from '@/lib/customerPortal';

interface MainLayoutProps {
  children: React.ReactNode;
  topSection?: React.ReactNode;
  /** Full-height page with no outer padding (e.g. AI copilot). */
  fillViewport?: boolean;
}

export default function MainLayout({ children, topSection, fillViewport = false }: MainLayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading: authLoading } = useAuth();

  const isCustomer = !authLoading && !!user && isCustomerPortalUser(user);

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      const next = pathname && pathname !== '/' ? `/?next=${encodeURIComponent(pathname)}` : '/';
      router.replace(next);
      return;
    }
    if (isCustomerPortalUser(user)) {
      router.replace(CUSTOMER_HOME_PATH);
    }
  }, [user, authLoading, router, pathname]);

  useEffect(() => {
    const checkMobile = () => {
      setIsMobile(window.innerWidth < 1024);
      if (window.innerWidth < 1024) {
        setMobileSidebarOpen(false);
      }
    };

    checkMobile();
    window.addEventListener('resize', checkMobile);
    return () => window.removeEventListener('resize', checkMobile);
  }, []);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [pathname]);

  const toggleSidebar = () => {
    if (isMobile) {
      setMobileSidebarOpen(!mobileSidebarOpen);
    } else {
      setSidebarCollapsed(!sidebarCollapsed);
    }
  };

  if (authLoading) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" aria-label="Checking your session" />
        <p className="text-sm font-medium text-slate-700">Checking your session…</p>
        <p className="text-xs text-slate-500">Protected pages require you to be signed in.</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" aria-label="Redirecting to sign in" />
        <p className="text-sm font-medium text-slate-700">Redirecting to sign in…</p>
        <p className="text-xs text-slate-500">You need an account to open this page.</p>
      </div>
    );
  }

  if (isCustomer) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-slate-50 px-6 text-center">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" aria-label="Redirecting" />
        <p className="text-sm font-medium text-slate-700">Opening your workspace…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 overflow-x-hidden">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[100] focus:rounded-md focus:bg-emerald-800 focus:px-3 focus:py-2 focus:text-white"
      >
        Skip to content
      </a>
      <div className="flex relative">
        {isMobile && mobileSidebarOpen && (
          <div
            className="fixed inset-0 bg-opacity-50 z-40 lg:hidden"
            onClick={() => setMobileSidebarOpen(false)}
          />
        )}

        <div
          className={cn(
            'fixed lg:relative z-50',
            isMobile && !mobileSidebarOpen && '-translate-x-full lg:translate-x-0'
          )}
        >
          <Sidebar
            isCollapsed={sidebarCollapsed}
            onToggle={toggleSidebar}
            isMobile={isMobile}
            mobileOpen={mobileSidebarOpen}
          />
        </div>

        <div
          className={cn(
            'flex-1 transition-all duration-300 flex flex-col min-w-0 w-full',
            fillViewport && 'h-screen overflow-hidden',
            !isMobile && (sidebarCollapsed ? 'lg:ml-16' : 'lg:ml-64')
          )}
        >
          {isMobile && (
            <div className="sticky top-0 z-30 bg-white border-b border-gray-200 px-4 py-3 lg:hidden">
              <button
                onClick={toggleSidebar}
                className="p-2 rounded-md hover:bg-gray-100 transition-colors min-h-11 min-w-11"
                aria-label="Open navigation menu"
                aria-expanded={mobileSidebarOpen}
              >
                <Menu className="h-6 w-6 text-gray-600" />
              </button>
            </div>
          )}

          {topSection && (
            <div className="sticky top-0 lg:top-0 z-20 bg-white border-b border-gray-200 shadow-sm">
              <div className="py-3 sm:py-4">{topSection}</div>
            </div>
          )}

          <main
            id="main-content"
            className={cn(
              'flex-1 min-h-0',
              fillViewport ? 'overflow-hidden flex flex-col' : 'overflow-auto'
            )}
          >
            <div
              className={cn(
                'w-full min-w-0',
                fillViewport ? 'flex-1 flex flex-col min-h-0' : 'p-4 sm:p-6'
              )}
            >
              {children}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
