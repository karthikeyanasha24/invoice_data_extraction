'use client';

import Link from 'next/link';

interface FooterProps {
  className?: string;
}

export default function Footer({ className = '' }: FooterProps) {
  return (
    <footer className={`bg-slate-50 border-t border-slate-200 py-6 ${className}`}>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex flex-col sm:flex-row items-center justify-between space-y-2 sm:space-y-0">
          <div className="flex items-center space-x-2">
            <div className="w-6 h-6 bg-emerald-800 rounded-md flex items-center justify-center">
              <span className="text-white font-bold text-xs">B</span>
            </div>
            <span className="text-sm text-slate-600">Powered by</span>
            <Link 
              href="https://abor-tech.com/" 
              target="_blank" 
              rel="noopener noreferrer"
              className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors"
            >
              Abor-Tech Ltd.
            </Link>
          </div>
          <div className="text-sm text-slate-500">
            © 2025 Abor-Tech Ltd. All rights reserved.
          </div>
        </div>
      </div>
    </footer>
  );
}

