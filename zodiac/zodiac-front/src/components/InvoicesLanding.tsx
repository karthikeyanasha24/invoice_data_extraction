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
  Upload
} from 'lucide-react';
import { cn } from '@/lib/utils';
import Pagination from '@/components/Pagination';
import LoadingSpinner from '@/components/LoadingSpinner';
import DeleteConfirmationModal from '@/components/DeleteConfirmationModal';

export default function InvoicesLanding() {
  const router = useRouter();
  const { user, isAuthenticated, handleAuthError } = useAuth();
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [deletedInvoices, setDeletedInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [itemsPerPage] = useState(10);
  const [showRecycleBin, setShowRecycleBin] = useState(false);
  
  // Delete confirmation modal state
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [selectedInvoiceToDelete, setSelectedInvoiceToDelete] = useState<Invoice | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (isAuthenticated) {
      fetchInvoices();
      fetchDeletedInvoices();
    } else {
      setLoading(false);
    }
  }, [isAuthenticated]);

  const fetchInvoices = async () => {
    try {
      const data = await fileApi.getFiles();
      setInvoices(data);
    } catch (error: any) {
      console.error('Failed to fetch invoices:', error);
      if (error.message?.includes('Session expired') || error.message?.includes('log in again')) {
        handleAuthError();
      }
    } finally {
      setLoading(false);
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

  // Filter and search invoices based on current view
  const filteredInvoices = showRecycleBin 
    ? deletedInvoices.filter(invoice => {
        const matchesSearch = invoice.filename.toLowerCase().includes(searchTerm.toLowerCase()) ||
                             invoice.customerName?.toLowerCase().includes(searchTerm.toLowerCase());
        return matchesSearch;
      })
    : invoices.filter(invoice => {
        const matchesSearch = invoice.filename.toLowerCase().includes(searchTerm.toLowerCase()) ||
                             invoice.customerName?.toLowerCase().includes(searchTerm.toLowerCase());
        return matchesSearch && invoice.status !== 'deleted';
      });

  const handleDeleteInvoice = async (invoice: Invoice) => {
    console.log('🗑️ InvoicesLanding - Requesting to delete invoice:', invoice.id);
    setSelectedInvoiceToDelete(invoice);
    setShowDeleteModal(true);
  };

  const confirmDeleteInvoice = async () => {
    if (!selectedInvoiceToDelete) return;

    console.log('🗑️ InvoicesLanding - Confirming delete for invoice:', selectedInvoiceToDelete.id);
    setIsDeleting(true);

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
      } else {
        console.error('Failed to delete invoice:', result.error);
      }
    } catch (error) {
      console.error('Failed to delete invoice:', error);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleRestoreInvoice = async (invoice: Invoice) => {
    try {
      const result = await fileApi.restoreFile(Number(invoice.id));
      if (result.success) {
        console.log('🔄 Invoice restored successfully, refreshing data');
        // Refresh both active and deleted invoices from server
        await Promise.all([
          fetchInvoices(),
          fetchDeletedInvoices()
        ]);
      } else {
        console.error('Failed to restore invoice:', result.error);
      }
    } catch (error) {
      console.error('Failed to restore invoice:', error);
    }
  };

  const handleUploadClick = () => {
    router.push('/upload');
  };

  const handleExportClick = () => {
    router.push('/export');
  };

  const handleDownloadClick = (invoice: Invoice) => {
    // TODO: Implement actual download functionality
    console.log('📥 Downloading invoice:', invoice.id);
    // For now, just show a message or implement actual download
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

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner size="lg" text="Loading invoices..." />
      </div>
    );
  }

  return (
    <div className="space-y-6">

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div 
          className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
          onClick={() => {
            console.log('📊 Total invoices card clicked');
            setShowRecycleBin(false);
            setSearchTerm('');
          }}
        >
          <div className="flex items-center">
            <FileText className="h-8 w-8 text-blue-500" />
            <div className="ml-3">
              <div className="text-lg font-semibold text-gray-900">{filteredInvoices.length}</div>
              <div className="text-sm text-gray-500">{showRecycleBin ? 'Deleted Invoices' : 'Total Invoices'}</div>
            </div>
          </div>
        </div>
        {!showRecycleBin && (
          <>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Completed invoices card clicked');
                setSearchTerm('successful completed');
              }}
            >
              <div className="flex items-center">
                <CheckCircle className="h-8 w-8 text-green-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">
                    {filteredInvoices.filter(inv => inv.status === 'successful' || inv.status === 'completed').length}
                  </div>
                  <div className="text-sm text-gray-500">Completed</div>
                </div>
              </div>
            </div>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Failed invoices card clicked');
                setSearchTerm('failed error');
              }}
            >
              <div className="flex items-center">
                <XCircle className="h-8 w-8 text-red-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">
                    {filteredInvoices.filter(inv => inv.status === 'failed' || inv.status === 'error').length}
                  </div>
                  <div className="text-sm text-gray-500">Failed</div>
                </div>
              </div>
            </div>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Deleted invoices card clicked - showing recycle bin');
                setShowRecycleBin(true);
                setSearchTerm('');
              }}
            >
              <div className="flex items-center">
                <Trash className="h-8 w-8 text-gray-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">{deletedInvoices.length}</div>
                  <div className="text-sm text-gray-500">Deleted</div>
                </div>
              </div>
            </div>
          </>
        )}
        {showRecycleBin && (
          <>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Can Restore card clicked');
                setSearchTerm('');
              }}
            >
              <div className="flex items-center">
                <RotateCcw className="h-8 w-8 text-blue-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">{filteredInvoices.length}</div>
                  <div className="text-sm text-gray-500">Can Restore</div>
                </div>
              </div>
            </div>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Can Delete Permanently card clicked');
                setSearchTerm('');
              }}
            >
              <div className="flex items-center">
                <Trash2 className="h-8 w-8 text-red-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">{filteredInvoices.length}</div>
                  <div className="text-sm text-gray-500">Can Delete Permanently</div>
                </div>
              </div>
            </div>
            <div 
              className="bg-white rounded-lg shadow p-4 cursor-pointer hover:shadow-md transition-shadow"
              onClick={() => {
                console.log('📊 Active Invoices card clicked - going back to main view');
                setShowRecycleBin(false);
                setSearchTerm('');
              }}
            >
              <div className="flex items-center">
                <FileText className="h-8 w-8 text-gray-500" />
                <div className="ml-3">
                  <div className="text-lg font-semibold text-gray-900">{invoices.filter(inv => inv.status !== 'deleted').length}</div>
                  <div className="text-sm text-gray-500">Active Invoices</div>
                </div>
              </div>
            </div>
          </>
        )}
      </div>

      {/* Search and Actions */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search invoices..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div className="flex items-center space-x-3">
            <button
              onClick={handleUploadClick}
              className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors cursor-pointer"
            >
              <Upload className="h-4 w-4" />
              <span>Upload</span>
            </button>
            <button
              onClick={handleExportClick}
              className="flex items-center space-x-2 px-4 py-2 bg-gray-100 text-gray-700 rounded-md hover:bg-gray-200 transition-colors cursor-pointer"
            >
              <Download className="h-4 w-4" />
              <span>Export</span>
            </button>
            <button
              onClick={() => setShowRecycleBin(!showRecycleBin)}
              className={cn(
                "flex items-center space-x-2 px-4 py-2 rounded-md text-sm font-medium transition-colors cursor-pointer",
                showRecycleBin 
                  ? "bg-red-100 text-red-700 hover:bg-red-200" 
                  : "bg-gray-100 text-gray-700 hover:bg-gray-200"
              )}
            >
              <Trash className="h-4 w-4" />
              <span>{showRecycleBin ? 'Hide Recycle Bin' : 'Show Recycle Bin'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Invoices Table */}
      <div className="bg-white rounded-lg shadow overflow-hidden">
        {paginatedInvoices.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <h3 className="text-lg font-medium text-gray-900 mb-2">
              {showRecycleBin ? 'No deleted invoices found' : 'No invoices found'}
            </h3>
            <p className="text-gray-500">
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
            <table className="w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Customer</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Status</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Format</th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    {showRecycleBin ? 'Deleted' : 'Uploaded'}
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Actions</th>
                </tr>
              </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {paginatedInvoices.map((invoice, index) => (
                    <tr key={invoice.id || `invoice-${index}`} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {invoice.customerName || 'N/A'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={cn("inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium", getStatusColor(invoice.status))}>
                          {getStatusIcon(invoice.status)}
                          <span className="ml-1">{invoice.status || 'Unknown'}</span>
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {invoice.formate || 'N/A'}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {showRecycleBin 
                          ? (invoice.deleted_at ? new Date(invoice.deleted_at).toLocaleDateString() : 'N/A')
                          : (invoice.uploaded_at ? new Date(invoice.uploaded_at).toLocaleDateString() : 'N/A')
                        }
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
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
        isOpen={showDeleteModal}
        onClose={() => {
          setShowDeleteModal(false);
          setSelectedInvoiceToDelete(null);
        }}
        onConfirm={confirmDeleteInvoice}
        isLoading={isDeleting}
        invoiceName={selectedInvoiceToDelete?.filename || 'Unknown'}
      />
    </div>
  );
}
