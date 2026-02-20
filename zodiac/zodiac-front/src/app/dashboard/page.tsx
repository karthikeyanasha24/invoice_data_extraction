'use client';

import { useState } from 'react';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import DashboardV2Inbound from '@/components/DashboardV2Inbound';
import DashboardV2Outbound from '@/components/DashboardV2Outbound';
import DashboardV2Business from '@/components/DashboardV2Business';
import { ArrowDownToLine, ArrowUpFromLine, TrendingUp } from 'lucide-react';
import { cn } from '@/lib/utils';

type TabId = 'inbound' | 'outbound' | 'business';

const tabs: { id: TabId; label: string; icon: React.ReactNode }[] = [
  { id: 'inbound', label: 'Inbound', icon: <ArrowDownToLine className="h-4 w-4" /> },
  { id: 'outbound', label: 'Outbound', icon: <ArrowUpFromLine className="h-4 w-4" /> },
  { id: 'business', label: 'Business', icon: <TrendingUp className="h-4 w-4" /> },
];

export default function DashboardPage() {
  const [activeTab, setActiveTab] = useState<TabId>('inbound');

  return (
    <MainLayout
      topSection={
        <TopSection
          title="Dashboard"
          subtitle="Inbound, outbound, and business analytics"
        />
      }
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        <div className="border-b border-gray-200 bg-white rounded-t-lg shadow-sm">
          <nav className="flex space-x-2 px-6" aria-label="Tabs">
            {tabs.map((tab) => {
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={cn(
                    'group relative min-w-0 flex-1 overflow-hidden py-4 px-4 text-center text-sm font-medium hover:bg-gray-50 focus:z-10 transition-all',
                    isActive
                      ? 'text-blue-600 border-b-2 border-blue-600'
                      : 'text-gray-500 hover:text-gray-700 border-b-2 border-transparent'
                  )}
                  aria-current={isActive ? 'page' : undefined}
                >
                  <div className="flex items-center justify-center space-x-2">
                    <span className={cn(isActive ? 'text-blue-600' : 'text-gray-500')}>
                      {tab.icon}
                    </span>
                    <span className="hidden sm:inline">{tab.label}</span>
                  </div>
                </button>
              );
            })}
          </nav>
        </div>
        <div className="bg-white rounded-b-lg shadow-sm border border-t-0 border-gray-200 p-6">
          {activeTab === 'inbound' && <DashboardV2Inbound />}
          {activeTab === 'outbound' && <DashboardV2Outbound />}
          {activeTab === 'business' && <DashboardV2Business />}
        </div>
      </div>
    </MainLayout>
  );
}
