'use client';

import { useState, useEffect } from 'react';
import { customerApi } from '@/lib/api';
import {
  Plus,
  Trash2,
  Edit2,
  Search,
  Check,
  X,
  Loader,
  AlertCircle,
  CheckCircle,
  Building2,
  DollarSign,
  Percent,
  Key,
  Copy,
  Shield,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import CertificateManagement from './CertificateManagement';

interface Customer {
  id: number;
  customer_id: string;
  target_format: string;
  tax_value: string;
  tax_percentage: string;
  validation_fields?: string;
  created_at: string;
}

// Format information mapping for V2
const FORMAT_INFO: Record<string, {
  name: string;
  description: string;
  color: string;
  bgColor: string;
}> = {
  'X12': {
    name: 'X12',
    description: 'ASC X12 EDI format',
    color: 'text-orange-800',
    bgColor: 'bg-orange-100',
  },
  'EDIFACT': {
    name: 'EDIFACT',
    description: 'UN/EDIFACT format',
    color: 'text-purple-800',
    bgColor: 'bg-purple-100',
  },
  'PDF': {
    name: 'PDF',
    description: 'Portable Document Format',
    color: 'text-red-800',
    bgColor: 'bg-red-100',
  },
  'XML': {
    name: 'XML',
    description: 'XML format (UBL 2.0)',
    color: 'text-blue-800',
    bgColor: 'bg-blue-100',
  },
  'UBL': {
    name: 'UBL',
    description: 'Universal Business Language 2.0',
    color: 'text-green-800',
    bgColor: 'bg-green-100',
  },
  'PIDX': {
    name: 'PIDX',
    description: 'Petroleum Industry Data Exchange',
    color: 'text-yellow-800',
    bgColor: 'bg-yellow-100',
  },
  'CFDI': {
    name: 'CFDI',
    description: 'Mexican CFDI format',
    color: 'text-pink-800',
    bgColor: 'bg-pink-100',
  },
};

// Available invoice fields for validation (excluding tax_percentage)
const AVAILABLE_INVOICE_FIELDS = [
  { name: 'supplier_id', label: 'Supplier ID' },
  { name: 'supplier_name', label: 'Supplier Name' },
  { name: 'supplier_tax_id', label: 'Supplier Tax ID' },
  { name: 'supplier_legal_name', label: 'Supplier Legal Name' },
  { name: 'customer_id', label: 'Customer ID' },
  { name: 'customer_name', label: 'Customer Name' },
  { name: 'customer_tax_id', label: 'Customer Tax ID' },
  { name: 'customer_legal_name', label: 'Customer Legal Name' },
  { name: 'invoice_number', label: 'Invoice Number' },
  { name: 'issue_date', label: 'Issue Date' },
  { name: 'due_date', label: 'Due Date' },
  { name: 'invoice_type_code', label: 'Invoice Type Code' },
  { name: 'currency', label: 'Currency' },
  { name: 'payment_means_code', label: 'Payment Means Code' },
  { name: 'total', label: 'Total Amount' },
  { name: 'tax_amount', label: 'Tax Amount' },
];

export default function CustomerManagementPanel() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [currentPage, setCurrentPage] = useState(0);
  const [totalCustomers, setTotalCustomers] = useState(0);
  const itemsPerPage = 10;

  // Modal states
  const [showForm, setShowForm] = useState(false);
  const [editingCustomer, setEditingCustomer] = useState<Customer | null>(null);
  const [customerToDelete, setCustomerToDelete] = useState<Customer | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Customer token modal state
  const [showTokenModal, setShowTokenModal] = useState(false);
  const [tokenCustomer, setTokenCustomer] = useState<Customer | null>(null);
  const [tokenInfo, setTokenInfo] = useState<{ has_token: boolean; last_used_at?: string; expires_at?: string; is_active?: boolean } | null>(null);
  const [generatedToken, setGeneratedToken] = useState<string | null>(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [tokenError, setTokenError] = useState('');
  const [tokenAction, setTokenAction] = useState<'idle' | 'generate' | 'revoke'>('idle');

  // Certificate modal state
  const [showCertificateModal, setShowCertificateModal] = useState(false);
  const [certificateCustomer, setCertificateCustomer] = useState<Customer | null>(null);

  // Form states
  const [formData, setFormData] = useState({
    customer_id: '',
    target_format: 'XML',
    tax_value: '0',
    tax_percentage: '0',
  });
  
  // Validation fields: {field_name: expected_value}
  const [validationFields, setValidationFields] = useState<Record<string, string>>({});

  const [submitting, setSubmitting] = useState(false);
  const [supportedFormats, setSupportedFormats] = useState<string[]>([
    'X12', 'EDIFACT', 'PDF', 'XML', 'UBL', 'PIDX', 'CFDI'
  ]);

  useEffect(() => {
    fetchCustomers();
    fetchFormats();
  }, [currentPage, searchTerm]);

  const fetchFormats = async () => {
    try {
      const data = await customerApi.getSupportedFormats();
      if (data.supported_formats) {
        setSupportedFormats(data.supported_formats);
      }
    } catch (err) {
      console.error('Failed to fetch formats:', err);
    }
  };

  const fetchCustomers = async () => {
    setLoading(true);
    setError('');
    try {
      const skip = currentPage * itemsPerPage;
      const data = await customerApi.getCustomers(skip, itemsPerPage, searchTerm || undefined);
      setCustomers(data.customers || []);
      setTotalCustomers(data.total || 0);
    } catch (err: any) {
      setError(err.message || 'Failed to load customers');
      setCustomers([]);
    } finally {
      setLoading(false);
    }
  };

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchTerm(e.target.value);
    setCurrentPage(0);
  };

  const openCreateForm = () => {
    setEditingCustomer(null);
    setFormData({
      customer_id: '',
      target_format: 'XML',
      tax_value: '0',
      tax_percentage: '0',
    });
    setValidationFields({});
    setShowForm(true);
    setError('');
  };

  const openEditForm = (customer: Customer) => {
    setEditingCustomer(customer);
    setFormData({
      customer_id: customer.customer_id,
      target_format: customer.target_format,
      tax_value: customer.tax_value || '0',
      tax_percentage: customer.tax_percentage || '0',
    });
    
    // Parse validation fields
    let parsedFields = {};
    if (customer.validation_fields) {
      try {
        parsedFields = JSON.parse(customer.validation_fields);
      } catch {
        parsedFields = {};
      }
    }
    setValidationFields(parsedFields);
    
    setShowForm(true);
    setError('');
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingCustomer(null);
    setFormData({
      customer_id: '',
      target_format: 'XML',
      tax_value: '0',
      tax_percentage: '0',
    });
    setValidationFields({});
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');

    try {
      // Convert validation fields to JSON string
      const validationFieldsJson = Object.keys(validationFields).length > 0
        ? JSON.stringify(validationFields)
        : null;
      
      const customerData = {
        customer_id: formData.customer_id,
        target_format: formData.target_format.toUpperCase(),
        tax_value: parseFloat(formData.tax_value),
        tax_percentage: parseFloat(formData.tax_percentage),
        validation_fields: validationFieldsJson,
      };

      if (editingCustomer) {
        // Update existing customer
        await customerApi.updateCustomer(editingCustomer.customer_id, customerData);
        setSuccess('Customer updated successfully');
      } else {
        // Create new customer
        await customerApi.createCustomer(customerData);
        setSuccess('Customer created successfully');
      }

      closeForm();
      fetchCustomers();

      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to save customer');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async () => {
    if (!customerToDelete) return;

    setSubmitting(true);
    setError('');

    try {
      await customerApi.deleteCustomer(customerToDelete.customer_id);
      setSuccess('Customer deleted successfully');
      setShowDeleteConfirm(false);
      setCustomerToDelete(null);
      fetchCustomers();

      // Clear success message after 3 seconds
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      setError(err.message || 'Failed to delete customer');
    } finally {
      setSubmitting(false);
    }
  };

  const toggleValidationField = (fieldName: string) => {
    setValidationFields(prev => {
      const newFields = { ...prev };
      if (newFields[fieldName] !== undefined) {
        delete newFields[fieldName];
      } else {
        newFields[fieldName] = '';
      }
      return newFields;
    });
  };

  const updateValidationFieldValue = (fieldName: string, value: string) => {
    setValidationFields(prev => ({
      ...prev,
      [fieldName]: value
    }));
  };

  const totalPages = Math.ceil(totalCustomers / itemsPerPage);

  const openTokenModal = async (customer: Customer) => {
    setTokenCustomer(customer);
    setShowTokenModal(true);
    setGeneratedToken(null);
    setTokenError('');
    setTokenAction('idle');
    setTokenLoading(true);
    setTokenInfo(null);
    try {
      const info = await customerApi.getCustomerTokenInfo(customer.customer_id);
      setTokenInfo(info);
    } catch (e: any) {
      setTokenError(e.message || 'Failed to load token info');
      setTokenInfo({ has_token: false });
    } finally {
      setTokenLoading(false);
    }
  };

  const closeTokenModal = () => {
    setShowTokenModal(false);
    setTokenCustomer(null);
    setTokenInfo(null);
    setGeneratedToken(null);
    setTokenError('');
    setTokenAction('idle');
  };

  const handleGenerateToken = async () => {
    if (!tokenCustomer) return;
    setTokenAction('generate');
    setTokenError('');
    setTokenLoading(true);
    try {
      const res = await customerApi.generateCustomerToken(tokenCustomer.customer_id);
      setGeneratedToken(res.token);
      setTokenInfo({ has_token: true, is_active: true, expires_at: res.expires_at ?? undefined });
    } catch (e: any) {
      setTokenError(e.message || 'Failed to generate token');
    } finally {
      setTokenLoading(false);
      setTokenAction('idle');
    }
  };

  const handleRevokeToken = async () => {
    if (!tokenCustomer) return;
    setTokenAction('revoke');
    setTokenError('');
    setTokenLoading(true);
    try {
      await customerApi.revokeCustomerToken(tokenCustomer.customer_id);
      setTokenInfo({ has_token: false });
      setGeneratedToken(null);
      setSuccess('Token revoked.');
      setTimeout(() => setSuccess(''), 3000);
    } catch (e: any) {
      setTokenError(e.message || 'Failed to revoke token');
    } finally {
      setTokenLoading(false);
      setTokenAction('idle');
    }
  };

  const copyTokenToClipboard = () => {
    if (generatedToken) {
      navigator.clipboard.writeText(generatedToken);
      setSuccess('Token copied to clipboard.');
      setTimeout(() => setSuccess(''), 2000);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-blue-600 rounded-lg">
              <Building2 className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-3xl font-bold text-gray-900">Customer Management</h1>
              <p className="text-gray-600 text-sm mt-1">Manage customers, tax settings, and invoice validation rules</p>
            </div>
          </div>
        </div>

        {/* Alert Messages */}
        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-red-900">Error</p>
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          </div>
        )}

        {success && (
          <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3">
            <CheckCircle className="w-5 h-5 text-green-600 flex-shrink-0 mt-0.5" />
            <p className="text-green-700 font-medium">{success}</p>
          </div>
        )}

        {/* Controls */}
        <div className="mb-6 flex flex-col sm:flex-row gap-4 justify-between items-stretch sm:items-center">
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search customers..."
              value={searchTerm}
              onChange={handleSearch}
              className="w-full pl-10 pr-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent bg-white shadow-sm"
            />
          </div>
          <button
            onClick={openCreateForm}
            className="flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg font-medium transition-colors shadow-sm"
          >
            <Plus className="w-5 h-5" />
            <span>Add Customer</span>
          </button>
        </div>

        {/* Customers Table */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="text-center">
                <Loader className="w-8 h-8 text-blue-600 animate-spin mx-auto mb-3" />
                <p className="text-gray-500 text-sm">Loading customers...</p>
              </div>
            </div>
          ) : customers.length === 0 ? (
            <div className="text-center py-16">
              <Building2 className="w-12 h-12 text-gray-400 mx-auto mb-3" />
              <p className="text-gray-600 font-medium">No customers found</p>
              <p className="text-gray-500 text-sm mt-1">Try adjusting your search or add a new customer</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Customer ID</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Target Format</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Tax Value</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Tax %</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Validation Fields</th>
                    <th className="px-6 py-3.5 text-left text-xs font-semibold text-gray-700 uppercase tracking-wider">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {customers.map((customer) => {
                    const formatInfo = FORMAT_INFO[customer.target_format] || FORMAT_INFO['XML'];
                    let validationCount = 0;
                    if (customer.validation_fields) {
                      try {
                        const parsed = JSON.parse(customer.validation_fields);
                        validationCount = Object.keys(parsed).length;
                      } catch {}
                    }

                    return (
                      <tr key={customer.id} className="hover:bg-gray-50 transition-colors border-b border-gray-100 last:border-0">
                        <td className="px-6 py-4 text-sm font-semibold text-gray-900">{customer.customer_id}</td>
                        <td className="px-6 py-4">
                          <span className={cn("px-3 py-1 rounded-full text-xs font-medium", formatInfo.bgColor, formatInfo.color)}>
                            {customer.target_format}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-700 font-medium">${customer.tax_value}</td>
                        <td className="px-6 py-4 text-sm text-gray-700">{customer.tax_percentage}%</td>
                        <td className="px-6 py-4 text-sm text-gray-600">
                          {validationCount > 0 ? (
                            <span className="inline-flex items-center gap-1 px-2 py-1 bg-blue-50 text-blue-700 rounded-md text-xs font-medium">
                              <CheckCircle className="w-3 h-3" />
                              {validationCount} field(s)
                            </span>
                          ) : (
                            <span className="text-gray-400">None</span>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-1.5">
                            <button
                              onClick={() => {
                                setCertificateCustomer(customer);
                                setShowCertificateModal(true);
                              }}
                              className="p-2 text-blue-600 hover:bg-blue-50 rounded-lg transition-colors"
                              title="Manage certificates (mTLS)"
                            >
                              <Shield className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => openTokenModal(customer)}
                              className="p-2 text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                              title="Customer token (for API)"
                            >
                              <Key className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => openEditForm(customer)}
                              className="p-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors"
                              title="Edit"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => {
                                setCustomerToDelete(customer);
                                setShowDeleteConfirm(true);
                              }}
                              className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors"
                              title="Delete"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex flex-col sm:flex-row gap-3 sm:gap-0 items-center justify-between">
              <p className="text-sm text-gray-600">
                Showing <span className="font-semibold text-gray-900">{currentPage * itemsPerPage + 1}</span> - <span className="font-semibold text-gray-900">{Math.min((currentPage + 1) * itemsPerPage, totalCustomers)}</span> of <span className="font-semibold text-gray-900">{totalCustomers}</span> customers
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setCurrentPage(prev => Math.max(0, prev - 1))}
                  disabled={currentPage === 0}
                  className="px-4 py-2 border border-gray-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100 transition-colors font-medium text-sm"
                >
                  Previous
                </button>
                <button
                  onClick={() => setCurrentPage(prev => Math.min(totalPages - 1, prev + 1))}
                  disabled={currentPage >= totalPages - 1}
                  className="px-4 py-2 border border-gray-300 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed hover:bg-gray-100 transition-colors font-medium text-sm"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Create/Edit Form Modal */}
        {showForm && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-2xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 rounded-t-xl">
                <h2 className="text-xl font-bold text-gray-900">
                  {editingCustomer ? 'Edit Customer' : 'Create Customer'}
                </h2>
                <p className="text-sm text-gray-600 mt-1">
                  {editingCustomer ? 'Update customer configuration and validation rules' : 'Add a new customer to the system'}
                </p>
              </div>

              <form onSubmit={handleSubmit} className="p-6 space-y-6">
                {/* Customer ID */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Customer ID <span className="text-red-600">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.customer_id}
                    onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    placeholder="e.g., CUST-001"
                  />
                </div>

                {/* Target Format */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Target Format <span className="text-red-600">*</span>
                  </label>
                  <select
                    required
                    value={formData.target_format}
                    onChange={(e) => setFormData({ ...formData, target_format: e.target.value })}
                    className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                  >
                    {supportedFormats.map(format => (
                      <option key={format} value={format}>
                        {format} - {FORMAT_INFO[format]?.description || format}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Tax Fields */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">
                      <DollarSign className="w-4 h-4 inline mr-1" />
                      Tax Value <span className="text-red-600">*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      required
                      value={formData.tax_value}
                      onChange={(e) => setFormData({ ...formData, tax_value: e.target.value })}
                      className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="e.g., 208.11"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-semibold text-gray-700 mb-2">
                      <Percent className="w-4 h-4 inline mr-1" />
                      Tax Percentage <span className="text-red-600">*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      required
                      value={formData.tax_percentage}
                      onChange={(e) => setFormData({ ...formData, tax_percentage: e.target.value })}
                      className="w-full px-4 py-2.5 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      placeholder="e.g., 15"
                    />
                  </div>
                </div>

                {/* Validation Fields */}
                <div>
                  <label className="block text-sm font-semibold text-gray-700 mb-2">
                    Validation Fields <span className="text-gray-500 font-normal">(Optional)</span>
                  </label>
                  <p className="text-sm text-gray-600 mb-4">
                    Select invoice fields to validate. Checked fields must match exact values during conversion.
                  </p>

                  <div className="space-y-3 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-4 bg-gray-50">
                    {AVAILABLE_INVOICE_FIELDS.map(field => {
                      const isSelected = validationFields[field.name] !== undefined;
                      
                      return (
                        <div key={field.name} className="space-y-2">
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              id={`field-${field.name}`}
                              checked={isSelected}
                              onChange={() => toggleValidationField(field.name)}
                              className="w-4 h-4 text-blue-600 rounded focus:ring-2 focus:ring-blue-500"
                            />
                            <label htmlFor={`field-${field.name}`} className="text-sm font-medium text-gray-700 cursor-pointer">
                              {field.label}
                            </label>
                          </div>

                          {isSelected && (
                            <input
                              type="text"
                              value={validationFields[field.name] || ''}
                              onChange={(e) => updateValidationFieldValue(field.name, e.target.value)}
                              className="ml-6 w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm bg-white"
                              placeholder={`Expected ${field.label.toLowerCase()}`}
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {/* Form Actions */}
                <div className="flex gap-3 justify-end pt-4 border-t border-gray-200">
                  <button
                    type="button"
                    onClick={closeForm}
                    disabled={submitting}
                    className="px-6 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 font-medium transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 font-medium transition-colors"
                  >
                    {submitting ? (
                      <>
                        <Loader className="w-4 h-4 animate-spin" />
                        Saving...
                      </>
                    ) : (
                      <>
                        <Check className="w-4 h-4" />
                        {editingCustomer ? 'Update Customer' : 'Create Customer'}
                      </>
                    )}
                  </button>
                </div>
              </form>
            </div>
          </div>
        )}

        {/* Delete Confirmation Modal */}
        {showDeleteConfirm && customerToDelete && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-2xl max-w-md w-full p-6">
              <div className="mb-4">
                <div className="w-12 h-12 bg-red-100 rounded-full flex items-center justify-center mx-auto mb-4">
                  <AlertCircle className="w-6 h-6 text-red-600" />
                </div>
                <h3 className="text-lg font-bold text-gray-900 text-center mb-2">Confirm Deletion</h3>
                <p className="text-gray-600 text-center">
                  Are you sure you want to delete customer <strong className="text-gray-900">{customerToDelete.customer_id}</strong>? This action cannot be undone.
                </p>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    setCustomerToDelete(null);
                  }}
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50 font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={submitting}
                  className="flex-1 px-4 py-2.5 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center justify-center gap-2 font-medium transition-colors"
                >
                  {submitting ? (
                    <>
                      <Loader className="w-4 h-4 animate-spin" />
                      Deleting...
                    </>
                  ) : (
                    <>
                      <Trash2 className="w-4 h-4" />
                      Delete
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Certificate Management Modal */}
        {showCertificateModal && certificateCustomer && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between rounded-t-xl">
                <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <Shield className="w-5 h-5 text-blue-600" />
                  Certificate Management — {certificateCustomer.customer_id}
                </h3>
                <button
                  onClick={() => {
                    setShowCertificateModal(false);
                    setCertificateCustomer(null);
                  }}
                  className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
              <div className="p-6">
                <CertificateManagement customerId={certificateCustomer.customer_id} />
              </div>
            </div>
          </div>
        )}

        {/* Customer Token Modal */}
        {showTokenModal && tokenCustomer && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50">
            <div className="bg-white rounded-xl shadow-2xl max-w-lg w-full p-6">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-bold text-gray-900 flex items-center gap-2">
                  <Key className="w-5 h-5 text-amber-600" />
                  Customer token — {tokenCustomer.customer_id}
                </h3>
                <button onClick={closeTokenModal} className="p-1.5 text-gray-500 hover:bg-gray-100 rounded-lg transition-colors">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <p className="text-sm text-gray-600 mb-4">
                Use this token for API authentication (X-Customer-Token header). This provides token-based access to the portal APIs.
              </p>
              {tokenError && (
                <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  {tokenError}
                </div>
              )}
              {tokenLoading && !generatedToken ? (
                <div className="flex items-center gap-2 text-gray-600 py-4">
                  <Loader className="w-5 h-5 animate-spin" />
                  Loading...
                </div>
              ) : generatedToken ? (
                <div className="space-y-3">
                  <p className="text-sm font-medium text-amber-800">Store this token securely. It will not be shown again.</p>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      readOnly
                      value={generatedToken}
                      className="flex-1 px-3 py-2 border border-gray-300 rounded-lg bg-gray-50 text-sm font-mono"
                    />
                    <button
                      type="button"
                      onClick={copyTokenToClipboard}
                      className="px-3 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 flex items-center gap-1"
                      title="Copy"
                    >
                      <Copy className="w-4 h-4" />
                    </button>
                  </div>
                  <div className="flex justify-end pt-2">
                    <button onClick={closeTokenModal} className="px-6 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition-colors">
                      Done
                    </button>
                  </div>
                </div>
              ) : (
                <div className="space-y-4">
                  {tokenInfo?.has_token && (
                    <p className="text-sm text-gray-600">
                      A token already exists for this customer. You can regenerate it (old token will stop working) or revoke it.
                    </p>
                  )}
                  <div className="flex gap-2 flex-wrap">
                    <button
                      type="button"
                      onClick={handleGenerateToken}
                      disabled={tokenLoading}
                      className="px-6 py-2.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 disabled:opacity-50 flex items-center gap-2 font-medium transition-colors"
                    >
                      {tokenAction === 'generate' && tokenLoading ? <Loader className="w-4 h-4 animate-spin" /> : <Key className="w-4 h-4" />}
                      {tokenInfo?.has_token ? 'Regenerate token' : 'Generate token'}
                    </button>
                    {tokenInfo?.has_token && (
                      <button
                        type="button"
                        onClick={handleRevokeToken}
                        disabled={tokenLoading}
                        className="px-6 py-2.5 border border-red-300 text-red-700 rounded-lg hover:bg-red-50 disabled:opacity-50 flex items-center gap-2 font-medium transition-colors"
                      >
                        {tokenAction === 'revoke' && tokenLoading ? <Loader className="w-4 h-4 animate-spin" /> : null}
                        Revoke token
                      </button>
                    )}
                    <button onClick={closeTokenModal} className="px-6 py-2.5 border border-gray-300 rounded-lg hover:bg-gray-50 font-medium transition-colors">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
