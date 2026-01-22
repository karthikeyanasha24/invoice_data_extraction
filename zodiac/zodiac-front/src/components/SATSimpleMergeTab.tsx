'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { satApi, satSimpleMergeApi } from '@/lib/api';
import LoadingSpinner from './LoadingSpinner';
import { 
  FileText, 
  Download, 
  RefreshCw, 
  Merge, 
  Calendar,
  Building2,
  CheckCircle,
  DollarSign,
  Eye
} from 'lucide-react';
import { format } from 'date-fns';
import { cn } from '@/lib/utils';

interface SATDocument {
  id: string;
  cfdi_uuid: string;
  doc_type: string;
  supplier_rfc: string;
  supplier_name: string;
  total: string;
  currency: string;
  moneda: string;
  fecha: string;
  status: string;
  serie?: string;
  folio?: string;
}

interface DocumentGroup {
  supplier_rfc: string;
  supplier_name: string;
  fiscal_year: number;
  fiscal_period: number;
  documents: SATDocument[];
  total_amount: number;
  currency: string;
}

interface SimpleMergedDocument {
  id: string;
  vendor_rfc: string;
  vendor_name: string;
  fiscal_year: number;
  fiscal_period: number;
  document_count: number;
  document_types: string[];
  cfdi_uuids: string[];
  total_amount: number;
  currency: string;
  created_at: string;
}

