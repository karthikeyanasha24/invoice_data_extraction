'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Invoice } from '@/types';
import { Upload, FileText, BarChart3, Activity, LogOut, User, Eye, MessageCircle, Share2, Trash2, Download, Trash, Settings } from 'lucide-react';
import { cn } from '@/lib/utils';
import AIAssistantPanel from './AIAssistantPanel';
import SuccessfulInvoiceModal from './SuccessfulInvoiceModal';
import DeleteConfirmationModal from './DeleteConfirmationModal';
import { useRouter } from 'next/navigation';

interface DashboardProps {
  initialTab?: 'overview' | 'invoices' | 'upload' | 'recycle';
  initialShowAI?: boolean;
}

export default function Dashboard({ initialTab = 'overview', initialShowAI = false }: DashboardProps) {
  const router = useRouter();
  const { user, logout, handleAuthError } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState<'overview' | 'invoices' | 'upload' | 'recycle'>(initialTab);
  const [uploadError, setUploadError] = useState('');
  const [uploadSuccess, setUploadSuccess] = useState('');
  const [latestInvoice, setLatestInvoice] = useState<Invoice | null>(null);
  const [uploading, setUploading] = useState(false);
  
  // Counts state
  const [counts, setCounts] = useState({
    successful: 0,
    failed: 0,
    deleted: 0,
    total: 0,
    processing: 0
  });
  
  // Panel states
  const [showAIAssistant, setShowAIAssistant] = useState(initialShowAI);
  const [selectedSuccessfulInvoice, setSelectedSuccessfulInvoice] = useState<Invoice | null>(null);
  const [showSuccessfulModal, setShowSuccessfulModal] = useState(false);
  
  // Delete states
  const [deletedInvoices, setDeletedInvoices] = useState<Invoice[]>([]);
  const [selectedInvoiceToDelete, setSelectedInvoiceToDelete] = useState<Invoice | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showPermanentDeleteModal, setShowPermanentDeleteModal] = useState(false);
  const [selectedInvoiceToPermanentDelete, setSelectedInvoiceToPermanentDelete] = useState<Invoice | null>(null);

  useEffect(() => {
    fetchInvoices();
    fetchDeletedInvoices();
    fetchCounts();
  }, []);

  const fetchCounts = async () => {
    console.log('📊 Dashboard - Fetching counts...');
    try {
      const data = await fileApi.getInvoiceCounts();
      console.log('📊 Dashboard - Counts data received:', data);
      setCounts(data);
    } catch (error: any) {
      console.error('📊 Dashboard - Failed to fetch counts:', error);
      
      // Check if it's an authentication error
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        console.log('📊 Dashboard - Authentication error detected, redirecting to login');
        handleAuthError();
        return;
      }
      
      // Don't show error to user here, just log it and keep default counts
    }
  };

  const fetchInvoices = async () => {
    console.log('📊 Dashboard - Fetching invoices...');
    try {
      const data = await fileApi.getFiles();
      console.log('📊 Dashboard - Raw invoice data received:', data);
      
      // Ensure all invoices have proper structure
      const sanitizedData = data.map((invoice, index) => ({
        ...invoice,
        id: invoice.id || `temp-${index}-${Date.now()}`, // Ensure unique ID
        status: invoice.status || 'Unknown',
        customerName: invoice.customerName || 'N/A',
        formate: invoice.formate || 'N/A',
        export: invoice.export || false
      }));
      
      console.log('📊 Dashboard - Sanitized invoice data:', sanitizedData);
      
      // Check for duplicate IDs
      const ids = sanitizedData.map(inv => inv.id);
      const uniqueIds = new Set(ids);
      if (ids.length !== uniqueIds.size) {
        console.warn('📊 Dashboard - Duplicate IDs detected:', ids);
      }
      
      setInvoices(sanitizedData);
    } catch (error: any) {
      console.error('📊 Dashboard - Failed to fetch invoices:', error);
      
      // Check if it's an authentication error
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        console.log('📊 Dashboard - Authentication error detected, redirecting to login');
        handleAuthError();
        return;
      }
      
      // Don't show error to user here, just log it and show empty state
      setInvoices([]);
    } finally {
      setLoading(false);
    }
  };

  const fetchDeletedInvoices = async () => {
    console.log('🗑️ Dashboard - Fetching deleted invoices...');
    try {
      const data = await fileApi.getDeletedFiles();
      console.log('🗑️ Dashboard - Deleted invoices data received:', data);
      
      setDeletedInvoices(data);
    } catch (error: any) {
      console.error('🗑️ Dashboard - Failed to fetch deleted invoices:', error);
      
      // Check if it's an authentication error
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        console.log('🗑️ Dashboard - Authentication error detected, redirecting to login');
        handleAuthError();
        return;
      }
      
      // Don't show error to user here, just log it and show empty state
      setDeletedInvoices([]);
    }
  };

  const handleFileUpload = async (file: File) => {
    console.log('📤 Dashboard - File upload started:', { 
      fileName: file.name, 
      fileSize: file.size, 
      fileType: file.type 
    });
    
    // This function should never throw - all errors are handled locally
    setUploading(true);
    
    try {
      // Client-side validation
      const allowedTypes = ['.edi', '.xml', '.txt', '.x12'];
      const fileExtension = '.' + file.name.split('.').pop()?.toLowerCase();
      
      console.log('📤 Dashboard - Client validation:', { 
        fileExtension, 
        allowedTypes, 
        isValidType: allowedTypes.includes(fileExtension),
        fileSize: file.size,
        sizeLimit: 10 * 1024 * 1024,
        isValidSize: file.size <= 10 * 1024 * 1024
      });
      
      if (!allowedTypes.includes(fileExtension)) {
        console.warn('📤 Dashboard - Invalid file type:', fileExtension);
        setUploadError('Please upload EDI, XML, TXT, or X12 files only.');
        setTimeout(() => setUploadError(''), 10000);
        return;
      }

      if (file.size > 10 * 1024 * 1024) {
        console.warn('📤 Dashboard - File too large:', file.size);
        setUploadError('File size must be less than 10MB.');
        setTimeout(() => setUploadError(''), 10000);
        return;
      }
      
      // Clear any previous messages
      setUploadError('');
      setUploadSuccess('');
      
      console.log('📤 Dashboard - Calling API upload...');
      // Attempt upload - this should never throw
      const result = await fileApi.uploadFile(file);
      
      console.log('📤 Dashboard - Upload result:', result);
      
      if (result.success && result.data) {
        console.log('📤 Dashboard - Upload successful, updating invoice list');
        
        // Convert FileUploadResponse to Invoice format
        const newInvoice: Invoice = {
          id: result.data.tracking_id || Date.now().toString(),
          filename: file.name, // Use the uploaded file name
          status: result.data.invoice_operation_success ? 'success' : 'failed',
          accepted: result.data.invoice_operation_success ? 1 : 0,
          rejected: result.data.invoice_operation_success ? 0 : 1,
          customerName: 'N/A',
          formate: 'N/A',
          export: false,
          uploaded_at: new Date().toISOString(),
          tracking_id: result.data.tracking_id,
          xml_validation_pass: result.data.xml_validation_pass,
          xml_convert_message: result.data.xml_convert_message,
          edi_convert_pass: result.data.edi_convert_pass,
          edi_convert_message: result.data.edi_convert_message,
          warnings: result.warnings || [],
          processing_steps: result.data.processing_steps || []
        };
        
        setInvoices(prev => [newInvoice, ...prev]);
        setLatestInvoice(newInvoice);
        
        // Refresh counts after successful upload
        await fetchCounts();
        
        // Show success message with navigation options
        const successMessage = result.data.invoice_operation_success 
          ? `File "${file.name}" processed successfully!`
          : `File "${file.name}" uploaded but processing failed.`;
        
        setUploadSuccess(successMessage);
        
        // Clear success message after 8 seconds (longer for user to read)
        setTimeout(() => setUploadSuccess(''), 8000);
        
      } else if (result.isProcessingError && result.data) {
        console.log('📤 Dashboard - Processing error, updating invoice list');
        
        // Handle processing failure (file uploaded but processing failed)
        const newInvoice: Invoice = {
          id: result.data.tracking_id || Date.now().toString(),
          filename: file.name,
          status: 'failed',
          accepted: 0,
          rejected: 1,
          customerName: 'N/A',
          formate: 'N/A',
          export: false,
          uploaded_at: new Date().toISOString(),
          tracking_id: result.data.tracking_id,
          xml_validation_pass: result.data.xml_validation_pass,
          xml_convert_message: result.data.xml_convert_message,
          edi_convert_pass: result.data.edi_convert_pass,
          edi_convert_message: result.data.edi_convert_message,
          warnings: result.warnings || [],
          processing_steps: result.data.processing_steps || []
        };
        
        setInvoices(prev => [newInvoice, ...prev]);
        setLatestInvoice(newInvoice);
        
        // Refresh counts after processing failure
        await fetchCounts();
        
        setUploadSuccess(`File "${file.name}" uploaded but processing failed. Check details for more information.`);
        
        // Clear success message after 8 seconds
        setTimeout(() => setUploadSuccess(''), 8000);
        
      } else {
        console.error('📤 Dashboard - Upload failed:', result.error);
        
        // Check if it's an authentication error
        if (result.error?.includes('Session expired') || result.error?.includes('log in again')) {
          console.log('📤 Dashboard - Authentication error during upload, redirecting to login');
          handleAuthError();
          return;
        }
        
        // Handle upload failure
        setUploadError(result.error || 'Upload failed. Please try again.');
        setTimeout(() => setUploadError(''), 10000);
      }
    } catch (error: any) {
      // This catch block should never be reached due to API error handling
      // But if it is, handle it gracefully without affecting the page
      console.error('📤 Dashboard - Unexpected upload error:', error);
      
      // Check if it's an authentication error
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        console.log('📤 Dashboard - Authentication error in catch block, redirecting to login');
        handleAuthError();
        return;
      }
      
      setUploadError('Upload failed. Please try again.');
      setTimeout(() => setUploadError(''), 10000);
    } finally {
      setUploading(false);
      console.log('📤 Dashboard - File upload completed');
    }
  };

  // Modal handlers
  const handleViewFailedInvoice = (invoice: Invoice) => {
    console.log('🔍 Dashboard - Navigating to failed invoice page with AI assistant:', invoice.id);
    router.push(`/failed-invoice/${invoice.id}?ai=true`);
  };

  const handleRetryInvoice = async (file: File) => {
    console.log('🔄 Dashboard - Retrying invoice with new file:', file.name);
    await handleFileUpload(file);
  };

  const handleStartLLMConversation = () => {
    setShowAIAssistant(true);
  };

  const handleShareInvoice = (invoice: Invoice) => {
    // Implement sharing functionality
    console.log('📤 Dashboard - Sharing invoice:', invoice.id);
    // This would integrate with email/WhatsApp APIs
  };

  const handleDeleteInvoice = async (invoice: Invoice) => {
    console.log('🗑️ Dashboard - Requesting to delete invoice:', invoice.id);
    setSelectedInvoiceToDelete(invoice);
    setShowDeleteModal(true);
  };

  const confirmDeleteInvoice = async () => {
    if (!selectedInvoiceToDelete) return;
    
    console.log('🗑️ Dashboard - Confirming delete for invoice:', selectedInvoiceToDelete.id);
    setIsDeleting(true);
    
    try {
      const result = await fileApi.deleteFile(Number(selectedInvoiceToDelete.id));
      
      if (result.success) {
        console.log('🗑️ Dashboard - Delete successful, refreshing data');
        
        // Refresh both active and deleted invoices from server
        await Promise.all([
          fetchInvoices(),
          fetchDeletedInvoices(),
          fetchCounts()
        ]);
        
        // Close modal
        setShowDeleteModal(false);
        setSelectedInvoiceToDelete(null);
      } else {
        console.error('🗑️ Dashboard - Delete failed:', result.error);
        // Handle error - could show a toast notification
      }
    } catch (error: any) {
      console.error('🗑️ Dashboard - Delete error:', error);
      // Handle error - could show a toast notification
    } finally {
      setIsDeleting(false);
    }
  };

  const handlePermanentDeleteClick = (invoice: Invoice) => {
    console.log('🗑️ Dashboard - Requesting permanent delete for invoice:', invoice.id);
    setSelectedInvoiceToPermanentDelete(invoice);
    setShowPermanentDeleteModal(true);
  };

  const confirmPermanentDeleteInvoice = async () => {
    if (!selectedInvoiceToPermanentDelete) return;

    console.log('🗑️ Dashboard - Confirming permanent delete for invoice:', selectedInvoiceToPermanentDelete.id);
    setIsDeleting(true);

    try {
      // TODO: Implement actual permanent delete API call
      // For now, just remove from deleted list
      setDeletedInvoices(prev => prev.filter(inv => inv.id !== selectedInvoiceToPermanentDelete.id));
      console.log('🗑️ Dashboard - Permanent delete successful');
      
      // Close modal
      setShowPermanentDeleteModal(false);
      setSelectedInvoiceToPermanentDelete(null);
    } catch (error) {
      console.error('🗑️ Dashboard - Permanent delete error:', error);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRestoreInvoice = async (invoice: Invoice) => {
    console.log('♻️ Dashboard - Restoring invoice:', invoice.id);
    
    try {
      const result = await fileApi.restoreFile(Number(invoice.id));
      
      if (result.success) {
        console.log('♻️ Dashboard - Restore successful, refreshing data');
        
        // Refresh both active and deleted invoices from server
        await Promise.all([
          fetchInvoices(),
          fetchDeletedInvoices(),
          fetchCounts()
        ]);
      } else {
        console.error('♻️ Dashboard - Restore failed:', result.error);
        // Handle error - could show a toast notification
      }
    } catch (error: any) {
      console.error('♻️ Dashboard - Restore error:', error);
      // Handle error - could show a toast notification
    }
  };

  const handleDownloadInvoice = (invoice: Invoice) => {
    console.log('⬇️ Dashboard - Downloading invoice:', invoice.id);
    // Implement download functionality
    // This would download the processed EDI file
  };

  const handleViewSuccessfulInvoice = (invoice: Invoice) => {
    console.log('🔍 Dashboard - Navigating to invoice details page:', invoice.id);
    router.push(`/invoice/${invoice.id}`);
  };

  const getStatusColor = (status?: string) => {
    if (!status) return 'bg-gray-100 text-gray-800';
    
    switch (status.toLowerCase()) {
      case 'successful':
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'processing':
        return 'bg-yellow-100 text-yellow-800';
      case 'failed':
      case 'error':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const stats = {
    totalFiles: counts.total,
    completed: counts.successful,
    processing: counts.processing,
    failed: counts.failed,
    deleted: counts.deleted,
  };

  return (
    <div className={cn(
      "min-h-screen bg-gray-50 transition-all duration-300",
      showAIAssistant ? "mr-96" : ""
    )}>
      {/* Header */}
      <header className="bg-white shadow">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center py-6">
            <div className="flex items-center">
              <h1 className="text-2xl font-bold text-gray-900">Zodiac Dashboard</h1>
            </div>
            <div className="flex items-center space-x-4">
              <div className="flex items-center space-x-2">
                <User className="h-5 w-5 text-gray-400" />
                <span className="text-sm font-medium text-gray-700">{user?.username}</span>
              </div>
              <button
                onClick={() => router.push('/settings')}
                className="flex items-center space-x-2 text-sm text-gray-500 hover:text-gray-700"
              >
                <Settings className="h-4 w-4" />
                <span>Settings</span>
              </button>
              <button
                onClick={logout}
                className="flex items-center space-x-2 text-sm text-gray-500 hover:text-gray-700"
              >
                <LogOut className="h-4 w-4" />
                <span>Logout</span>
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Navigation */}
      <nav className="bg-white border-b">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex space-x-8">
            {[
              { id: 'overview', label: 'Overview', icon: BarChart3 },
              { id: 'invoices', label: 'Invoices', icon: FileText },
              { id: 'upload', label: 'Upload', icon: Upload },
              { id: 'recycle', label: 'Recycle Bin', icon: Trash },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={cn(
                  "flex items-center space-x-2 py-4 px-1 border-b-2 font-medium text-sm",
                  activeTab === tab.id
                    ? "border-blue-500 text-blue-600"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                )}
              >
                <tab.icon className="h-5 w-5" />
                <span>{tab.label}</span>
              </button>
            ))}
          </div>
        </div>
      </nav>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        {activeTab === 'overview' && (
          <div className="space-y-6">
            {/* Stats Cards */}
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5">
              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="p-5">
                  <div className="flex items-center">
                    <div className="flex-shrink-0">
                      <FileText className="h-6 w-6 text-gray-400" />
                    </div>
                    <div className="ml-5 w-0 flex-1">
                      <dl>
                        <dt className="text-sm font-medium text-gray-500 truncate">Total Files</dt>
                        <dd className="text-lg font-medium text-gray-900">{stats.totalFiles}</dd>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="p-5">
                  <div className="flex items-center">
                    <div className="flex-shrink-0">
                      <Activity className="h-6 w-6 text-green-400" />
                    </div>
                    <div className="ml-5 w-0 flex-1">
                      <dl>
                        <dt className="text-sm font-medium text-gray-500 truncate">Completed</dt>
                        <dd className="text-lg font-medium text-gray-900">{stats.completed}</dd>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="p-5">
                  <div className="flex items-center">
                    <div className="flex-shrink-0">
                      <Activity className="h-6 w-6 text-yellow-400" />
                    </div>
                    <div className="ml-5 w-0 flex-1">
                      <dl>
                        <dt className="text-sm font-medium text-gray-500 truncate">Processing</dt>
                        <dd className="text-lg font-medium text-gray-900">{stats.processing}</dd>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="p-5">
                  <div className="flex items-center">
                    <div className="flex-shrink-0">
                      <Activity className="h-6 w-6 text-red-400" />
                    </div>
                    <div className="ml-5 w-0 flex-1">
                      <dl>
                        <dt className="text-sm font-medium text-gray-500 truncate">Failed</dt>
                        <dd className="text-lg font-medium text-gray-900">{stats.failed}</dd>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white overflow-hidden shadow rounded-lg">
                <div className="p-5">
                  <div className="flex items-center">
                    <div className="flex-shrink-0">
                      <Trash className="h-6 w-6 text-gray-400" />
                    </div>
                    <div className="ml-5 w-0 flex-1">
                      <dl>
                        <dt className="text-sm font-medium text-gray-500 truncate">Deleted</dt>
                        <dd className="text-lg font-medium text-gray-900">{stats.deleted}</dd>
                      </dl>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            {/* Recent Activity */}
            <div className="bg-white shadow rounded-lg">
              <div className="px-4 py-5 sm:p-6">
                <h3 className="text-lg leading-6 font-medium text-gray-900">Recent Activity</h3>
                <div className="mt-5">
                  {loading ? (
                    <div className="text-center py-4">Loading...</div>
                  ) : invoices.filter(inv => inv.status !== 'deleted').length === 0 ? (
                    <div className="text-center py-4 text-gray-500">No files uploaded yet</div>
                  ) : (
                    <div className="space-y-3">
                      {invoices.filter(inv => inv.status !== 'deleted').slice(0, 5).map((invoice, index) => (
                        <div key={invoice.id || `recent-${index}`} className="flex items-center justify-between py-2 border-b border-gray-200 last:border-b-0">
                          <div className="flex items-center space-x-3">
                            <FileText className="h-5 w-5 text-gray-400" />
                            <div>
                              <p className="text-sm font-medium text-gray-900">{invoice.filename}</p>
                              <p className="text-xs text-gray-500">{invoice.customerName || 'No customer'}</p>
                            </div>
                          </div>
                          <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium", getStatusColor(invoice.status))}>
                            {invoice.status || 'Unknown'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'invoices' && (
          <div className="bg-white shadow rounded-lg">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">All Invoices</h3>
              {loading ? (
                <div className="text-center py-8">Loading...</div>
              ) : invoices.filter(inv => inv.status !== 'deleted').length === 0 ? (
                <div className="text-center py-8 text-gray-500">No invoices found</div>
              ) : (
                <div className="w-full">
                  <table className="w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Format</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Export</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {invoices.filter(inv => inv.status !== 'deleted').map((invoice, index) => (
                        <tr key={invoice.id || `invoice-${index}`}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.customerName || 'N/A'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium", getStatusColor(invoice.status))}>
                              {invoice.status || 'Unknown'}
                            </span>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.formate || 'N/A'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.export ? 'Yes' : 'No'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <div className="flex items-center space-x-2">
                              {/* View Details Button */}
                              <button
                                onClick={() => {
                                  const status = invoice.status?.toLowerCase();
                                  if (status === 'failed' || status === 'error') {
                                    handleViewFailedInvoice(invoice);
                                  } else if (status === 'successful' || status === 'completed') {
                                    handleViewSuccessfulInvoice(invoice);
                                  }
                                }}
                                className="p-1 text-gray-400 hover:text-blue-600 transition-colors"
                                title="View Details"
                              >
                                <Eye className="h-4 w-4" />
                              </button>

                              {/* Download Button (for successful invoices) */}
                              {(invoice.status?.toLowerCase() === 'successful' || invoice.status?.toLowerCase() === 'completed') && (
                                <button
                                  onClick={() => handleDownloadInvoice(invoice)}
                                  className="p-1 text-gray-400 hover:text-green-600 transition-colors"
                                  title="Download EDI File"
                                >
                                  <Download className="h-4 w-4" />
                                </button>
                              )}

                              {/* Share Button (for successful invoices) */}
                              {(invoice.status?.toLowerCase() === 'successful' || invoice.status?.toLowerCase() === 'completed') && (
                                <button
                                  onClick={() => handleShareInvoice(invoice)}
                                  className="p-1 text-gray-400 hover:text-purple-600 transition-colors"
                                  title="Share Invoice"
                                >
                                  <Share2 className="h-4 w-4" />
                                </button>
                              )}

                              {/* AI Help Button (for failed invoices) */}
                              {(invoice.status?.toLowerCase() === 'failed' || invoice.status?.toLowerCase() === 'error') && (
                                <button
                                  onClick={() => router.push(`/failed-invoice/${invoice.id}?ai=true`)}
                                  className="p-1 text-gray-400 hover:text-purple-600 transition-colors"
                                  title="Get AI Help"
                                >
                                  <MessageCircle className="h-4 w-4" />
                                </button>
                              )}

                              {/* Delete Button */}
                              <button
                                onClick={() => {
                                  console.log('🗑️ Dashboard Delete button clicked for invoice:', invoice.id, invoice.filename);
                                  handleDeleteInvoice(invoice);
                                }}
                                className="p-1 text-gray-400 hover:text-red-600 transition-colors cursor-pointer"
                                title="Delete Invoice"
                                disabled={isDeleting}
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'upload' && (
          <FileUploadComponent 
            onUpload={handleFileUpload} 
            error={uploadError}
            success={uploadSuccess}
            uploading={uploading}
            onDismissError={() => setUploadError('')}
            onDismissSuccess={() => {
              setUploadSuccess('');
              setLatestInvoice(null);
            }}
            latestInvoice={latestInvoice}
          />
        )}

        {activeTab === 'recycle' && (
          <div className="bg-white shadow rounded-lg">
            <div className="px-4 py-5 sm:p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg leading-6 font-medium text-gray-900">Recycle Bin</h3>
                <div className="text-sm text-gray-500">
                  {deletedInvoices.length} deleted item{deletedInvoices.length !== 1 ? 's' : ''}
                </div>
              </div>
              {loading ? (
                <div className="text-center py-8">Loading...</div>
              ) : deletedInvoices.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <Trash className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                  <p>No deleted invoices found</p>
                  <p className="text-sm">Deleted invoices will appear here</p>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200">
                    <thead className="bg-gray-50">
                      <tr>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">File</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Deleted</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Format</th>
                        <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="bg-white divide-y divide-gray-200">
                      {deletedInvoices.map((invoice, index) => (
                        <tr key={invoice.id || `deleted-${index}`}>
                          <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                            {invoice.filename}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.customerName || 'N/A'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.deleted_at ? new Date(invoice.deleted_at).toLocaleString() : 'Unknown'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            {invoice.formate || 'N/A'}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                            <div className="flex items-center space-x-2">
                              {/* Restore Button */}
                              <button
                                onClick={() => handleRestoreInvoice(invoice)}
                                className="p-1 text-gray-400 hover:text-green-600 transition-colors"
                                title="Restore Invoice"
                              >
                                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                                </svg>
                              </button>

                              {/* Permanent Delete Button */}
                              <button
                                onClick={() => handlePermanentDeleteClick(invoice)}
                                className="p-1 text-gray-400 hover:text-red-600 transition-colors cursor-pointer"
                                title="Permanently Delete"
                              >
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}
      </main>

      {selectedSuccessfulInvoice && (
        <SuccessfulInvoiceModal
          invoice={selectedSuccessfulInvoice}
          isOpen={showSuccessfulModal}
          onClose={() => {
            setShowSuccessfulModal(false);
            setSelectedSuccessfulInvoice(null);
          }}
          onDownload={() => handleDownloadInvoice(selectedSuccessfulInvoice)}
          onShare={() => handleShareInvoice(selectedSuccessfulInvoice)}
          onDelete={() => handleDeleteInvoice(selectedSuccessfulInvoice)}
        />
      )}

      {/* AI Assistant Panel */}
      <AIAssistantPanel
        invoiceDetails={null}
        isOpen={showAIAssistant}
        onClose={() => {
          setShowAIAssistant(false);
        }}
      />

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        invoice={selectedInvoiceToDelete}
        isOpen={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          setSelectedInvoiceToDelete(null);
        }}
        onConfirm={confirmDeleteInvoice}
        isDeleting={isDeleting}
      />
    </div>
  );
}

function FileUploadComponent({ onUpload, error, success, uploading, onDismissError, onDismissSuccess, latestInvoice }: { 
  onUpload: (file: File) => void; 
  error: string; 
  success: string; 
  uploading: boolean;
  onDismissError: () => void;
  onDismissSuccess: () => void;
  latestInvoice?: Invoice | null;
}) {
  const [dragActive, setDragActive] = useState(false);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      await handleFile(e.dataTransfer.files[0]);
    }
  };

  const handleFile = async (file: File) => {
    // This should never throw - all errors are handled in the parent
    await onUpload(file);
  };

  const handleChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      await handleFile(e.target.files[0]);
    }
  };

  return (
    <div className="bg-white shadow rounded-lg">
      <div className="px-4 py-5 sm:p-6">
        <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">Upload Invoice Files</h3>
        
        {/* Upload Progress */}
        {uploading && (
          <div className="mb-4 rounded-md bg-blue-50 p-4">
            <div className="flex items-center">
              <div className="flex-shrink-0">
                <div className="animate-spin rounded-full h-5 w-5 border-2 border-blue-300 border-t-blue-600"></div>
              </div>
              <div className="ml-3">
                <h3 className="text-sm font-medium text-blue-800">Uploading...</h3>
                <div className="mt-1 text-sm text-blue-700">Please wait while your file is being processed.</div>
              </div>
            </div>
          </div>
        )}
        
        {/* Error Message */}
        {error && (
          <div className="mb-4 rounded-md bg-red-50 p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-red-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3 flex-1">
                <h3 className="text-sm font-medium text-red-800">Upload Error</h3>
                <div className="mt-2 text-sm text-red-700">{error}</div>
                <div className="mt-3">
                  <button
                    onClick={onDismissError}
                    className="text-sm bg-red-100 text-red-800 px-3 py-1 rounded-md hover:bg-red-200 focus:outline-none focus:ring-2 focus:ring-red-500"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Success Message */}
        {success && (
          <div className="mb-4 rounded-md bg-green-50 p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg className="h-5 w-5 text-green-400" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
                </svg>
              </div>
              <div className="ml-3 flex-1">
                <h3 className="text-sm font-medium text-green-800">Upload Successful</h3>
                <div className="mt-2 text-sm text-green-700">{success}</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    onClick={onDismissSuccess}
                    className="text-sm bg-green-100 text-green-800 px-3 py-1 rounded-md hover:bg-green-200 focus:outline-none focus:ring-2 focus:ring-green-500"
                  >
                    Dismiss
                  </button>
                  {latestInvoice && (
                    <>
                      <button
                        onClick={() => {
                          const status = latestInvoice.status?.toLowerCase();
                          if (status === 'failed' || status === 'error') {
                            window.location.href = `/failed-invoice/${latestInvoice.id}?ai=true`;
                          } else if (status === 'successful' || status === 'completed') {
                            window.location.href = `/invoice/${latestInvoice.id}`;
                          }
                        }}
                        className="text-sm bg-blue-100 text-blue-800 px-3 py-1 rounded-md hover:bg-blue-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
                      >
                        View Details
                      </button>
                      <button
                        onClick={() => window.location.href = '/invoices'}
                        className="text-sm bg-gray-100 text-gray-800 px-3 py-1 rounded-md hover:bg-gray-200 focus:outline-none focus:ring-2 focus:ring-gray-500"
                      >
                        View All Invoices
                      </button>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
        
        <div
          className={cn(
            "border-2 border-dashed rounded-lg p-6 text-center",
            dragActive ? "border-blue-400 bg-blue-50" : "border-gray-300",
            uploading && "opacity-50"
          )}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          {uploading ? (
            <div className="text-center">
              <div className="mx-auto h-12 w-12 text-blue-500 animate-spin">
                <svg className="h-12 w-12" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
              </div>
              <div className="mt-4">
                <span className="block text-sm font-medium text-blue-900">Processing Invoice...</span>
                <div className="mt-2 space-y-1">
                  <div className="flex items-center justify-center space-x-2 text-xs text-blue-700">
                    <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse"></div>
                    <span>Uploading file</span>
                  </div>
                  <div className="flex items-center justify-center space-x-2 text-xs text-gray-500">
                    <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                    <span>Validating XML format</span>
                  </div>
                  <div className="flex items-center justify-center space-x-2 text-xs text-gray-500">
                    <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                    <span>Converting to EDI</span>
                  </div>
                  <div className="flex items-center justify-center space-x-2 text-xs text-gray-500">
                    <div className="w-2 h-2 bg-gray-300 rounded-full"></div>
                    <span>Validating EDI format</span>
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <>
              <Upload className="mx-auto h-12 w-12 text-gray-400" />
              <div className="mt-4">
                <label htmlFor="file-upload" className="cursor-pointer">
                  <span className="mt-2 block text-sm font-medium text-gray-900">
                    Drop files here or click to upload
                  </span>
                  <span className="mt-1 block text-sm text-gray-500">
                    Supports EDI, XML, TXT, and X12 files (max 10MB)
                  </span>
                </label>
              </div>
            </>
          )}
          <input
            id="file-upload"
            name="file-upload"
            type="file"
            className="sr-only"
            onChange={handleChange}
            disabled={uploading}
            accept=".edi,.xml,.txt,.x12"
          />
        </div>
      </div>
    </div>
  );
}
