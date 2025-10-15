'use client';

import { Clock, Receipt } from 'lucide-react';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

export default function QuotationsPage() {
  const router = useRouter();

  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Quotations"
          subtitle="Manage your quotation files"
        />
      }
    >
      <div className="px-4 py-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-white rounded-lg shadow-lg p-8 text-center">
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 bg-gradient-to-br from-blue-100 to-indigo-100 rounded-full flex items-center justify-center">
                <Receipt className="h-8 w-8 text-blue-600" />
              </div>
            </div>
            
            <h2 className="text-2xl font-bold text-gray-900 mb-4">Coming Soon</h2>
            
            <p className="text-gray-600 mb-6 max-w-md mx-auto">
              The Quotations section is currently under development. We're working hard to bring you a comprehensive quotation management system.
            </p>
            
            <div className="flex items-center justify-center space-x-2 text-sm text-gray-500 mb-8">
              <Clock className="h-4 w-4" />
              <span>Expected release: Q2 2025</span>
            </div>
            
            <div className="bg-gray-50 rounded-lg p-6 mb-6">
              <h3 className="text-lg font-semibold text-gray-900 mb-3">What to expect:</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-left">
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">Quotation creation and editing</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">Template management</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">Client management</span>
                  </div>
                </div>
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">PDF generation</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">Email integration</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                    <span className="text-sm text-gray-700">Analytics and reporting</span>
                  </div>
                </div>
              </div>
            </div>
            
            <div className="flex flex-col sm:flex-row gap-3 justify-center">
              <button
                onClick={() => router.push('/invoices')}
                className="px-6 py-3 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
              >
                Manage Invoices
              </button>
              <button
                onClick={() => router.push('/dashboard')}
                className="px-6 py-3 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors"
              >
                Back to Dashboard
              </button>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
