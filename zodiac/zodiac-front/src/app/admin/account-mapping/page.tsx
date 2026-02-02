'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import { satSupplierMappingApi } from '@/lib/api';
import {
  Upload,
  Trash2,
  RefreshCw,
  FileText,
  CheckCircle,
  XCircle,
  Download
} from 'lucide-react';

interface SupplierAccountMapping {
  id: number;
  supplier_rfc: string;
  sap_gl_account: string;
  account_description: string | null;
  is_active: boolean;
  is_default: boolean;
  // New GL account fields
  company_code: string | null;
  fiscal_year: number | null;
  currency: string;
  opening_balance: number;
  credit_amount: number;
  debit_amount: number;
  closing_balance: number;
  created_at: string;
  updated_at: string;
}

interface MappingStats {
  total_mappings: number;
  active_mappings: number;
  inactive_mappings: number;
}

export default function AccountMappingPage() {
  const { user } = useAuth();
  const [mappings, setMappings] = useState<SupplierAccountMapping[]>([]);
  const [stats, setStats] = useState<MappingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (user) {
      fetchMappings();
      fetchStats();
    }
  }, [user]);

  const fetchMappings = async () => {
    try {
      setLoading(true);
      const response = await satSupplierMappingApi.list(false, 0, 100);
      setMappings(response.mappings || []);
    } catch (err: any) {
      console.error('Error fetching mappings:', err);
      setError(err.message || 'Failed to fetch mappings');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const response = await satSupplierMappingApi.getStats();
      setStats(response);
    } catch (err: any) {
      console.error('Error fetching stats:', err);
    }
  };

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    try {
      setUploading(true);
      setError(null);
      setSuccess(null);

      const response = await satSupplierMappingApi.uploadExcel(file);
      
      setSuccess(response.message || 'Excel file uploaded successfully!');
      await fetchMappings();
      await fetchStats();
      
      // Clear file input
      event.target.value = '';
    } catch (err: any) {
      console.error('Error uploading file:', err);
      setError(err.message || 'Failed to upload Excel file');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (mappingId: number) => {
    if (!confirm('Are you sure you want to delete this mapping?')) return;

    try {
      await satSupplierMappingApi.delete(mappingId);
      setSuccess('Mapping deleted successfully');
      await fetchMappings();
      await fetchStats();
    } catch (err: any) {
      console.error('Error deleting mapping:', err);
      setError(err.message || 'Failed to delete mapping');
    }
  };

  if (!user) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <LoadingSpinner />
      </div>
    );
  }

  return (
    <MainLayout
      topSection={
        <div className="px-4 sm:px-6 lg:px-8">
          <h1 className="text-2xl sm:text-3xl font-bold text-gray-900 mb-2">
            Supplier Account Mapping
          </h1>
          <p className="text-sm sm:text-base text-gray-600">
            Map supplier RFCs to SAP G/L accounts for automated posting
          </p>
        </div>
      }
    >
      <div className="space-y-6">
          {/* Stats Cards */}
          {stats && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="bg-white rounded-lg shadow p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">Total Mappings</p>
                    <p className="text-2xl font-bold text-gray-900 mt-1">
                      {stats.total_mappings}
                    </p>
                  </div>
                  <FileText className="w-12 h-12 text-blue-600" />
                </div>
              </div>

              <div className="bg-white rounded-lg shadow p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">Active Mappings</p>
                    <p className="text-2xl font-bold text-green-600 mt-1">
                      {stats.active_mappings}
                    </p>
                  </div>
                  <CheckCircle className="w-12 h-12 text-green-600" />
                </div>
              </div>

              <div className="bg-white rounded-lg shadow p-6">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-sm text-gray-600">Inactive Mappings</p>
                    <p className="text-2xl font-bold text-gray-600 mt-1">
                      {stats.inactive_mappings}
                    </p>
                  </div>
                  <XCircle className="w-12 h-12 text-gray-400" />
                </div>
              </div>
            </div>
          )}

          {/* Upload Section */}
          <div className="bg-white rounded-lg shadow p-6">
            <h2 className="text-xl font-semibold text-gray-900 mb-4">
              Upload Excel Mapping
            </h2>
            
            <div className="mb-4 p-4 bg-blue-50 rounded-lg">
              <p className="text-sm text-gray-700 mb-2 font-medium">
                File format (Excel or CSV - required: RFC, CTA; optional: other fields):
              </p>
              <p className="text-xs text-gray-600 mb-2">
                💡 <strong>Tip</strong>: CSV works everywhere! To convert Excel to CSV: File → Save As → CSV (UTF-8)
              </p>
              <div className="overflow-x-auto">
                <div className="grid grid-cols-11 gap-2 text-xs font-mono bg-white p-2 rounded min-w-max">
                  <div className="font-bold">RFC</div>
                  <div className="font-bold">COMPANY_CO</div>
                  <div className="font-bold">GL_ACC</div>
                  <div className="font-bold">CTAS</div>
                  <div className="font-bold">FISC_YR</div>
                  <div className="font-bold">CURR</div>
                  <div className="font-bold">OPEN_BAL</div>
                  <div className="font-bold">CRED</div>
                  <div className="font-bold">DEBE</div>
                  <div className="font-bold">CLOS_BAL</div>
                  <div className="font-bold">IS_ACTIVE</div>
                  <div>ABC123456789</div>
                  <div>MX01</div>
                  <div>40000001</div>
                  <div>Proveedores</div>
                  <div>2026</div>
                  <div>MXN</div>
                  <div>0.00</div>
                  <div>0.00</div>
                  <div>0.00</div>
                  <div>0.00</div>
                  <div>Yes</div>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-4">
              <label className="flex-1">
                <input
                  type="file"
                  accept=".xlsx,.xls,.csv"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  className="hidden"
                />
                <div className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 cursor-pointer transition-colors flex items-center justify-center gap-2">
                  {uploading ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      Uploading...
                    </>
                  ) : (
                    <>
                      <Upload className="w-4 h-4" />
                      Upload File (Excel/CSV)
                    </>
                  )}
                </div>
              </label>

              <button
                onClick={fetchMappings}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
            </div>

            {/* Messages */}
            {error && (
              <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
                <p className="text-red-800 text-sm">{error}</p>
              </div>
            )}

            {success && (
              <div className="mt-4 p-4 bg-green-50 border border-green-200 rounded-lg">
                <p className="text-green-800 text-sm">{success}</p>
              </div>
            )}
          </div>

          {/* Mappings Table */}
          <div className="bg-white rounded-lg shadow">
            <div className="p-6 border-b border-gray-200">
              <h2 className="text-xl font-semibold text-gray-900">
                Current Mappings ({mappings.length})
              </h2>
            </div>

            {loading ? (
              <div className="p-12 text-center">
                <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
                <p className="text-gray-600">Loading mappings...</p>
              </div>
            ) : mappings.length === 0 ? (
              <div className="p-12 text-center">
                <FileText className="w-16 h-16 text-gray-300 mx-auto mb-4" />
                <h3 className="text-lg font-medium text-gray-900 mb-2">
                  No Mappings
                </h3>
                <p className="text-gray-600">
                  Upload an Excel file to create supplier account mappings
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-gray-50 border-b border-gray-200">
                    <tr>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Supplier RFC
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Company Code
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        SAP G/L Account
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Description
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Fiscal Year
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Currency
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Balances
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Status
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="bg-white divide-y divide-gray-200">
                    {mappings.map((mapping) => (
                      <tr key={mapping.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4">
                          <div className="text-sm font-medium text-gray-900">
                            {mapping.supplier_rfc}
                          </div>
                          {mapping.is_default && (
                            <span className="text-xs text-orange-600 font-medium">
                              (Default)
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {mapping.company_code || '-'}
                        </td>
                        <td className="px-6 py-4">
                          <span className="px-2 py-1 bg-purple-100 text-purple-800 rounded text-sm font-medium">
                            {mapping.sap_gl_account}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {mapping.account_description || '-'}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {mapping.fiscal_year || '-'}
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {mapping.currency || 'MXN'}
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-xs text-gray-600 space-y-1">
                            <div>Open: {mapping.opening_balance?.toFixed(2) || '0.00'}</div>
                            <div>Cred: {mapping.credit_amount?.toFixed(2) || '0.00'}</div>
                            <div>Debe: {mapping.debit_amount?.toFixed(2) || '0.00'}</div>
                            <div>Close: {mapping.closing_balance?.toFixed(2) || '0.00'}</div>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          {mapping.is_active ? (
                            <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-xs font-medium">
                              Active
                            </span>
                          ) : (
                            <span className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">
                              Inactive
                            </span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          {!mapping.is_default && (
                            <button
                              onClick={() => handleDelete(mapping.id)}
                              className="text-red-600 hover:text-red-900 transition-colors"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
    </MainLayout>
  );
}

