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
  Eye,
  XCircle,
  AlertTriangle
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

interface MergeRequirements {
  can_merge: boolean;
  has_all_files: boolean;
  missing_types: string[];
  document_types_present: string[];
  document_count: number;
  mapping_exists: boolean;
  mapping_data: {
    company_code: string;
    sap_gl_account: string;
    fiscal_year: number;
    currency: string;
    account_description: string;
  } | null;
}

interface DocumentGroup {
  supplier_rfc: string;
  supplier_name: string;
  fiscal_year: number;
  fiscal_period: number;
  documents: SATDocument[];
  total_amount: number;
  currency: string;
  // New fields for validation
  document_types_present: string[];
  has_invoice: boolean;
  has_payment: boolean;
  has_credit_note: boolean;
  requirements?: MergeRequirements;
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

// File Status Card Component
const FileStatusCard = ({ 
  type, 
  present, 
  document, 
  formatCurrency 
}: { 
  type: string; 
  present: boolean; 
  document?: SATDocument;
  formatCurrency: (amount: string, currency?: string) => string;
}) => {
  const colors = {
    INVOICE: { bg: 'bg-green-50', border: 'border-green-200', text: 'text-green-700', icon: 'text-green-600' },
    PAYMENT: { bg: 'bg-blue-50', border: 'border-blue-200', text: 'text-blue-700', icon: 'text-blue-600' },
    CREDIT_NOTE: { bg: 'bg-orange-50', border: 'border-orange-200', text: 'text-orange-700', icon: 'text-orange-600' }
  };
  
  const color = colors[type as keyof typeof colors] || { bg: 'bg-gray-50', border: 'border-gray-200', text: 'text-gray-700', icon: 'text-gray-600' };
  
  const displayName = type === 'CREDIT_NOTE' ? 'Credit Note' : type.charAt(0) + type.slice(1).toLowerCase();
  
  return (
    <div className={cn(
      "p-3 sm:p-4 rounded-lg border-2 transition-all",
      present ? `${color.bg} ${color.border}` : "bg-gray-50 border-gray-300 opacity-60"
    )}>
      <div className="flex items-center justify-between mb-2">
        <span className={cn("font-semibold text-xs sm:text-sm", present ? color.text : "text-gray-500")}>
          {displayName}
        </span>
        {present ? (
          <CheckCircle className={cn("w-4 h-4 sm:w-5 sm:h-5", color.icon)} />
        ) : (
          <XCircle className="w-4 h-4 sm:w-5 sm:h-5 text-gray-400" />
        )}
      </div>
      {present && document && (
        <div className="text-xs text-gray-600 space-y-1">
          <div className="truncate">Folio: {document.folio || 'N/A'}</div>
          <div className="font-medium">{formatCurrency(document.total, document.currency || document.moneda)}</div>
        </div>
      )}
      {!present && (
        <div className="text-xs text-gray-500 italic">Not uploaded</div>
      )}
    </div>
  );
};

export default function SATSimpleMergeTab() {
  const router = useRouter();
  const { user } = useAuth();
  const [allDocuments, setAllDocuments] = useState<SATDocument[]>([]);
  const [documentGroups, setDocumentGroups] = useState<DocumentGroup[]>([]);
  const [mergedDocuments, setMergedDocuments] = useState<SimpleMergedDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMerged, setLoadingMerged] = useState(false);
  const [loadingRequirements, setLoadingRequirements] = useState(false);
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
      const groups = await groupDocumentsBySupplierAndPeriod(filteredDocs);
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

