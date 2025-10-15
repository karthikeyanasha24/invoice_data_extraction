'use client';

import { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface TopSectionProps {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}

export default function TopSection({ 
  title, 
  subtitle, 
  actions, 
  className 
}: TopSectionProps) {
  return (
    <div className={cn("flex items-center justify-between px-4 sm:px-6", className)}>
      <div className="flex-1 min-w-0">
        <h1 className="text-xl sm:text-2xl font-bold text-gray-900 truncate">{title}</h1>
        {subtitle && (
          <p className="mt-1 text-sm text-gray-600 truncate">{subtitle}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center space-x-2 sm:space-x-3 ml-4 flex-shrink-0">
          {actions}
        </div>
      )}
    </div>
  );
}
