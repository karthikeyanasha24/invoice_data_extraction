'use client';

import { ArrowLeft, Download, Clock } from 'lucide-react';
import { useRouter } from 'next/navigation';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

export default function ComingSoonPage() {
  const router = useRouter();

  const topSectionActions = (
    <button 
      onClick={() => router.push('/invoices')}
      className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors"
    >
      <ArrowLeft className="h-4 w-4" />
      <span>Back to Invoices</span>
    </button>
  );

  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Export"
          subtitle="Export your invoice data"
          actions={topSectionActions}
        />
      }
    >
      <div className="px-4 py-8">
        <div className="max-w-2xl mx-auto">
          <div className="bg-white rounded-lg shadow-lg p-8 text-center">
            <div className="flex justify-center mb-6">
              <div className="w-16 h-16 bg-blue-100 rounded-full flex items-center justify-center">
                <Download className="h-8 w-8 text-blue-600" />
              </div>
            </div>
            
            <h1 className="text-2xl font-bold text-gray-900 mb-4">Coming Soon</h1>
            
            <p className="text-gray-600 mb-6">
              We're working hard to bring you powerful export functionality for your invoice data. 
              This feature will allow you to export your invoices in various formats including CSV, Excel, and PDF.
            </p>
            
            <div className="bg-gray-50 rounded-lg p-6 mb-6">
              <div className="flex items-center justify-center mb-3">
                <Clock className="h-5 w-5 text-gray-500 mr-2" />
                <span className="text-sm font-medium text-gray-700">Planned Features</span>
              </div>
              <ul className="text-sm text-gray-600 space-y-2">
                <li>• Export invoices to CSV format</li>
                <li>• Export invoices to Excel format</li>
                <li>• Generate PDF reports</li>
                <li>• Custom date range filtering</li>
                <li>• Bulk export options</li>
              </ul>
            </div>
            
            <p className="text-sm text-gray-500">
              Stay tuned for updates! This feature will be available in an upcoming release.
            </p>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}


