'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { fileApi } from '@/lib/api';
import { Invoice } from '@/types';
import {
  FileText,
  Search,
  Download,
  Trash2,
  Eye,
  MessageCircle,
  Share2,
  CheckCircle,
  XCircle,
  RotateCcw,
  Trash,
  Upload,
  Clock,
  X,
  Cloud,
  MousePointer,
  Filter
} from 'lucide-react';
import { cn } from '@/lib/utils';
import Pagination from '@/components/Pagination';
import LoadingSpinner from '@/components/LoadingSpinner';
import DeleteConfirmationModal from '@/components/DeleteConfirmationModal';
import RestoreConfirmationModal from '@/components/RestoreConfirmationModal';

export default function InvoicesLanding() {
  const router = useRouter();
  const { user, isAuthenticated, handleAuthError } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [deletedInvoices, setDeletedInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [initialLoadComplete, setInitialLoadComplete] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(10);
  const [showRecycleBin, setShowRecycleBin] = useState(false);
  const [sourceFilter, setSourceFilter] = useState<'all' | 'api' | 'web'>('all'); // Filter by source

  // Delete confirmation modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedInvoiceToDelete, setSelectedInvoiceToDelete] = useState<Invoice | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Restore confirmation modal state
  const [showRestoreModal, setShowRestoreModal] = useState(false);
  const [selectedInvoiceToRestore, setSelectedInvoiceToRestore] = useState<Invoice | null>(null);
  const [isRestoring, setIsRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  useEffect(() => {
    if (isAuthenticated) {
      fetchInvoices();
      // Don't fetch deleted invoices until user opens recycle bin
      // fetchDeletedInvoices(); 
    } else {
      setLoading(false);
    }
  }, [isAuthenticated]);

  const fetchInvoices = async () => {
    setLoading(true); // Ensure loading state is set
    try {
      const data = await fileApi.getFiles();
      console.log("📊 TOTAL INVOICES RECEIVED:", data.length);
      
      // Log the first invoice to see all available fields
      if (data.length > 0) {
        console.log("📊 FIRST INVOICE COMPLETE DATA:", data[0]);
        console.log("📊 AVAILABLE FIELDS:", Object.keys(data[0]));
        console.log("📊 invoice_id value:", data[0].customerId);
        console.log("📊 customerName value:", data[0].customerName);
      }
      
      setInvoices(data);
      
      // Ensure loading screen is visible for at least 500ms for better UX
      await new Promise(resolve => setTimeout(resolve, 500));
    } catch (error: any) {
      console.error('Failed to fetch invoices:', error);
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
      setInitialLoadComplete(true);
    }
  };

  const fetchDeletedInvoices = async () => {
    try {
      const data = await fileApi.getDeletedFiles();
      setDeletedInvoices(data);
    } catch (error: any) {
      console.error('Failed to fetch deleted invoices:', error);
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
      }
    }
  };
  console.log(invoices, "invoices initial")

  // Filter and search invoices based on current view
  const filteredInvoices = showRecycleBin
    ? deletedInvoices.filter(invoice => {
      // Check if search term is empty - show all
      if (!searchTerm) return true;
      
      const searchLower = searchTerm.toLowerCase();
      const matchesSearch = invoice.filename?.toLowerCase().includes(searchLower) ||
        invoice.customerName?.toLowerCase().includes(searchLower) ||
        invoice.status?.toLowerCase().includes(searchLower);
      return matchesSearch;
    })
    : invoices.filter(invoice => {
      // Exclude deleted invoices
      if (invoice.status === 'deleted') return false;
      
      // Filter by source type
      if (sourceFilter !== 'all') {
        const invoiceSource = invoice.request_type || 'web'; // Default to 'web' if not set
        if (invoiceSource !== sourceFilter) return false;
      }
      
      // Check if search term is empty - show all active invoices matching source filter
      if (!searchTerm) return true;
      
      const searchLower = searchTerm.toLowerCase();
      const searchTerms = searchLower.split(' '); // Split by space to handle multiple terms
      
      // Check if any search term matches
      const matchesSearch = searchTerms.some(term => 
        invoice.filename?.toLowerCase().includes(term) ||
        invoice.customerName?.toLowerCase().includes(term) ||
        invoice.status?.toLowerCase().includes(term) ||
        invoice.customerId?.toLowerCase().includes(term)
      );
      
      return matchesSearch;
    });

  // Calculate total counts (independent of search/filter)
  const activeInvoices = invoices.filter(inv => inv.status !== 'deleted');
  const totalInvoicesCount = showRecycleBin ? deletedInvoices.length : activeInvoices.length;
  const completedCount = activeInvoices.filter(inv => inv.status === 'successful' || inv.status === 'completed').length;
  const failedCount = activeInvoices.filter(inv => inv.status === 'failed' || inv.status === 'error').length;
  const deletedCount = deletedInvoices.length;
  
  // Calculate source-based counts
  const sapInvoicesCount = activeInvoices.filter(inv => inv.request_type === 'api').length;
  const manualInvoicesCount = activeInvoices.filter(inv => !inv.request_type || inv.request_type === 'web').length;
  const sapSuccessCount = activeInvoices.filter(inv => inv.request_type === 'api' && (inv.status === 'successful' || inv.status === 'completed')).length;
  const sapFailedCount = activeInvoices.filter(inv => inv.request_type === 'api' && (inv.status === 'failed' || inv.status === 'error')).length;
  const manualSuccessCount = activeInvoices.filter(inv => (!inv.request_type || inv.request_type === 'web') && (inv.status === 'successful' || inv.status === 'completed')).length;
  const manualFailedCount = activeInvoices.filter(inv => (!inv.request_type || inv.request_type === 'web') && (inv.status === 'failed' || inv.status === 'error')).length;

  const handleDeleteInvoice = async (invoice: Invoice) => {
    console.log('🗑️ InvoicesLanding - Requesting to delete invoice:', invoice.id);
    setSelectedInvoiceToDelete(invoice);
    setShowDeleteModal(true);
  };

  const confirmDeleteInvoice = async () => {
    if (!selectedInvoiceToDelete) return;

    console.log('🗑️ InvoicesLanding - Confirming delete for invoice:', selectedInvoiceToDelete.id);
    setIsDeleting(true);
    setDeleteError(null);

    try {
      const result = await fileApi.deleteFile(Number(selectedInvoiceToDelete.id));

      if (result.success) {
        console.log('🗑️ InvoicesLanding - Delete successful, refreshing data');
        // Refresh both active and deleted invoices from server
        await Promise.all([
          fetchInvoices(),
          fetchDeletedInvoices()
        ]);
        // Close modal
        setShowDeleteModal(false);
        setSelectedInvoiceToDelete(null);
        setDeleteError(null);
        setSuccessMessage('Invoice moved to recycle bin successfully');
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        console.error('Failed to delete invoice:', result.error);
        setDeleteError(result.error || 'Failed to delete invoice. Please try again.');
      }
    } catch (error: any) {
      console.error('Failed to delete invoice:', error);
      setDeleteError(error.message || 'Failed to delete invoice. Please try again.');
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRestoreInvoice = (invoice: Invoice) => {
    console.log('🔄 InvoicesLanding - Requesting to restore invoice:', invoice.id);
    setSelectedInvoiceToRestore(invoice);
    setShowRestoreModal(true);
    setRestoreError(null);
  };

  const confirmRestoreInvoice = async () => {
    if (!selectedInvoiceToRestore) return;

    console.log('🔄 InvoicesLanding - Confirming restore for invoice:', selectedInvoiceToRestore.id);
    setIsRestoring(true);
    setRestoreError(null);

    try {
      const result = await fileApi.restoreFile(Number(selectedInvoiceToRestore.id));
      
      if (result.success) {
        console.log('🔄 InvoicesLanding - Restore successful, refreshing data');
        // Refresh both active and deleted invoices from server
        await Promise.all([
          fetchInvoices(),
          fetchDeletedInvoices()
        ]);
        // Close modal
        setShowRestoreModal(false);
        setSelectedInvoiceToRestore(null);
        setRestoreError(null);
        setSuccessMessage('Invoice restored successfully');
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        console.error('Failed to restore invoice:', result.error);
        setRestoreError(result.error || 'Failed to restore invoice. Please try again.');
      }
    } catch (error: any) {
      console.error('Failed to restore invoice:', error);
      setRestoreError(error.message || 'Failed to restore invoice. Please try again.');
    } finally {
      setIsRestoring(false);
    }
  };

  const handleUploadClick = () => {
    router.push('/upload');
  };

  const handleExportClick = () => {
    router.push('/export');
  };

  const handleDownloadClick = async(invoice: Invoice) => {
    try {
      // Use API endpoint for download (works with both blob storage and local files)
      const apiUrl = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/v1/invoices/${invoice.tracking_id}/download`;
      
      console.log('📥 Downloading from API:', apiUrl);
      
      // Construct proper filename from invoice data
      const format = (invoice.target_file_format || 'unknown').toUpperCase();
      const invoiceId = invoice.customerId || invoice.tracking_id.split('-')[0] || 'invoice';
      
      let fileExtension: string;
      switch (format) {
        case 'X12':
          fileExtension = 'x12';
          break;
        case 'EDIFACT':
          fileExtension = 'edi';
          break;
        case 'XML':
        case 'XML_EMBED_PDF':
        case 'XML_EMBED_X12':
        case 'XML_EMBED_EDIFACT':
          fileExtension = 'xml';
          break;
        default:
          fileExtension = 'txt';
      }
      
      const filename = `${invoiceId}_${format}.${fileExtension}`;
      console.log('📁 Downloading as:', filename);
      
      // Fetch from API (backend handles file serving for both local and blob storage)
      const response = await fetch(apiUrl, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      });
      
      if (!response.ok) {
        throw new Error(`Download failed: ${response.statusText}`);
      }
      
      // Download the file (iOS/mobile-friendly approach)
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      
      // Check if iOS/mobile
      const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent);
      const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
      
      if (isIOS || isMobile) {
        // For iOS/mobile: Open in new tab
        window.open(url, '_blank');
        setTimeout(() => window.URL.revokeObjectURL(url), 100);
      } else {
        // For desktop: Traditional download
        const a = document.createElement("a");
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
          document.body.removeChild(a);
          window.URL.revokeObjectURL(url);
        }, 100);
      }
      
      console.log(`✅ Downloaded: ${filename} (${blob.size} bytes)`);
    } catch (error) {
      console.error('❌ Download failed:', error);
      alert('Failed to download file. Please try again.');
    }
  };

  const handlePermanentDeleteClick = (invoice: Invoice) => {
    // TODO: Implement permanent deletion functionality
    console.log('🗑️ Permanently deleting invoice:', invoice.id);
    // This would permanently remove the invoice from the database
    // For now, just show a confirmation or implement actual permanent deletion
  };

  // Pagination
  const totalPages = Math.ceil(filteredInvoices.length / itemsPerPage);
  const startIndex = (currentPage - 1) * itemsPerPage;
  const endIndex = startIndex + itemsPerPage;
  const paginatedInvoices = filteredInvoices.slice(startIndex, endIndex);
  console.log(paginatedInvoices, "these are paginat")

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

  const getStatusIcon = (status?: string) => {
    switch (status?.toLowerCase()) {
      case 'successful':
      case 'completed':
        return <CheckCircle className="h-4 w-4" />;
      case 'processing':
        return <Clock className="h-4 w-4" />;
      case 'failed':
      case 'error':
        return <XCircle className="h-4 w-4" />;
      default:
        return <FileText className="h-4 w-4" />;
    }
  };

  const getSourceBadge = (requestType?: 'web' | 'api') => {
    const source = requestType || 'web';
    
    if (source === 'api') {
      return (
        <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-purple-100 text-purple-800 border border-purple-200">
          <Cloud className="h-3 w-3 mr-1" />
          From SAP
        </span>
      );
    }
    
    return (
      <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium bg-green-100 text-green-800 border border-green-200">
        <MousePointer className="h-3 w-3 mr-1" />
        Manual
      </span>
    );
  };

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-center">
          <h3 className="text-lg font-medium text-gray-900 mb-2">Authentication Required</h3>
          <p className="text-gray-500">Please log in to view your invoices.</p>
        </div>
      </div>
    );
  }

  // Show loading screen during initial load or when explicitly loading
  if (loading || (isAuthenticated && !initialLoadComplete)) {
    return (
      <div className="space-y-4 sm:space-y-6 animate-pulse">
        {/* Header Skeleton */}
        <div className="flex justify-between items-center">
          <div className="h-8 bg-gray-200 rounded w-48"></div>
          <div className="h-10 bg-gray-200 rounded w-32"></div>
        </div>

        {/* Filter Tabs Skeleton */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="h-4 bg-gray-200 rounded w-32 mb-3"></div>
          <div className="flex gap-2">
            <div className="h-10 bg-gray-200 rounded w-24"></div>
            <div className="h-10 bg-gray-200 rounded w-24"></div>
            <div className="h-10 bg-gray-200 rounded w-24"></div>
          </div>
        </div>

        {/* Stat Cards Skeleton */}
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 sm:gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="bg-white rounded-lg shadow p-4">
              <div className="flex items-start space-x-3">
                <div className="h-8 w-8 bg-gray-200 rounded-full"></div>
                <div className="flex-1">
                  <div className="h-6 bg-gray-200 rounded w-12 mb-2"></div>
                  <div className="h-4 bg-gray-200 rounded w-16"></div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Search Bar Skeleton */}
        <div className="bg-white rounded-lg shadow p-4">
          <div className="h-10 bg-gray-200 rounded w-full"></div>
        </div>

        {/* Table Skeleton */}
        <div className="bg-white rounded-lg shadow overflow-hidden">
          {/* Table Header */}
          <div className="border-b border-gray-200 bg-gray-50 p-4">
            <div className="grid grid-cols-5 gap-4">
              {[...Array(5)].map((_, i) => (
                <div key={i} className="h-4 bg-gray-200 rounded"></div>
              ))}
            </div>
          </div>
          
          {/* Table Rows */}
          {[...Array(8)].map((_, i) => (
            <div key={i} className="border-b border-gray-200 p-4">
              <div className="grid grid-cols-5 gap-4">
                {[...Array(5)].map((_, j) => (
                  <div key={j} className="h-4 bg-gray-100 rounded"></div>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Loading Text with Icon */}
        <div className="fixed bottom-8 right-8 bg-white rounded-full shadow-lg px-6 py-3 flex items-center space-x-3">
          <div className="relative">
            <div className="h-5 w-5 border-4 border-blue-200 border-t-blue-600 rounded-full animate-spin"></div>
          </div>
          <span className="text-sm font-medium text-gray-700">Loading invoices...</span>
        </div>
      </div>
    );
  }

  // Reusable StatCard component
  const StatCard = ({ 
    icon: Icon, 
    iconColor, 
    count, 
    label, 
    onClick 
  }: { 
    icon: any; 
    iconColor: string; 
    count: number; 
    label: string; 
    onClick: () => void;
  }) => (
    <div
      className="bg-white rounded-lg shadow p-3 sm:p-4 cursor-pointer hover:shadow-md transition-shadow"
      onClick={onClick}
    >
      <div className="flex flex-col sm:flex-row items-center sm:items-start space-y-2 sm:space-y-0">
        <Icon className={`h-6 w-6 sm:h-8 sm:w-8 ${iconColor} flex-shrink-0`} />
        <div className="sm:ml-3 text-center sm:text-left">
          <div className="text-base sm:text-lg font-semibold text-gray-900">{count}</div>
          <div className="text-xs sm:text-sm text-gray-500 whitespace-nowrap">{label}</div>
        </div>
      </div>
    </div>
  );

  return (
    <div className="space-y-4 sm:space-y-6">

      {/* Source Filter Tabs */}
      {!showRecycleBin && (
        <div className="bg-white rounded-lg shadow p-3 sm:p-4">
          <div className="flex items-center space-x-2 mb-3">
            <Filter className="h-4 w-4 text-gray-600" />
            <span className="text-sm font-medium text-gray-700">Filter by Source:</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => {
                setSourceFilter('all');
                setCurrentPage(1);
              }}
              className={cn(
                "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors",
                sourceFilter === 'all'
                  ? "bg-blue-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              <FileText className="h-4 w-4" />
              <span>All Invoices</span>
              <span className={cn(
                "ml-1 px-2 py-0.5 rounded-full text-xs font-semibold",
                sourceFilter === 'all' ? "bg-blue-500 text-white" : "bg-gray-200 text-gray-700"
              )}>
                {totalInvoicesCount}
              </span>
            </button>
            <button
              onClick={() => {
                setSourceFilter('api');
                setCurrentPage(1);
              }}
              className={cn(
                "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors",
                sourceFilter === 'api'
                  ? "bg-purple-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              <Cloud className="h-4 w-4" />
              <span>From SAP</span>
              <span className={cn(
                "ml-1 px-2 py-0.5 rounded-full text-xs font-semibold",
                sourceFilter === 'api' ? "bg-purple-500 text-white" : "bg-gray-200 text-gray-700"
              )}>
                {sapInvoicesCount}
              </span>
            </button>
            <button
              onClick={() => {
                setSourceFilter('web');
                setCurrentPage(1);
              }}
              className={cn(
                "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors",
                sourceFilter === 'web'
                  ? "bg-green-600 text-white"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              <MousePointer className="h-4 w-4" />
              <span>Manual Upload</span>
              <span className={cn(
                "ml-1 px-2 py-0.5 rounded-full text-xs font-semibold",
                sourceFilter === 'web' ? "bg-green-500 text-white" : "bg-gray-200 text-gray-700"
              )}>
                {manualInvoicesCount}
              </span>
            </button>
          </div>
        </div>
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {!showRecycleBin ? (
          <>
            <StatCard
              icon={FileText}
              iconColor="text-blue-500"
              count={sourceFilter === 'api' ? sapInvoicesCount : sourceFilter === 'web' ? manualInvoicesCount : totalInvoicesCount}
              label={sourceFilter === 'api' ? 'From SAP' : sourceFilter === 'web' ? 'Manual Upload' : 'Total Invoices'}
              onClick={() => {
                console.log('📊 Total invoices card clicked');
                setSearchTerm('');
              }}
            />
            <StatCard
              icon={CheckCircle}
              iconColor="text-green-500"
              count={sourceFilter === 'api' ? sapSuccessCount : sourceFilter === 'web' ? manualSuccessCount : completedCount}
              label="Successful"
              onClick={() => {
                console.log('📊 Successful invoices card clicked');
                setSearchTerm('successful completed');
              }}
            />
            <StatCard
              icon={XCircle}
              iconColor="text-red-500"
              count={sourceFilter === 'api' ? sapFailedCount : sourceFilter === 'web' ? manualFailedCount : failedCount}
              label="Failed"
              onClick={() => {
                console.log('📊 Failed invoices card clicked');
                setSearchTerm('failed error');
              }}
            />
            <StatCard
              icon={Trash}
              iconColor="text-gray-500"
              count={deletedCount}
              label="Deleted"
              onClick={() => {
                console.log('📊 Deleted invoices card clicked - showing recycle bin');
                setShowRecycleBin(true);
                setSearchTerm('');
                // Fetch deleted invoices only when user opens recycle bin
                if (deletedInvoices.length === 0) {
                  fetchDeletedInvoices();
                }
              }}
            />
          </>
        ) : (
          <>
            <StatCard
              icon={FileText}
              iconColor="text-blue-500"
              count={deletedCount}
              label="Deleted Invoices"
              onClick={() => {
                console.log('📊 Deleted Invoices card clicked');
                setSearchTerm('');
              }}
            />
            <StatCard
              icon={RotateCcw}
              iconColor="text-blue-500"
              count={deletedCount}
              label="Can Restore"
              onClick={() => {
                console.log('📊 Can Restore card clicked');
                setSearchTerm('');
              }}
            />
            <StatCard
              icon={Trash2}
              iconColor="text-red-500"
              count={deletedCount}
              label="Can Delete Permanently"
              onClick={() => {
                console.log('📊 Can Delete Permanently card clicked');
                setSearchTerm('');
              }}
            />
            <StatCard
              icon={FileText}
              iconColor="text-gray-500"
              count={activeInvoices.length}
              label="Active Invoices"
              onClick={() => {
                console.log('📊 Active Invoices card clicked - going back to main view');
                setShowRecycleBin(false);
                setSearchTerm('');
              }}
            />
          </>
        )}
      </div>

      {/* Search and Actions */}
      <div className="bg-white rounded-lg shadow p-3 sm:p-4">
        <div className="flex flex-col space-y-3 sm:space-y-0 sm:flex-row sm:items-center sm:justify-between">
          <div className="relative flex-1 sm:max-w-md">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search invoices..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
            />
          </div>
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <button
              onClick={handleUploadClick}
              className="flex items-center space-x-2 px-3 sm:px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors cursor-pointer text-sm flex-1 sm:flex-initial justify-center"
            >
              <Upload className="h-4 w-4" />
              <span>Upload</span>
            </button>
            <button
              onClick={handleExportClick}
              className="flex items-center space-x-2 px-3 sm:px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors cursor-pointer text-sm flex-1 sm:flex-initial justify-center"
            >
              <Download className="h-4 w-4" />
              <span>Export</span>
            </button>
            <button
              onClick={() => {
                setShowRecycleBin(!showRecycleBin);
                if (!showRecycleBin) {
                  // Reset source filter when entering recycle bin
                  setSourceFilter('all');
                }
              }}
              className={cn(
                "flex items-center space-x-2 px-3 sm:px-4 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer w-full sm:w-auto justify-center",
                showRecycleBin
                  ? "bg-red-100 text-red-700 hover:bg-red-200"
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              <Trash className="h-4 w-4" />
              <span className="whitespace-nowrap">{showRecycleBin ? 'Hide Recycle' : 'Recycle Bin'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Invoices Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {paginatedInvoices.length === 0 ? (
          <div className="text-center py-12 px-4">
            <FileText className="mx-auto h-10 w-10 sm:h-12 sm:w-12 text-gray-400 mb-4" />
            <h3 className="text-base sm:text-lg font-medium text-gray-900 mb-2">
              {showRecycleBin ? 'No deleted invoices found' : 'No invoices found'}
            </h3>
            <p className="text-sm sm:text-base text-gray-500">
              {searchTerm
                ? 'Try adjusting your search criteria'
                : showRecycleBin
                  ? 'No invoices have been deleted yet'
                  : 'Upload your first invoice to get started'
              }
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full divide-y divide-gray-200 min-w-[640px]">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Invoice ID</th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Source</th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Format</th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider whitespace-nowrap">
                    {showRecycleBin ? 'Deleted' : 'Uploaded'}
                  </th>
                  <th className="px-3 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {paginatedInvoices.map((invoice, index) => (
                  <tr key={invoice.id || `invoice-${index}`} className="hover:bg-gray-50">
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap text-xs sm:text-sm text-gray-500">
                      {invoice.customerId || invoice.invoice_id || 'N/A'}
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap text-xs sm:text-sm text-gray-500">
                      {invoice.customerName || 'N/A'}
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap">
                      <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium", getStatusColor(invoice.status))}>
                        {getStatusIcon(invoice.status)}
                        <span className="ml-1">{invoice.status || 'Unknown'}</span>
                      </span>
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap">
                      {getSourceBadge(invoice.request_type)}
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap text-xs sm:text-sm text-gray-500">
                      {(invoice.target_file_format || invoice.formate || 'XML').toUpperCase()}
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap text-xs sm:text-sm text-gray-500">
                      {showRecycleBin
                        ? (invoice.deleted_at ? new Date(invoice.deleted_at).toLocaleString() : 'N/A')
                        : (invoice.uploaded_at ? new Date(invoice.uploaded_at).toLocaleString() : 'N/A')
                      }
                    </td>
                    <td className="px-3 sm:px-6 py-3 sm:py-4 whitespace-nowrap text-xs sm:text-sm text-gray-500">
                      <div className="flex items-center space-x-2">
                        {showRecycleBin ? (
                          <>
                            <button
                              onClick={() => handleRestoreInvoice(invoice)}
                              className="p-1 text-gray-400 hover:text-green-600 transition-colors cursor-pointer"
                              title="Restore Document"
                            >
                              <RotateCcw className="h-4 w-4" />
                            </button>
                            <button
                              onClick={() => handlePermanentDeleteClick(invoice)}
                              className="p-1 text-gray-400 hover:text-red-600 transition-colors cursor-pointer"
                              title="Permanently Delete"
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              onClick={() => {
                                const status = invoice.status?.toLowerCase();
                                if (status === 'failed' || status === 'error') {
                                  router.push(`/failed-invoice/${invoice.id}?ai=true`);
                                } else if (status === 'successful' || status === 'completed') {
                                  router.push(`/invoice/${invoice.id}`);
                                }
                              }}
                              className="p-1 text-gray-400 hover:text-blue-600 transition-colors cursor-pointer"
                              title="View Details"
                            >
                              <Eye className="h-4 w-4" />
                            </button>
                            {(invoice.status === 'successful' || invoice.status === 'completed') && (
                              <button
                                onClick={() => handleDownloadClick(invoice)}
                                className="p-1 text-gray-400 hover:text-green-600 transition-colors cursor-pointer"
                                title="Download"
                              >
                                <Download className="h-4 w-4" />
                              </button>
                            )}
                            {(invoice.status === 'failed' || invoice.status === 'error') && (
                              <button
                                onClick={() => router.push(`/failed-invoice/${invoice.id}?ai=true`)}
                                className="p-1 text-gray-400 hover:text-purple-600 transition-colors cursor-pointer"
                                title="Get AI Help"
                              >
                                <MessageCircle className="h-4 w-4" />
                              </button>
                            )}
                            <button
                              onClick={() => {
                                console.log('🗑️ Delete button clicked for invoice:', invoice.id, invoice.filename);
                                handleDeleteInvoice(invoice);
                              }}
                              className="p-1 text-gray-400 hover:text-red-600 transition-colors cursor-pointer"
                              title="Delete Invoice"
                              disabled={isDeleting}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>

            {/* Pagination */}
            <Pagination
              currentPage={currentPage}
              totalPages={totalPages}
              onPageChange={setCurrentPage}
              itemsPerPage={itemsPerPage}
              totalItems={filteredInvoices.length}
            />
          </>
        )}
      </div>

      {/* Delete Confirmation Modal */}
      <DeleteConfirmationModal
        invoice={selectedInvoiceToDelete}
        isOpen={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          setSelectedInvoiceToDelete(null);
          setDeleteError(null);
        }}
        onConfirm={confirmDeleteInvoice}
        isDeleting={isDeleting}
      />

      {/* Restore Confirmation Modal */}
      <RestoreConfirmationModal
        invoice={selectedInvoiceToRestore}
        isOpen={showRestoreModal}
        onClose={() => {
          setShowRestoreModal(false);
          setSelectedInvoiceToRestore(null);
          setRestoreError(null);
        }}
        onConfirm={confirmRestoreInvoice}
        isRestoring={isRestoring}
      />

      {/* Error Messages */}
      {deleteError && (
        <div className="fixed bottom-4 right-4 bg-red-50 border border-red-200 rounded-lg p-4 shadow-lg z-50 max-w-md">
          <div className="flex items-start space-x-3">
            <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-medium text-red-800">Delete Failed</h4>
              <p className="text-sm text-red-700 mt-1">{deleteError}</p>
            </div>
            <button
              onClick={() => setDeleteError(null)}
              className="text-red-400 hover:text-red-600"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {restoreError && (
        <div className="fixed bottom-4 right-4 bg-red-50 border border-red-200 rounded-lg p-4 shadow-lg z-50 max-w-md">
          <div className="flex items-start space-x-3">
            <XCircle className="h-5 w-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-medium text-red-800">Restore Failed</h4>
              <p className="text-sm text-red-700 mt-1">{restoreError}</p>
            </div>
            <button
              onClick={() => setRestoreError(null)}
              className="text-red-400 hover:text-red-600"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {/* Success Message */}
      {successMessage && (
        <div className="fixed bottom-4 right-4 bg-green-50 border border-green-200 rounded-lg p-4 shadow-lg z-50 max-w-md">
          <div className="flex items-start space-x-3">
            <CheckCircle className="h-5 w-5 text-green-600 flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <h4 className="text-sm font-medium text-green-800">Success</h4>
              <p className="text-sm text-green-700 mt-1">{successMessage}</p>
            </div>
            <button
              onClick={() => setSuccessMessage(null)}
              className="text-green-400 hover:text-green-600"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
