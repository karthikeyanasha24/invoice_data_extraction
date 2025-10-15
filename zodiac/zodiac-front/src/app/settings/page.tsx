'use client';

import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { User, Bell, Palette, Database, Download } from 'lucide-react';
import { cn } from '@/lib/utils';
import LoadingSpinner from '@/components/LoadingSpinner';
import MainLayout from '@/components/MainLayout';
import TopSection from '@/components/TopSection';

export default function SettingsPage() {
  const { user } = useAuth();
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<'profile' | 'notifications' | 'appearance' | 'data'>('profile');
  const [showDeleteAccountModal, setShowDeleteAccountModal] = useState(false);
  const [isDeletingAccount, setIsDeletingAccount] = useState(false);

  const tabs = [
    { id: 'profile', label: 'Profile', icon: User },
    { id: 'notifications', label: 'Notifications', icon: Bell },
    { id: 'appearance', label: 'Appearance', icon: Palette },
    { id: 'data', label: 'Data & Privacy', icon: Database }
  ];

  const handleSave = async () => {
    setLoading(true);
    // Simulate API call
    await new Promise(resolve => setTimeout(resolve, 1000));
    setLoading(false);
  };

  const handleDeleteAccountClick = () => {
    setShowDeleteAccountModal(true);
  };

  const confirmDeleteAccount = async () => {
    setIsDeletingAccount(true);
    try {
      // TODO: Implement actual account deletion API call
      console.log('🗑️ Deleting account for user:', user?.email);
      // Simulate API call
      await new Promise(resolve => setTimeout(resolve, 2000));
      // After successful deletion, redirect to sign-in page
      // window.location.href = '/sign-in';
    } catch (error) {
      console.error('Failed to delete account:', error);
    } finally {
      setIsDeletingAccount(false);
      setShowDeleteAccountModal(false);
    }
  };

  return (
    <MainLayout 
      topSection={
        <TopSection
          title="Settings"
          subtitle="Manage your account settings and preferences"
        />
      }
    >
      <div className="px-4 py-8">
        <div className="max-w-7xl mx-auto">

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-8">
          {/* Sidebar */}
          <div className="lg:col-span-1">
            <nav className="space-y-1">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id as any)}
                    className={cn(
                      "w-full flex items-center space-x-3 px-3 py-2 rounded-lg text-left transition-colors",
                      activeTab === tab.id
                        ? "bg-blue-50 text-blue-700 border border-blue-200"
                        : "text-gray-700 hover:bg-gray-50"
                    )}
                  >
                    <Icon className="h-5 w-5" />
                    <span className="font-medium">{tab.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>

          {/* Main Content */}
          <div className="lg:col-span-3">
            <div className="bg-white rounded-lg shadow">
              {/* Profile Tab */}
              {activeTab === 'profile' && (
                <div className="p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-6">Profile Information</h2>
                  <div className="space-y-6">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Username
                        </label>
                        <input
                          type="text"
                          defaultValue={user?.username || ''}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-gray-700 mb-2">
                          Email
                        </label>
                        <input
                          type="email"
                          defaultValue={user?.email || ''}
                          className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Full Name
                      </label>
                      <input
                        type="text"
                        placeholder="Enter your full name"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Bio
                      </label>
                      <textarea
                        rows={3}
                        placeholder="Tell us about yourself"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* Notifications Tab */}
              {activeTab === 'notifications' && (
                <div className="p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-6">Notification Preferences</h2>
                  <div className="space-y-6">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">Email Notifications</h3>
                        <p className="text-sm text-gray-500">Receive notifications via email</p>
                      </div>
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" className="sr-only peer" defaultChecked />
                        <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                      </label>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">Processing Updates</h3>
                        <p className="text-sm text-gray-500">Get notified when invoice processing completes</p>
                      </div>
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" className="sr-only peer" defaultChecked />
                        <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                      </label>
                    </div>
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">Error Alerts</h3>
                        <p className="text-sm text-gray-500">Receive alerts when invoice processing fails</p>
                      </div>
                      <label className="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" className="sr-only peer" defaultChecked />
                        <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                      </label>
                    </div>
                  </div>
                </div>
              )}

              {/* Appearance Tab */}
              {activeTab === 'appearance' && (
                <div className="p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-6">Appearance Settings</h2>
                  <div className="space-y-6">
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-3">
                        Theme
                      </label>
                      <div className="grid grid-cols-3 gap-4">
                        <button className="p-4 border-2 border-blue-500 rounded-lg bg-white">
                          <div className="w-full h-8 bg-gray-100 rounded mb-2"></div>
                          <div className="text-sm font-medium">Light</div>
                        </button>
                        <button className="p-4 border-2 border-gray-300 rounded-lg bg-gray-900">
                          <div className="w-full h-8 bg-gray-700 rounded mb-2"></div>
                          <div className="text-sm font-medium text-white">Dark</div>
                        </button>
                        <button className="p-4 border-2 border-gray-300 rounded-lg bg-white">
                          <div className="w-full h-8 bg-gradient-to-r from-gray-100 to-gray-900 rounded mb-2"></div>
                          <div className="text-sm font-medium">Auto</div>
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-gray-700 mb-2">
                        Language
                      </label>
                      <select className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500">
                        <option>English</option>
                        <option>Spanish</option>
                        <option>French</option>
                        <option>German</option>
                      </select>
                    </div>
                  </div>
                </div>
              )}

              {/* Data & Privacy Tab */}
              {activeTab === 'data' && (
                <div className="p-6">
                  <h2 className="text-lg font-semibold text-gray-900 mb-6">Data & Privacy</h2>
                  <div className="space-y-6">
                    <div className="border rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h3 className="text-sm font-medium text-gray-900">Export Data</h3>
                          <p className="text-sm text-gray-500">Download all your data in JSON format</p>
                        </div>
                        <button className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700">
                          <Download className="h-4 w-4" />
                          <span>Export</span>
                        </button>
                      </div>
                    </div>
                    <div className="border rounded-lg p-4">
                      <div className="flex items-center justify-between">
                        <div>
                          <h3 className="text-sm font-medium text-gray-900">Delete Account</h3>
                          <p className="text-sm text-gray-500">Permanently delete your account and all data</p>
                        </div>
                        <button 
                          onClick={handleDeleteAccountClick}
                          disabled={true}
                          className="flex items-center space-x-2 px-4 py-2 bg-gray-400 text-white rounded-md cursor-not-allowed opacity-50"
                        >
                          <span>Delete</span>
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Save Button - Hidden for Data & Privacy tab */}
              {activeTab !== 'data' && (
                <div className="px-6 py-4 border-t border-gray-200">
                  <div className="flex items-center justify-end space-x-3">
                    <button className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors cursor-pointer">
                      Cancel
                    </button>
                    <button
                      onClick={handleSave}
                      disabled={loading}
                      className="flex items-center space-x-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 transition-colors cursor-pointer"
                    >
                      {loading && <LoadingSpinner size="sm" />}
                      <span>Save Changes</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
        </div>
      </div>

      {/* Delete Account Confirmation Modal */}
      {showDeleteAccountModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
            <div className="flex items-center mb-4">
              <div className="flex-shrink-0">
                <div className="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                  <span className="text-red-600 text-xl">⚠️</span>
                </div>
              </div>
              <div className="ml-3">
                <h3 className="text-lg font-medium text-gray-900">Delete Account</h3>
                <p className="text-sm text-gray-500">This action cannot be undone</p>
              </div>
            </div>
            <div className="mb-6">
              <p className="text-sm text-gray-600">
                Are you sure you want to permanently delete your account? This will remove all your data, invoices, and settings. This action cannot be undone.
              </p>
            </div>
            <div className="flex items-center justify-end space-x-3">
              <button
                onClick={() => setShowDeleteAccountModal(false)}
                disabled={isDeletingAccount}
                className="px-4 py-2 text-gray-700 bg-gray-100 rounded-md hover:bg-gray-200 transition-colors cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={confirmDeleteAccount}
                disabled={isDeletingAccount}
                className="px-4 py-2 bg-red-600 text-white rounded-md hover:bg-red-700 transition-colors cursor-pointer disabled:opacity-50"
              >
                {isDeletingAccount ? 'Deleting...' : 'Delete Account'}
              </button>
            </div>
          </div>
        </div>
      )}
    </MainLayout>
  );
}