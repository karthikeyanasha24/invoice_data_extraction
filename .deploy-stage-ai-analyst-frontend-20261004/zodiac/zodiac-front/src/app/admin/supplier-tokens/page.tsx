'use client';

import { useState, useEffect } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import MainLayout from '@/components/MainLayout';
import LoadingSpinner from '@/components/LoadingSpinner';
import { supplierTokensApi } from '@/lib/api';
import {
  Key,
  Plus,
  Trash2,
  RefreshCw,
  Copy,
  CheckCircle,
  XCircle,
  Clock,
  AlertCircle
} from 'lucide-react';

interface SupplierTokenInfo {
  id: number;
  supplier_rfc: string;
  supplier_name: string | null;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
  created_by: number | null;
  has_ip_whitelist: boolean;
  notes: string | null;
}

interface TokenStats {
  total_tokens: number;
  active_tokens: number;
  expired_tokens: number;
  recently_used: number;
}

export default function SupplierTokensPage() {
  const { user } = useAuth();
  const [tokens, setTokens] = useState<SupplierTokenInfo[]>([]);
  const [stats, setStats] = useState<TokenStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [generatedToken, setGeneratedToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form state
  const [formData, setFormData] = useState({
    supplier_rfc: '',
    supplier_name: '',
    expires_in_days: 365,
    notes: ''
  });

  useEffect(() => {
    if (user) {
      fetchTokens();
      fetchStats();
    }
  }, [user]);

  const fetchTokens = async () => {
    try {
      setLoading(true);
      const data = await supplierTokensApi.list();
      setTokens(data.tokens || []);
    } catch (err: any) {
      console.error('Error fetching tokens:', err);
      setError(err.message || 'Failed to fetch tokens');
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const data = await supplierTokensApi.getStats();
      setStats(data);
    } catch (err: any) {
      console.error('Error fetching stats:', err);
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    
    try {
      const data = await supplierTokensApi.generate(formData);
      setGeneratedToken(data.token);
      setSuccess(`Token generated for ${data.supplier_rfc}!`);
      setShowGenerateModal(false);  // Close the modal
      
      // Reset form
      setFormData({
        supplier_rfc: '',
        supplier_name: '',
        expires_in_days: 365,
        notes: ''
      });
      
      // Refresh list
      await fetchTokens();
      await fetchStats();
    } catch (err: any) {
      console.error('Error generating token:', err);
      setError(err.message || 'Failed to generate token');
    }
  };

  const handleRevoke = async (tokenId: number, rfc: string) => {
    if (!confirm(`Are you sure you want to revoke token for ${rfc}?`)) return;
    
    try {
      await supplierTokensApi.revoke(tokenId);
      setSuccess(`Token revoked for ${rfc}`);
      await fetchTokens();
      await fetchStats();
    } catch (err: any) {
      console.error('Error revoking token:', err);
      setError(err.message || 'Failed to revoke token');
    }
  };

  const handleRefresh = async (tokenId: number, rfc: string) => {
    if (!confirm(`Generate new token for ${rfc}? The old token will be deactivated.`)) return;
    
    try {
      const data = await supplierTokensApi.refresh(tokenId);
      setGeneratedToken(data.token);
      setSuccess(`New token generated for ${rfc}!`);
      
      await fetchTokens();
      await fetchStats();
    } catch (err: any) {
      console.error('Error refreshing token:', err);
      setError(err.message || 'Failed to refresh token');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setSuccess('Token copied to clipboard!');
    setTimeout(() => setSuccess(null), 3000);
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
            Supplier Tokens
          </h1>
          <p className="text-sm sm:text-base text-gray-600">
            Manage API tokens for suppliers to submit CFDI documents
          </p>
        </div>
      }
    >
      <div className="space-y-6">
        {/* Stats Cards */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600">Total Tokens</p>
                  <p className="text-2xl font-bold text-gray-900 mt-1">
                    {stats.total_tokens}
                  </p>
                </div>
                <Key className="w-12 h-12 text-blue-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600">Active</p>
                  <p className="text-2xl font-bold text-green-600 mt-1">
                    {stats.active_tokens}
                  </p>
                </div>
                <CheckCircle className="w-12 h-12 text-green-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600">Expired</p>
                  <p className="text-2xl font-bold text-orange-600 mt-1">
                    {stats.expired_tokens}
                  </p>
                </div>
                <Clock className="w-12 h-12 text-orange-600" />
              </div>
            </div>

            <div className="bg-white rounded-lg shadow p-6">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-600">Recently Used</p>
                  <p className="text-2xl font-bold text-purple-600 mt-1">
                    {stats.recently_used}
                  </p>
                </div>
                <RefreshCw className="w-12 h-12 text-purple-600" />
              </div>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center justify-between">
            <h2 className="text-xl font-semibold text-gray-900">
              Manage Supplier Tokens
            </h2>
            <div className="flex gap-3">
              <button
                onClick={fetchTokens}
                className="px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 transition-colors flex items-center gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                Refresh
              </button>
              <button
                onClick={() => setShowGenerateModal(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
              >
                <Plus className="w-4 h-4" />
                Generate Token
              </button>
            </div>
          </div>
        </div>

        {/* Messages */}
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <p className="text-red-800">{error}</p>
          </div>
        )}

        {success && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4 flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <p className="text-green-800">{success}</p>
          </div>
        )}

        {/* Generated Token Display */}
        {generatedToken && (
          <div className="bg-yellow-50 border-2 border-yellow-400 rounded-lg p-6">
            <div className="flex items-start gap-3 mb-4">
              <AlertCircle className="w-6 h-6 text-yellow-600 flex-shrink-0 mt-0.5" />
              <div className="flex-1">
                <h3 className="text-lg font-bold text-yellow-900 mb-2">
                  Token Generated Successfully!
                </h3>
                <p className="text-yellow-800 text-sm mb-4">
                  This is the ONLY time this token will be displayed. Copy it now and store it securely!
                </p>
                <div className="bg-white border-2 border-yellow-300 rounded p-4">
                  <div className="flex items-center justify-between">
                    <code className="text-sm font-mono text-gray-900 break-all flex-1">
                      {generatedToken}
                    </code>
                    <button
                      onClick={() => copyToClipboard(generatedToken)}
                      className="ml-4 px-3 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors flex items-center gap-2"
                    >
                      <Copy className="w-4 h-4" />
                      Copy
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <button
              onClick={() => setGeneratedToken(null)}
              className="px-4 py-2 bg-yellow-600 text-white rounded hover:bg-yellow-700 transition-colors"
            >
              I've copied the token
            </button>
          </div>
        )}

        {/* Tokens Table */}
        <div className="bg-white rounded-lg shadow">
          <div className="p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">
              Supplier Tokens ({tokens.length})
            </h2>
          </div>

          {loading ? (
            <div className="p-12 text-center">
              <RefreshCw className="w-8 h-8 animate-spin text-blue-600 mx-auto mb-4" />
              <p className="text-gray-600">Loading tokens...</p>
            </div>
          ) : tokens.length === 0 ? (
            <div className="p-12 text-center">
              <Key className="w-16 h-16 text-gray-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-gray-900 mb-2">
                No Supplier Tokens
              </h3>
              <p className="text-gray-600 mb-4">
                Generate your first supplier token to allow suppliers to submit documents via API
              </p>
              <button
                onClick={() => setShowGenerateModal(true)}
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
              >
                Generate First Token
              </button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Supplier
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Status
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Last Used
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Expires
                    </th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                      Actions
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {tokens.map((token) => (
                    <tr key={token.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4">
                        <div className="text-sm font-medium text-gray-900">
                          {token.supplier_rfc}
                        </div>
                        <div className="text-sm text-gray-500">
                          {token.supplier_name || 'No name'}
                        </div>
                        {token.has_ip_whitelist && (
                          <span className="text-xs text-blue-600">IP Restricted</span>
                        )}
                      </td>
                      <td className="px-6 py-4">
                        {token.is_active ? (
                          <span className="px-2 py-1 bg-green-100 text-green-800 rounded-full text-xs font-medium">
                            Active
                          </span>
                        ) : (
                          <span className="px-2 py-1 bg-gray-100 text-gray-800 rounded-full text-xs font-medium">
                            Revoked
                          </span>
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600">
                        {token.last_used_at
                          ? new Date(token.last_used_at).toLocaleString()
                          : 'Never'}
                      </td>
                      <td className="px-6 py-4 text-sm text-gray-600">
                        {token.expires_at
                          ? new Date(token.expires_at).toLocaleDateString()
                          : 'No expiration'}
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleRefresh(token.id, token.supplier_rfc)}
                            className="p-1 text-blue-600 hover:text-blue-900 transition-colors"
                            title="Refresh Token"
                          >
                            <RefreshCw className="w-4 h-4" />
                          </button>
                          {token.is_active && (
                            <button
                              onClick={() => handleRevoke(token.id, token.supplier_rfc)}
                              className="p-1 text-red-600 hover:text-red-900 transition-colors"
                              title="Revoke Token"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Generate Token Modal */}
        {showGenerateModal && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full">
              <div className="p-6 border-b border-gray-200">
                <h3 className="text-xl font-semibold text-gray-900">
                  Generate Supplier Token
                </h3>
              </div>
              <form onSubmit={handleGenerate} className="p-6 space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Supplier RFC *
                  </label>
                  <input
                    type="text"
                    required
                    maxLength={13}
                    value={formData.supplier_rfc}
                    onChange={(e) => setFormData({...formData, supplier_rfc: e.target.value.toUpperCase()})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="ABC123456789"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Supplier Name *
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.supplier_name}
                    onChange={(e) => setFormData({...formData, supplier_name: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Company Name SA DE CV"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Expires In (Days)
                  </label>
                  <input
                    type="number"
                    min={1}
                    max={3650}
                    value={formData.expires_in_days}
                    onChange={(e) => setFormData({...formData, expires_in_days: parseInt(e.target.value)})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                  />
                  <p className="text-xs text-gray-500 mt-1">
                    Default: 365 days (1 year)
                  </p>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Notes (Optional)
                  </label>
                  <textarea
                    rows={3}
                    value={formData.notes}
                    onChange={(e) => setFormData({...formData, notes: e.target.value})}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Internal notes..."
                  />
                </div>
                <div className="flex justify-end gap-3 pt-4">
                  <button
                    type="button"
                    onClick={() => setShowGenerateModal(false)}
                    className="px-4 py-2 text-gray-700 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors flex items-center gap-2"
                  >
                    <Key className="w-4 h-4" />
                    Generate Token
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}
      </div>
    </MainLayout>
  );
}