  const groupDocumentsBySupplierAndPeriod = async (docs: SATDocument[]): Promise<DocumentGroup[]> => {
    const groupMap = new Map<string, DocumentGroup>();

    docs.forEach((doc) => {
      if (!doc.fecha) return;
      
      const docDate = new Date(doc.fecha);
      const year = docDate.getFullYear();
      const period = docDate.getMonth() + 1;
      
      const groupKey = `${doc.supplier_rfc}_${year}_${period}`;
      
      if (!groupMap.has(groupKey)) {
        const docTypes: string[] = [];
        groupMap.set(groupKey, {
          supplier_rfc: doc.supplier_rfc,
          supplier_name: doc.supplier_name || doc.supplier_rfc,
          fiscal_year: year,
          fiscal_period: period,
          documents: [],
          total_amount: 0,
          currency: doc.currency || doc.moneda || 'MXN',
          document_types_present: docTypes,
          has_invoice: false,
          has_payment: false,
          has_credit_note: false,
        });
      }
      
      const group = groupMap.get(groupKey)!;
      group.documents.push(doc);
      group.total_amount += parseFloat(doc.total || '0');
      
      // Track document types
      if (!group.document_types_present.includes(doc.doc_type)) {
        group.document_types_present.push(doc.doc_type);
      }
      
      if (doc.doc_type === 'INVOICE') group.has_invoice = true;
      if (doc.doc_type === 'PAYMENT') group.has_payment = true;
      if (doc.doc_type === 'CREDIT_NOTE') group.has_credit_note = true;
    });

    const groups = Array.from(groupMap.values()).sort((a, b) => {
      const nameCompare = a.supplier_name.localeCompare(b.supplier_name);
      if (nameCompare !== 0) return nameCompare;
      if (a.fiscal_year !== b.fiscal_year) return b.fiscal_year - a.fiscal_year;
      return b.fiscal_period - a.fiscal_period;
    });

    // Fetch requirements for each group
    setLoadingRequirements(true);
    for (const group of groups) {
      try {
        const requirements = await satSimpleMergeApi.checkMergeRequirements(
          group.supplier_rfc,
          group.fiscal_year,
          group.fiscal_period
        );
        group.requirements = requirements;
      } catch (error) {
        console.error(`Failed to fetch requirements for ${group.supplier_rfc}:`, error);
        // Set default requirements if API fails
        group.requirements = {
          can_merge: false,
          has_all_files: false,
          missing_types: ['INVOICE', 'PAYMENT', 'CREDIT_NOTE'],
          document_types_present: group.document_types_present,
          document_count: group.documents.length,
          mapping_exists: false,
          mapping_data: null
        };
      }
    }
    setLoadingRequirements(false);

    return groups;
  };