export default function SATSimpleMergeTab() {
  const router = useRouter();
  const { user } = useAuth();
  const [allDocuments, setAllDocuments] = useState<SATDocument[]>([]);
  const [documentGroups, setDocumentGroups] = useState<DocumentGroup[]>([]);
  const [mergedDocuments, setMergedDocuments] = useState<SimpleMergedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMerged, setLoadingMerged] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mergingGroup, setMergingGroup] = useState<string | null>(null);

  // Filters
  const [yearFilter, setYearFilter] = useState<number>(new Date().getFullYear());
  const [periodFilter, setPeriodFilter] = useState<number>(new Date().getMonth() + 1);

  useEffect(() => {
    if (user) {
      fetchData();
    }
  }, [user, yearFilter, periodFilter]);

  const fetchData = async () => {
    await Promise.all([fetchDocuments(), fetchMergedDocuments()]);
  };

  const fetchDocuments = async () => {
    try {
      setLoading(true);
      setError(null);
      const response = await satApi.list();
      const docs = response.documents || [];
      
      // Filter documents by fiscal year and period
      const filteredDocs = docs.filter((doc: SATDocument) => {
        if (!doc.fecha) return false;
        const docDate = new Date(doc.fecha);
        return docDate.getFullYear() === yearFilter && (docDate.getMonth() + 1) === periodFilter;
      });

      setAllDocuments(filteredDocs);
      
      // Group documents by supplier and period
      const groups = groupDocumentsBySupplierAndPeriod(filteredDocs);
      setDocumentGroups(groups);
    } catch (err: any) {
      console.error('Error fetching documents for simple merge:', err);
      setError(err.message || 'Failed to fetch documents.');
    } finally {
      setLoading(false);
    }
  };

  const fetchMergedDocuments = async () => {
    try {
      setLoadingMerged(true);
      const response = await satSimpleMergeApi.list(yearFilter, periodFilter);
      setMergedDocuments(response.documents || []);
    } catch (err: any) {
      console.error('Error fetching merged documents:', err);
    } finally {
      setLoadingMerged(false);
    }
  };

  const groupDocumentsBySupplierAndPeriod = (docs: SATDocument[]): DocumentGroup[] => {
    const groupMap = new Map<string, DocumentGroup>();

    docs.forEach((doc) => {
      if (!doc.fecha) return;
      
      const docDate = new Date(doc.fecha);
      const year = docDate.getFullYear();
      const period = docDate.getMonth() + 1;
      
      const groupKey = `${doc.supplier_rfc}_${year}_${period}`;
      
      if (!groupMap.has(groupKey)) {
        groupMap.set(groupKey, {
          supplier_rfc: doc.supplier_rfc,
          supplier_name: doc.supplier_name || doc.supplier_rfc,
          fiscal_year: year,
          fiscal_period: period,
          documents: [],
          total_amount: 0,
          currency: doc.currency || doc.moneda || 'MXN',
        });
      }
      
      const group = groupMap.get(groupKey)!;
      group.documents.push(doc);
      group.total_amount += parseFloat(doc.total || '0');
    });

    return Array.from(groupMap.values()).sort((a, b) => {
      // Sort by supplier name, then by year, then by period
      const nameCompare = a.supplier_name.localeCompare(b.supplier_name);
      if (nameCompare !== 0) return nameCompare;
      if (a.fiscal_year !== b.fiscal_year) return b.fiscal_year - a.fiscal_year;
      return b.fiscal_period - a.fiscal_period;
    });
  };

  const handleMerge = async (group: DocumentGroup) => {
    const groupKey = `${group.supplier_rfc}_${group.fiscal_year}_${group.fiscal_period}`;
    
    try {
      setMergingGroup(groupKey);
      setError(null);
      
      await satSimpleMergeApi.merge({
        fiscal_year: group.fiscal_year,
        fiscal_period: group.fiscal_period,
        supplier_rfc: group.supplier_rfc
      });
      
      // Refresh merged documents
      await fetchMergedDocuments();
      
      alert('Documents merged successfully!');
    } catch (err: any) {
      console.error('Error merging documents:', err);
      setError(err.message || 'Failed to merge documents.');
    } finally {
      setMergingGroup(null);
    }
  };

  const formatCurrency = (amount: number, currency: string = 'MXN') => {
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency || 'MXN'
    }).format(amount);
  };

  const getMonthName = (month: number) => {
    return new Date(2000, month - 1, 1).toLocaleString('default', { month: 'long' });
  };

  const getDocTypeColors = (docType: string) => {
    const colors = {
      INVOICE: 'bg-green-50 border-green-200',
      CREDIT_NOTE: 'bg-orange-50 border-orange-200',
      PAYMENT: 'bg-blue-50 border-blue-200',
    };
    return colors[docType as keyof typeof colors] || 'bg-gray-50 border-gray-200';
  };

  const getDocTypeIconColors = (docType: string) => {
    const colors = {
      INVOICE: 'text-green-600',
      CREDIT_NOTE: 'text-orange-600',
      PAYMENT: 'text-blue-600',
    };
    return colors[docType as keyof typeof colors] || 'text-gray-600';
  };

  const isGroupAlreadyMerged = (group: DocumentGroup) => {
    return mergedDocuments.some(
      (merged) =>
        merged.vendor_rfc === group.supplier_rfc &&
        merged.fiscal_year === group.fiscal_year &&
        merged.fiscal_period === group.fiscal_period
    );
  };

  if (loading && loadingMerged) {
    return (
      <div className="flex items-center justify-center py-20">
        <LoadingSpinner size="lg" text="Loading..." />
      </div>
    );
  }

  if (error && documentGroups.length === 0 && mergedDocuments.length === 0) {
    return (
      <div className="text-center py-12 text-red-600">
        <p>{error}</p>
        <button onClick={fetchData} className="mt-4 px-4 py-2 bg-blue-600 text-white rounded-md">
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Info */}
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <h2 className="text-xl font-semibold text-gray-900 mb-2">Simple XML Merge</h2>
            <p className="text-gray-600">
              Merge CFDI documents by supplier and fiscal period into a single XML file. Merged documents are saved and can be downloaded anytime.
            </p>
          </div>
          <button
            onClick={fetchData}
            className="p-2 rounded-full text-gray-400 hover:text-gray-500 hover:bg-gray-100 transition-colors"
            title="Refresh documents"
          >
            <RefreshCw className="h-5 w-5" />
          </button>
        </div>

        {/* Filters */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Fiscal Year
            </label>
            <select
              value={yearFilter}
              onChange={(e) => setYearFilter(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {[2023, 2024, 2025, 2026].map((year) => (
                <option key={year} value={year}>
                  {year}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Fiscal Period (Month)
            </label>
            <select
              value={periodFilter}
              onChange={(e) => setPeriodFilter(parseInt(e.target.value))}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            >
              {Array.from({ length: 12 }, (_, i) => i + 1).map((month) => (
                <option key={month} value={month}>
                  {getMonthName(month)}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-red-800">{error}</p>
        </div>
      )}

      {/* Available Document Groups to Merge */}
      {documentGroups.length > 0 && (
        <div className="space-y-6">
          <h3 className="text-lg font-semibold text-gray-900">Available Documents to Merge</h3>
          {documentGroups.map((group) => {
            const groupKey = `${group.supplier_rfc}_${group.fiscal_year}_${group.fiscal_period}`;
            const isMerging = mergingGroup === groupKey;
            const alreadyMerged = isGroupAlreadyMerged(group);

            return (
              <div key={groupKey} className="bg-white rounded-lg shadow p-6">
                {/* Group Header */}
                <div className="flex items-start justify-between mb-4 pb-4 border-b border-gray-200">
                  <div className="flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <Building2 className="w-5 h-5 text-blue-600" />
                      <h3 className="text-lg font-semibold text-gray-900">
                        {group.supplier_name}
                      </h3>
                      {alreadyMerged && (
                        <span className="px-2 py-1 bg-green-100 text-green-800 text-xs font-medium rounded-full">
                          Already Merged
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-4 text-sm text-gray-600">
                      <span className="flex items-center gap-1">
                        <span className="font-medium">RFC:</span>
                        <span className="font-mono">{group.supplier_rfc}</span>
                      </span>
                      <span className="flex items-center gap-1">
                        <Calendar className="w-4 h-4" />
                        {getMonthName(group.fiscal_period)} {group.fiscal_year}
                      </span>
                      <span className="flex items-center gap-1">
                        <FileText className="w-4 h-4" />
                        {group.documents.length} documents
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm text-gray-600 mb-1">Total Amount</div>
                    <div className="text-xl font-bold text-gray-900">
                      {formatCurrency(group.total_amount, group.currency)}
                    </div>
                  </div>
                </div>

                {/* Individual Document Cards */}
                <div className="mb-4">
                  <h4 className="text-sm font-medium text-gray-700 mb-3">
                    Documents to be merged
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {group.documents.map((doc) => (
                      <div
                        key={doc.id}
                        className={cn(
                          'border-2 rounded-lg p-4',
                          getDocTypeColors(doc.doc_type)
                        )}
                      >
                        <div className="flex items-start justify-between mb-3">
                          <div className="flex items-center gap-2">
                            <FileText className={cn('w-5 h-5', getDocTypeIconColors(doc.doc_type))} />
                            <span className="font-semibold text-gray-900">
                              {doc.doc_type.replace('_', ' ')}
                            </span>
                          </div>
                          <CheckCircle className="w-4 h-4 text-green-600" />
                        </div>
                        
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between">
                            <span className="text-gray-600">Serie-Folio:</span>
                            <span className="font-medium text-gray-900">
                              {doc.serie || 'N/A'}-{doc.folio || 'N/A'}
                            </span>
                          </div>
                          
                          <div className="flex justify-between">
                            <span className="text-gray-600">UUID:</span>
                            <span className="font-mono text-xs text-gray-900">
                              {doc.cfdi_uuid.substring(0, 8)}...
                            </span>
                          </div>
                          
                          <div className="flex justify-between">
                            <span className="text-gray-600">Date:</span>
                            <span className="text-gray-900">
                              {doc.fecha ? format(new Date(doc.fecha), 'MMM dd, yyyy') : 'N/A'}
                            </span>
                          </div>
                          
                          <div className="flex justify-between pt-2 border-t border-gray-300">
                            <span className="text-gray-600 font-medium">Total:</span>
                            <span className="font-bold text-gray-900">
                              {formatCurrency(parseFloat(doc.total), doc.currency || doc.moneda)}
                            </span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Merge Button */}
                <div className="flex justify-end">
                  <button
                    onClick={() => handleMerge(group)}
                    disabled={isMerging || alreadyMerged}
                    className={cn(
                      "inline-flex items-center px-6 py-3 border border-transparent text-base font-medium rounded-md shadow-sm text-white transition-all",
                      alreadyMerged
                        ? "bg-gray-400 cursor-not-allowed"
                        : "bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500",
                      isMerging && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    {isMerging ? (
                      <>
                        <RefreshCw className="animate-spin -ml-1 mr-3 h-5 w-5" />
                        Merging...
                      </>
                    ) : alreadyMerged ? (
                      <>
                        <CheckCircle className="-ml-1 mr-3 h-5 w-5" />
                        Merged
                      </>
                    ) : (
                      <>
                        <Merge className="-ml-1 mr-3 h-5 w-5" />
                        <span className="hidden sm:inline">Merge & Save</span>
                        <span className="sm:hidden">Merge</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Merged Documents List */}
      {mergedDocuments.length > 0 && (
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">
              Saved Merged Documents ({mergedDocuments.length})
            </h2>
            <p className="text-sm text-gray-600 mt-1">
              View details or download merged XML files
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Vendor
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Period
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Documents
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Total Amount
                  </th>
                  <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Created
                  </th>
                  <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {mergedDocuments.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center">
                        <Building2 className="w-4 h-4 text-gray-400 mr-2" />
                        <div>
                          <div className="text-sm font-medium text-gray-900">
                            {doc.vendor_name}
                          </div>
                          <div className="text-sm text-gray-500 font-mono">
                            {doc.vendor_rfc}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="flex items-center text-sm text-gray-900">
                        <Calendar className="w-4 h-4 text-gray-400 mr-2" />
                        {getMonthName(doc.fiscal_period)} {doc.fiscal_year}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap">
                      <div className="text-sm text-gray-900">
                        {doc.document_count} documents
                      </div>
                      <div className="text-xs text-gray-500">
                        {doc.document_types?.join(', ')}
                      </div>
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-900">
                      {formatCurrency(doc.total_amount, doc.currency)}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                      {format(new Date(doc.created_at), 'MMM dd, yyyy HH:mm')}
                    </td>
                    <td className="px-6 py-4 whitespace-nowrap text-right text-sm font-medium">
                      <button
                        onClick={() => router.push(`/sat-documents/simple-merge/${doc.id}`)}
                        className="text-blue-600 hover:text-blue-900 mr-4"
                      >
                        <Eye className="w-5 h-5 inline" />
                        <span className="ml-1 hidden sm:inline">Details</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Empty State */}
      {documentGroups.length === 0 && mergedDocuments.length === 0 && !loading && (
        <div className="bg-white rounded-lg shadow p-12 text-center">
          <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-lg font-medium text-gray-900 mb-2">No Documents Available</h3>
          <p className="text-gray-600">
            No CFDI documents found for {getMonthName(periodFilter)} {yearFilter}.
            Try selecting a different period or upload new documents.
          </p>
        </div>
      )}

      {/* Info Box */}
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
        <div className="flex gap-3">
          <FileText className="w-5 h-5 text-blue-600 flex-shrink-0 mt-0.5" />
          <div>
            <h4 className="text-sm font-medium text-blue-900 mb-1">About Simple Merge</h4>
            <p className="text-sm text-blue-800">
              The merged XML file contains all CFDI documents grouped by vendor and fiscal period under a single root element. 
              Each original document is preserved in its entirety. This is different from the <strong>Canonical Merge</strong> which aggregates financial data for SAP integration.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
