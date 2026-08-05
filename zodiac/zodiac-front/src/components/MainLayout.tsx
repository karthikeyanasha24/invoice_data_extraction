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

  // Phase 11/12 — customer portal users must never see the admin shell
  useEffect(() => {
    if (authLoading || !user) return;
    if (isCustomerPortalUser(user)) {
      router.replace(CUSTOMER_HOME_PATH);
    }
  }, [user, authLoading, router]);

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

  // Phase 12 — no admin chrome flash while redirecting customer users
  if (authLoading || isCustomer) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader className="h-8 w-8 animate-spin text-emerald-600" aria-label="Redirecting" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 overflow-x-hidden">
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
                className="p-2 rounded-md hover:bg-gray-100 transition-colors"
                aria-label="Toggle menu"
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
