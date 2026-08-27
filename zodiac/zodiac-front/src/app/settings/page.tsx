'use client';

import { useState, useEffect } from 'react';
import { User, Key, Shield, Copy, Eye, EyeOff, Plus, Trash2, AlertCircle, CheckCircle, Globe } from 'lucide-react';
import { fileApi } from '@/lib/api';
import { publicApiError } from '@/lib/apiErrors';
import { ApiKeyInfo, ApiKeyResponse } from '@/types';
import { cn } from '@/lib/utils';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';
import { useAuth } from '@/contexts/AuthContext';

export default function SettingsPage() {
  const { user, loading: authLoading } = useAuth();
  const [apiKeyInfo, setApiKeyInfo] = useState<ApiKeyInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showApiKey, setShowApiKey] = useState(false);
  const [generatedApiKey, setGeneratedApiKey] = useState('');
  const [newIpAddress, setNewIpAddress] = useState('');
  const [ipAddresses, setIpAddresses] = useState<string[]>([]);
  const [hasChanges, setHasChanges] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  useEffect(() => {
    if (authLoading || !user) return;
    fetchApiKeyInfo();
  }, [authLoading, user]);

  const fetchApiKeyInfo = async () => {
    try {
      setLoading(true);
      const info = await fileApi.getApiKey();
      setApiKeyInfo(info);
      setIpAddresses(info.allow_list || []);
      setHasChanges(false);
    } catch (error: any) {
      console.error('Failed to fetch API key info:', error);
      setError(publicApiError(error, 'Could not load API key information.'));
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateApiKey = async () => {
    try {
      setActionLoading('generate');
      setError('');
      setSuccess('');
      
      const result = await fileApi.generateApiKey();
      setGeneratedApiKey(result.api_key);
      setShowApiKey(true);
      setSuccess('API key generated successfully!');
      
      await fetchApiKeyInfo();
    } catch (error: any) {
      console.error('Failed to generate API key:', error);
      setError(publicApiError(error, 'Could not generate API key.'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleRegenerateApiKey = async () => {
    if (!confirm('Are you sure you want to regenerate your API key? This will invalidate your current key and you will need to update all applications using it.')) {
      return;
    }

    try {
      setActionLoading('regenerate');
      setError('');
      setSuccess('');
      
      const result = await fileApi.regenerateApiKey();
      setGeneratedApiKey(result.api_key);
      setShowApiKey(true);
      setSuccess('API key regenerated successfully!');
      
      await fetchApiKeyInfo();
    } catch (error: any) {
      console.error('Failed to regenerate API key:', error);
      setError(publicApiError(error, 'Could not regenerate API key.'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleSuspendApiKey = async () => {
    if (!confirm('Are you sure you want to suspend your API key? This will prevent all API access until you reactivate it.')) {
      return;
    }

    try {
      setActionLoading('suspend');
      setError('');
      setSuccess('');
      
      await fileApi.suspendApiKey();
      setSuccess('API key suspended successfully!');
      
      await fetchApiKeyInfo();
    } catch (error: any) {
      console.error('Failed to suspend API key:', error);
      setError(publicApiError(error, 'Could not suspend API key.'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleActivateApiKey = async () => {
    try {
      setActionLoading('activate');
      setError('');
      setSuccess('');
      
      await fileApi.activateApiKey();
      setSuccess('API key activated successfully!');
      
      await fetchApiKeyInfo();
    } catch (error: any) {
      console.error('Failed to activate API key:', error);
      setError(publicApiError(error, 'Could not activate API key.'));
    } finally {
      setActionLoading(null);
    }
  };

  const handleSaveIpAddresses = async () => {
    try {
      setActionLoading('save');
      setError('');
      setSuccess('');
      
      await fileApi.updateApiKeyAllowList(ipAddresses);
      setSuccess('IP allow list updated successfully!');
      setHasChanges(false);
      
      await fetchApiKeyInfo();
    } catch (error: any) {
      console.error('Failed to update IP allow list:', error);
      setError(publicApiError(error, 'Could not update the IP allow list.'));
    } finally {
      setActionLoading(null);
    }
  };

  const addIpAddress = () => {
    if (newIpAddress.trim() && !ipAddresses.includes(newIpAddress.trim())) {
      setIpAddresses([...ipAddresses, newIpAddress.trim()]);
      setNewIpAddress('');
      setHasChanges(true);
    }
  };

  const removeIpAddress = (ip: string) => {
    setIpAddresses(ipAddresses.filter(addr => addr !== ip));
    setHasChanges(true);
  };

  const copyApiKey = () => {
    if (generatedApiKey) {
      navigator.clipboard.writeText(generatedApiKey);
      setSuccess('API key copied to clipboard!');
    }
  };

  const validateIpAddress = (ip: string) => {
    const ipPattern = /^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    return ipPattern.test(ip);
  };

  return (
    <MainLayout 
      topSection={
        <TopSection 
          title="Settings" 
          subtitle="Profile, security, and API access"
        />
      }
    >
      <div className="max-w-7xl mx-auto py-6 sm:px-6 lg:px-8">
        {authLoading && (
          <div className="mb-6 rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-600">
            Loading your account…
          </div>
        )}
        {error && (
          <div className="mb-6 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            <p className="font-medium">Could not load settings</p>
            <p className="mt-1">{error}</p>
            <button
              type="button"
              onClick={() => { setError(''); fetchApiKeyInfo(); }}
              className="mt-3 rounded-md bg-red-700 px-3 py-1.5 text-white hover:bg-red-800"
            >
              Retry
            </button>
          </div>
        )}
        <div className="space-y-6">
          <nav className="flex flex-wrap gap-2" aria-label="Settings sections">
            {[
              { href: '#profile', label: 'Profile' },
              { href: '#security', label: 'Security' },
              { href: '#api-access', label: 'API access' },
              { href: '#account', label: 'Account' },
            ].map((s) => (
              <a
                key={s.href}
                href={s.href}
                className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:border-emerald-400 hover:text-emerald-800"
              >
                {s.label}
              </a>
            ))}
          </nav>
          {/* Profile Settings */}
          <div id="profile" className="bg-white shadow rounded-lg scroll-mt-24">
            <div className="px-4 py-5 sm:p-6">
              <div className="flex items-center">
                <User className="h-6 w-6 text-blue-600 mr-3" />
                <h3 className="text-lg leading-6 font-medium text-gray-900">Profile Information</h3>
              </div>
              <p className="mt-2 text-sm text-gray-600">
                Manage your account profile and personal information.
              </p>
              
              <div className="mt-6">
                <div className="grid grid-cols-1 gap-6 sm:grid-cols-2">
                  <div>
                    <label htmlFor="username" className="block text-sm font-medium text-gray-700">
                      Username
                    </label>
                    <input
                      type="text"
                      name="username"
                      id="username"
                      className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm bg-gray-50"
                      value={user?.username || ''}
                      disabled
                    />
                  </div>
                  
                  <div>
                    <label htmlFor="email" className="block text-sm font-medium text-gray-700">
                      Email Address
                    </label>
                    <input
                      type="email"
                      name="email"
                      id="email"
                      className="mt-1 block w-full border-gray-300 rounded-md shadow-sm focus:ring-blue-500 focus:border-blue-500 sm:text-sm bg-gray-50"
                      value={user?.email || ''}
                      disabled
                    />
                  </div>
                </div>
                
                <div className="mt-6">
                  <p className="text-xs text-slate-500">
                    Username and email are assigned by your administrator. Contact support to change them.
                  </p>
                </div>
              </div>
            </div>
          </div>

          <div id="security" className="bg-white shadow rounded-lg scroll-mt-24">
            <div className="px-4 py-5 sm:p-6">
              <div className="flex items-center">
                <Shield className="h-6 w-6 text-emerald-800 mr-3" />
                <h3 className="text-lg leading-6 font-medium text-gray-900">Security</h3>
              </div>
              <p className="mt-2 text-sm text-gray-600">
                Sessions use a signed JWT. Protected pages and adaptive analytics require a valid token.
              </p>
              <div className="mt-6 bg-slate-50 border border-slate-200 rounded-md p-4">
                <h4 className="text-sm font-medium text-slate-800">Password and account changes</h4>
                <p className="mt-2 text-sm text-slate-600">
                  Password resets and role changes are handled by your administrator. This page does not expose unused notification or processing toggles.
                </p>
              </div>
            </div>
          </div>

          {/* API Key Management */}
          <div id="api-access" className="bg-white shadow rounded-lg scroll-mt-24">
            <div className="px-4 py-5 sm:p-6">
              <div className="flex items-center">
                <Key className="h-6 w-6 text-blue-600 mr-3" />
                <h3 className="text-lg leading-6 font-medium text-gray-900">API Key Management</h3>
              </div>
              <p className="mt-2 text-sm text-gray-600">
                Manage your API key for programmatic access to invoice processing services.
              </p>

              {/* Error/Success Messages */}
              {error && (
                <div className="mt-4 bg-red-50 border border-red-200 rounded-md p-4">
                  <div className="flex">
                    <AlertCircle className="h-5 w-5 text-red-400" />
                    <div className="ml-3">
                      <h3 className="text-sm font-medium text-red-800">Error</h3>
                      <div className="mt-2 text-sm text-red-700">{error}</div>
                    </div>
                  </div>
                </div>
              )}

              {success && (
                <div className="mt-4 bg-green-50 border border-green-200 rounded-md p-4">
                  <div className="flex">
                    <CheckCircle className="h-5 w-5 text-green-400" />
                    <div className="ml-3">
                      <h3 className="text-sm font-medium text-green-800">Success</h3>
                      <div className="mt-2 text-sm text-green-700">{success}</div>
                    </div>
                  </div>
                </div>
              )}

              {loading ? (
                <div className="mt-6 animate-pulse">
                  <div className="h-4 bg-gray-200 rounded w-1/4 mb-4"></div>
                  <div className="space-y-3">
                    <div className="h-4 bg-gray-200 rounded"></div>
                    <div className="h-4 bg-gray-200 rounded w-5/6"></div>
                  </div>
                </div>
              ) : (
                <div className="mt-6">
                  {apiKeyInfo?.has_key ? (
                    <div className="space-y-6">
                      {/* API Key Status */}
                      <div>
                        <h4 className="text-md font-medium text-gray-900 mb-4">Current Status</h4>
                        
                        <div className="space-y-4">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center">
                              <Shield className="h-5 w-5 text-green-500 mr-2" />
                              <span className="text-sm font-medium text-gray-900">API Key Status</span>
                            </div>
                            <span className={cn(
                              "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
                              apiKeyInfo.is_active 
                                ? "bg-green-100 text-green-800" 
                                : "bg-red-100 text-red-800"
                            )}>
                              {apiKeyInfo.is_active ? 'Active' : 'Suspended'}
                            </span>
                          </div>

                          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
                            <div>
                              <span className="font-medium text-gray-700">User Identifier:</span>
                              <p className="text-gray-900 font-mono">{apiKeyInfo.api_user_identifier}</p>
                            </div>
                            <div>
                              <span className="font-medium text-gray-700">Created:</span>
                              <p className="text-gray-900">
                                {apiKeyInfo.created_at ? new Date(apiKeyInfo.created_at).toLocaleString() : 'N/A'}
                              </p>
                            </div>
                            <div>
                              <span className="font-medium text-gray-700">Last Updated:</span>
                              <p className="text-gray-900">
                                {apiKeyInfo.updated_at ? new Date(apiKeyInfo.updated_at).toLocaleString() : 'N/A'}
                              </p>
                            </div>
                            <div>
                              <span className="font-medium text-gray-700">IP Restrictions:</span>
                              <p className="text-gray-900">
                                {apiKeyInfo.allow_list && apiKeyInfo.allow_list.length > 0 
                                  ? `${apiKeyInfo.allow_list.length} IP(s) configured`
                                  : 'No restrictions (all IPs allowed)'
                                }
                              </p>
                            </div>
                          </div>

                          {/* Action Buttons */}
                          <div className="flex flex-wrap gap-2 pt-4 border-t">
                            {apiKeyInfo.is_active ? (
                              <button
                                onClick={handleSuspendApiKey}
                                disabled={actionLoading === 'suspend'}
                                className="inline-flex items-center px-3 py-2 border border-red-300 shadow-sm text-sm leading-4 font-medium rounded-md text-red-700 bg-white hover:bg-red-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-red-500 disabled:opacity-50"
                              >
                                {actionLoading === 'suspend' ? 'Suspending...' : 'Suspend Key'}
                              </button>
                            ) : (
                              <button
                                onClick={handleActivateApiKey}
                                disabled={actionLoading === 'activate'}
                                className="inline-flex items-center px-3 py-2 border border-green-300 shadow-sm text-sm leading-4 font-medium rounded-md text-green-700 bg-white hover:bg-green-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50"
                              >
                                {actionLoading === 'activate' ? 'Activating...' : 'Activate Key'}
                              </button>
                            )}
                            
                            <button
                              onClick={handleRegenerateApiKey}
                              disabled={actionLoading === 'regenerate'}
                              className="inline-flex items-center px-3 py-2 border border-yellow-300 shadow-sm text-sm leading-4 font-medium rounded-md text-yellow-700 bg-white hover:bg-yellow-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-yellow-500 disabled:opacity-50"
                            >
                              {actionLoading === 'regenerate' ? 'Regenerating...' : 'Regenerate Key'}
                            </button>
                          </div>
                        </div>
                      </div>

                      {/* Generated API Key Display */}
                      {generatedApiKey && showApiKey && (
                        <div>
                          <div className="flex items-center justify-between mb-4">
                            <h4 className="text-md font-medium text-gray-900">Your API Key</h4>
                            <div className="flex items-center space-x-2">
                              <button
                                onClick={() => setShowApiKey(!showApiKey)}
                                className="text-gray-400 hover:text-gray-600"
                              >
                                {showApiKey ? <EyeOff className="h-5 w-5" /> : <Eye className="h-5 w-5" />}
                              </button>
                              <button
                                onClick={copyApiKey}
                                className="text-gray-400 hover:text-gray-600"
                              >
                                <Copy className="h-5 w-5" />
                              </button>
                            </div>
                          </div>
                          
                          <div className="bg-gray-50 border border-gray-200 rounded-md p-3">
                            <code className="text-sm font-mono text-gray-900 break-all">
                              {showApiKey ? generatedApiKey : '••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••••'}
                            </code>
                          </div>
                          
                          <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-md">
                            <div className="flex">
                              <AlertCircle className="h-5 w-5 text-yellow-400" />
                              <div className="ml-3">
                                <h3 className="text-sm font-medium text-yellow-800">Important Security Notice</h3>
                                <div className="mt-2 text-sm text-yellow-700">
                                  <ul className="list-disc list-inside space-y-1">
                                    <li>Store this API key securely and never share it publicly</li>
                                    <li>This key will only be shown once - make sure to copy it now</li>
                                    <li>Use HTTPS when making API requests</li>
                                    <li>Consider setting up IP restrictions for additional security</li>
                                  </ul>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* IP Address Management */}
                      <div>
                        <div className="flex items-center mb-4">
                          <Globe className="h-5 w-5 text-blue-600 mr-2" />
                          <h4 className="text-md font-medium text-gray-900">IP Address Restrictions</h4>
                        </div>
                        
                        <p className="text-sm text-gray-600 mb-4">
                          Restrict API access to specific IP addresses. Leave empty to allow access from any IP address.
                        </p>

                        {/* Add IP Address */}
                        <div className="flex gap-2 mb-4">
                          <input
                            type="text"
                            value={newIpAddress}
                            onChange={(e) => setNewIpAddress(e.target.value)}
                            placeholder="Enter IP address (e.g., 192.168.1.1)"
                            className="flex-1 px-3 py-2 border border-gray-300 rounded-md shadow-sm focus:outline-none focus:ring-blue-500 focus:border-blue-500"
                            onKeyPress={(e) => e.key === 'Enter' && addIpAddress()}
                          />
                          <button
                            onClick={addIpAddress}
                            disabled={!newIpAddress.trim() || !validateIpAddress(newIpAddress.trim()) || ipAddresses.includes(newIpAddress.trim())}
                            className="px-3 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
                          >
                            <Plus className="h-4 w-4" />
                          </button>
                        </div>

                        {/* IP Address List */}
                        {ipAddresses.length > 0 && (
                          <div className="space-y-2 mb-4">
                            {ipAddresses.map((ip, index) => (
                              <div key={index} className="flex items-center justify-between bg-gray-50 px-3 py-2 rounded-md">
                                <span className="text-sm font-mono text-gray-900">{ip}</span>
                                <button
                                  onClick={() => removeIpAddress(ip)}
                                  className="text-red-400 hover:text-red-600"
                                >
                                  <Trash2 className="h-4 w-4" />
                                </button>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Save Button */}
                        {hasChanges && (
                          <div className="flex justify-end">
                            <button
                              onClick={handleSaveIpAddresses}
                              disabled={actionLoading === 'save'}
                              className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-green-600 hover:bg-green-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-green-500 disabled:opacity-50"
                            >
                              {actionLoading === 'save' ? 'Saving...' : 'Save Changes'}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="mt-6 text-center py-8">
                      <Key className="mx-auto h-12 w-12 text-gray-400 mb-4" />
                      <h3 className="text-lg font-medium text-gray-900 mb-2">No API Key Generated</h3>
                      <p className="text-sm text-gray-500 mb-4">
                        Generate an API key to start using programmatic access to invoice processing.
                      </p>
                      <button
                        onClick={handleGenerateApiKey}
                        disabled={actionLoading === 'generate'}
                        className="inline-flex items-center px-4 py-2 border border-transparent text-sm font-medium rounded-md shadow-sm text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50"
                      >
                        {actionLoading === 'generate' ? 'Generating...' : 'Generate API Key'}
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          <div id="account" className="bg-white shadow rounded-lg scroll-mt-24">
            <div className="px-4 py-5 sm:p-6">
              <h3 className="text-lg leading-6 font-medium text-gray-900 mb-4">Account</h3>
              
              <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
                <div className="bg-gray-50 overflow-hidden shadow rounded-lg">
                  <div className="p-5">
                    <div className="flex items-center">
                      <div className="flex-shrink-0">
                        <User className="h-6 w-6 text-gray-400" />
                      </div>
                      <div className="ml-5 w-0 flex-1">
                        <dl>
                          <dt className="text-sm font-medium text-gray-500 truncate">Member Since</dt>
                          <dd className="text-lg font-medium text-gray-900">
                            {user?.created_at ? new Date(user.created_at).toLocaleDateString('en-US', { 
                              year: 'numeric', 
                              month: 'long' 
                            }) : 'N/A'}
                          </dd>
                        </dl>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-gray-50 overflow-hidden shadow rounded-lg">
                  <div className="p-5">
                    <div className="flex items-center">
                      <div className="flex-shrink-0">
                        <Key className="h-6 w-6 text-gray-400" />
                      </div>
                      <div className="ml-5 w-0 flex-1">
                        <dl>
                          <dt className="text-sm font-medium text-gray-500 truncate">API Access</dt>
                          <dd className="text-lg font-medium text-gray-900">
                            {apiKeyInfo?.has_key ? 'Enabled' : 'Not Configured'}
                          </dd>
                        </dl>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="bg-gray-50 overflow-hidden shadow rounded-lg">
                  <div className="p-5">
                    <div className="flex items-center">
                      <div className="flex-shrink-0">
                        <Shield className="h-6 w-6 text-gray-400" />
                      </div>
                      <div className="ml-5 w-0 flex-1">
                        <dl>
                          <dt className="text-sm font-medium text-gray-500 truncate">Account Status</dt>
                          <dd className="text-lg font-medium text-gray-900">
                            {user?.is_active ? 'Active' : 'Inactive'}
                          </dd>
                        </dl>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}