  const handleMerge = async (group: DocumentGroup) => {
    if (!group.requirements?.can_merge) {
      let message = 'Cannot merge:\n';
      if (group.requirements?.missing_types && group.requirements.missing_types.length > 0) {
        message += `- Missing files: ${group.requirements.missing_types.join(', ')}\n`;
      }
      if (!group.requirements?.mapping_exists) {
        message += `- Missing mapping data for RFC ${group.supplier_rfc}\n`;
      }
      alert(message);
      return;
    }

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

  const formatCurrency = (amount: number | string, currency: string = 'MXN') => {
    const numAmount = typeof amount === 'string' ? parseFloat(amount) : amount;
    return new Intl.NumberFormat('es-MX', {
      style: 'currency',
      currency: currency || 'MXN'
    }).format(numAmount);
  };

  const getMonthName = (month: number) => {
    return new Date(2000, month - 1, 1).toLocaleString('default', { month: 'long' });
  };

  const getDocByType = (group: DocumentGroup, type: string): SATDocument | undefined => {
    return group.documents.find(doc => doc.doc_type === type);
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
      <div className="bg-white rounded-lg shadow p-4 sm:p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex-1">
            <h2 className="text-lg sm:text-xl font-semibold text-gray-900 mb-2">Simple XML Merge</h2>
            <p className="text-sm sm:text-base text-gray-600">
              Merge CFDI documents by supplier and fiscal period. All 3 document types (Invoice, Payment, Credit Note) are required.
            </p>
          </div>
          <button
            onClick={fetchData}
            className="p-2 rounded-full text-gray-400 hover:text-gray-500 hover:bg-gray-100 transition-colors flex-shrink-0"
            title="Refresh documents"
          >
            <RefreshCw className="h-5 w-5" />
          </button>
        </div>

        {/* Filters */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
          <h3 className="text-base sm:text-lg font-semibold text-gray-900">Available Documents to Merge</h3>
          {loadingRequirements && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
              <div className="flex items-center gap-2">
                <RefreshCw className="w-4 h-4 animate-spin text-blue-600" />
                <span className="text-sm text-blue-800">Checking merge requirements...</span>
              </div>
            </div>
          )}
          
          {documentGroups.map((group) => {
            const groupKey = `${group.supplier_rfc}_${group.fiscal_year}_${group.fiscal_period}`;
            const isMerging = mergingGroup === groupKey;
            const alreadyMerged = isGroupAlreadyMerged(group);
            const canMerge = group.requirements?.can_merge && !alreadyMerged;

            return (
              <div key={groupKey} className="bg-white rounded-lg shadow-lg p-4 sm:p-6">
                {/* RFC Header */}
                <div className="flex flex-col sm:flex-row items-start justify-between mb-4 pb-4 border-b border-gray-200 gap-3">
                  <div className="flex-1 min-w-0 w-full sm:w-auto">
                    <div className="flex items-center gap-2 sm:gap-3 mb-2 flex-wrap">
                      <Building2 className="w-5 h-5 text-blue-600 flex-shrink-0" />
                      <h3 className="text-base sm:text-lg font-semibold text-gray-900 truncate">
                        {group.supplier_name}
                      </h3>
                      {alreadyMerged && (
                        <span className="px-2 py-1 bg-green-100 text-green-800 text-xs font-medium rounded-full whitespace-nowrap">
                          Already Merged
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap items-center gap-2 sm:gap-4 text-xs sm:text-sm text-gray-600">
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
                  <div className="text-left sm:text-right w-full sm:w-auto">
                    <div className="text-xs sm:text-sm text-gray-600 mb-1">Total Amount</div>
                    <div className="text-lg sm:text-xl font-bold text-gray-900">
                      {formatCurrency(group.total_amount, group.currency)}
                    </div>
                  </div>
                </div>

                {/* File Status Indicators - Responsive Grid */}
                <div className="mb-4">
                  <h4 className="text-xs sm:text-sm font-medium text-gray-700 mb-3">
                    Required Files Status
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <FileStatusCard 
                      type="INVOICE" 
                      present={group.has_invoice}
                      document={getDocByType(group, 'INVOICE')}
                      formatCurrency={formatCurrency}
                    />
                    <FileStatusCard 
                      type="PAYMENT" 
                      present={group.has_payment}
                      document={getDocByType(group, 'PAYMENT')}
                      formatCurrency={formatCurrency}
                    />
                    <FileStatusCard 
                      type="CREDIT_NOTE" 
                      present={group.has_credit_note}
                      document={getDocByType(group, 'CREDIT_NOTE')}
                      formatCurrency={formatCurrency}
                    />
                  </div>
                </div>

                {/* Mapping Status */}
                {group.requirements && (
                  <div className="mb-4 p-3 rounded-lg border">
                    {group.requirements.mapping_exists ? (
                      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-2 text-green-700">
                        <div className="flex items-center gap-2">
                          <CheckCircle className="w-5 h-5 flex-shrink-0" />
                          <span className="text-sm font-medium">Mapping Data Available</span>
                        </div>
                        <span className="text-xs sm:text-sm sm:ml-auto bg-green-100 px-2 py-1 rounded">
                          GL: {group.requirements.mapping_data?.sap_gl_account}
                        </span>
                      </div>
                    ) : (
                      <div className="flex items-start gap-2 text-red-700">
                        <XCircle className="w-5 h-5 flex-shrink-0 mt-0.5" />
                        <div>
                          <span className="text-sm font-medium block">Mapping Data Missing - Required</span>
                          <span className="text-xs">Please add mapping data for this RFC in the supplier mapping table</span>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Missing Requirements Warning */}
                {!group.requirements?.can_merge && !alreadyMerged && group.requirements && (
                  <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg">
                    <div className="flex items-start gap-2">
                      <XCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
                      <div className="flex-1">
                        <p className="text-sm font-medium text-red-800">Cannot Merge - Requirements Not Met</p>
                        {group.requirements.missing_types.length > 0 && (
                          <p className="text-xs text-red-700 mt-1">
                            Missing Files: {group.requirements.missing_types.map(type => 
                              type === 'CREDIT_NOTE' ? 'Credit Note' : type.charAt(0) + type.slice(1).toLowerCase()
                            ).join(', ')}
                          </p>
                        )}
                        {!group.requirements.mapping_exists && (
                          <p className="text-xs text-red-700 mt-1">
                            Missing Mapping Data: No supplier mapping found for RFC {group.supplier_rfc}
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Merge Button */}
                <div className="flex justify-end">
                  <button
                    onClick={() => handleMerge(group)}
                    disabled={!canMerge || isMerging}
                    className={cn(
                      "w-full sm:w-auto inline-flex items-center justify-center px-4 sm:px-6 py-2 sm:py-3 border border-transparent text-sm sm:text-base font-medium rounded-md shadow-sm text-white transition-all",
                      canMerge && !isMerging
                        ? "bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-700 hover:to-purple-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
                        : "bg-gray-400 cursor-not-allowed",
                      isMerging && "opacity-50"
                    )}
                  >
                    {isMerging ? (
                      <>
                        <RefreshCw className="animate-spin -ml-1 mr-2 sm:mr-3 h-4 w-4 sm:h-5 sm:w-5" />
                        Merging...
                      </>
                    ) : alreadyMerged ? (
                      <>
                        <CheckCircle className="-ml-1 mr-2 sm:mr-3 h-4 w-4 sm:h-5 sm:w-5" />
                        Merged
                      </>
                    ) : canMerge ? (
                      <>
                        <Merge className="-ml-1 mr-2 sm:mr-3 h-4 w-4 sm:h-5 sm:w-5" />
                        <span className="hidden sm:inline">Merge & Save</span>
                        <span className="sm:hidden">Merge</span>
                      </>
                    ) : (
                      <>
                        <XCircle className="-ml-1 mr-2 h-4 w-4 sm:h-5 sm:w-5" />
                        Cannot Merge
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
          <div className="p-4 sm:p-6 border-b border-gray-200">
            <h2 className="text-lg sm:text-xl font-semibold text-gray-900">
              Saved Merged Documents ({mergedDocuments.length})
            </h2>
            <p className="text-xs sm:text-sm text-gray-600 mt-1">
              View details or download merged XML files
            </p>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Vendor
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden sm:table-cell">
                    Period
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider hidden md:table-cell">
                    Documents
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Total Amount
                  </th>
                  <th className="px-4 sm:px-6 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="bg-white divide-y divide-gray-200">
                {mergedDocuments.map((doc) => (
                  <tr key={doc.id} className="hover:bg-gray-50">
                    <td className="px-4 sm:px-6 py-4">
                      <div className="flex items-center">
                        <Building2 className="w-4 h-4 text-gray-400 mr-2 flex-shrink-0" />
                        <div className="min-w-0">
                          <div className="text-xs sm:text-sm font-medium text-gray-900 truncate">
                            {doc.vendor_name}
                          </div>
                          <div className="text-xs text-gray-500 font-mono truncate">
                            {doc.vendor_rfc}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap hidden sm:table-cell">
                      <div className="flex items-center text-xs sm:text-sm text-gray-900">
                        <Calendar className="w-4 h-4 text-gray-400 mr-2" />
                        {getMonthName(doc.fiscal_period)} {doc.fiscal_year}
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap hidden md:table-cell">
                      <div className="text-xs sm:text-sm text-gray-900">
                        {doc.document_count} documents
                      </div>
                      <div className="text-xs text-gray-500">
                        {doc.document_types?.join(', ')}
                      </div>
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-xs sm:text-sm text-gray-900 font-medium">
                      {formatCurrency(doc.total_amount, doc.currency)}
                    </td>
                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-right text-xs sm:text-sm font-medium">
                      <button
                        onClick={() => router.push(`/sat-documents/simple-merge/${doc.id}`)}
                        className="text-blue-600 hover:text-blue-900 inline-flex items-center gap-1"
                      >
                        <Eye className="w-4 h-4" />
                        <span className="hidden sm:inline">Details</span>
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
        <div className="bg-white rounded-lg shadow p-8 sm:p-12 text-center">
          <FileText className="w-12 h-12 sm:w-16 sm:h-16 text-gray-300 mx-auto mb-4" />
          <h3 className="text-base sm:text-lg font-medium text-gray-900 mb-2">No Documents Available</h3>
          <p className="text-sm sm:text-base text-gray-600">
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
            <h4 className="text-xs sm:text-sm font-medium text-blue-900 mb-1">About Simple Merge</h4>
            <p className="text-xs sm:text-sm text-blue-800">
              <strong>Requirements for merging:</strong><br/>
              1. All 3 document types (Invoice, Payment, Credit Note) must be uploaded<br/>
              2. Mapping data must exist in supplier mapping table<br/>
              <br/>
              The merged XML contains all CFDI documents grouped by vendor and fiscal period. 
              Mapping data from the supplier account table will be included in the SAP JSON format.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
