'use client';

import { useState } from 'react';
import { BarChart3, Activity, TrendingUp, Brain } from 'lucide-react';
import { cn } from '@/lib/utils';

interface Tab {
  id: string;
  label: string;
  icon: React.ReactNode;
  description: string;
}

const tabs: Tab[] = [
  {
    id: 'overview',
    label: 'Overview',
    icon: <BarChart3 className="h-4 w-4" />,
    description: 'General statistics and insights'
  },
  {
    id: 'operations',
    label: 'Operations',
    icon: <Activity className="h-4 w-4" />,
    description: 'Message flow and auto-fix analytics'
  },
  {
    id: 'business',
    label: 'Business',
    icon: <TrendingUp className="h-4 w-4" />,
    description: 'Revenue and cost analysis (Coming Soon)'
  },
  {
    id: 'analytics',
    label: 'Analytics',
    icon: <Brain className="h-4 w-4" />,
    description: 'Advanced insights and trends (Coming Soon)'
  },
];

interface DashboardTabsProps {
  activeTab: string;
  onTabChange: (tabId: string) => void;
}

export default function DashboardTabs({ activeTab, onTabChange }: DashboardTabsProps) {
  return (
    <div className="border-b border-gray-200 bg-white rounded-t-lg shadow-sm">
      <nav className="flex space-x-2 px-6" aria-label="Tabs">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          const isDisabled = tab.description.includes('Coming Soon');
          
          return (
            <button
              key={tab.id}
              onClick={() => !isDisabled && onTabChange(tab.id)}
              disabled={isDisabled}
              className={cn(
                'group relative min-w-0 flex-1 overflow-hidden py-4 px-4 text-center text-sm font-medium hover:bg-gray-50 focus:z-10 transition-all',
                isActive
                  ? 'text-blue-600 border-b-2 border-blue-600'
                  : isDisabled
                  ? 'text-gray-400 cursor-not-allowed'
                  : 'text-gray-500 hover:text-gray-700 border-b-2 border-transparent'
              )}
              aria-current={isActive ? 'page' : undefined}
              title={tab.description}
            >
              <div className="flex items-center justify-center space-x-2">
                <span className={cn(
                  isActive ? 'text-blue-600' : isDisabled ? 'text-gray-400' : 'text-gray-500'
                )}>
                  {tab.icon}
                </span>
                <span className="hidden sm:inline">{tab.label}</span>
              </div>
              
              {/* Active indicator */}
              {isActive && (
                <span
                  className="absolute inset-x-0 bottom-0 h-0.5 bg-blue-600"
                  aria-hidden="true"
                />
              )}
              
              {/* Coming Soon badge */}
              {isDisabled && (
                <span className="absolute top-1 right-1 inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-600">
                  Soon
                </span>
              )}
            </button>
          );
        })}
      </nav>
    </div>
  );
}

