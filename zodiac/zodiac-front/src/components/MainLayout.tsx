'use client';

import { useState } from 'react';
import { usePathname } from 'next/navigation';
import Sidebar from '@/components/Sidebar';
import { cn } from '@/lib/utils';

interface MainLayoutProps {
  children: React.ReactNode;
  topSection?: React.ReactNode;
}

export default function MainLayout({ children, topSection }: MainLayoutProps) {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const pathname = usePathname();

  const toggleSidebar = () => {
    setSidebarCollapsed(!sidebarCollapsed);
  };

  return (
    <div className="min-h-screen bg-gray-50 overflow-x-hidden">
      <div className="flex">
        {/* Sidebar */}
        <Sidebar isCollapsed={sidebarCollapsed} onToggle={toggleSidebar} />
        
        {/* Main Content Area */}
        <div className={cn(
          "flex-1 transition-all duration-300 flex flex-col min-w-0",
          sidebarCollapsed ? "ml-16" : "ml-64"
        )}>
          {/* Fixed Top Section */}
          {topSection && (
            <div className="sticky top-0 z-10 bg-white border-b border-gray-200 shadow-sm">
              <div className="py-4">
                {topSection}
              </div>
            </div>
          )}
          
          {/* Scrollable Main Content */}
          <main className="flex-1 overflow-auto">
            <div className="w-full min-w-0">
              {children}
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}
