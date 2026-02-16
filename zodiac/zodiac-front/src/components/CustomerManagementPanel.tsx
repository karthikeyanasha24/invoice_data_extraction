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
} from 'lucide-react';
import { cn } from '@/lib/utils';

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

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-blue-50 to-indigo-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 bg-gradient-to-br from-blue-500 to-indigo-600 rounded-lg">
              <Building2 className="w-6 h-6 text-white" />
            </div>
            <h1 className="text-4xl font-bold text-gray-900">Customer Management</h1>
          </div>
          <p className="text-gray-600 ml-11">Manage customers, tax settings, and invoice validation rules</p>
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
        <div className="mb-6 flex flex-col sm:flex-row gap-4 justify-between items-start sm:items-center">
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3 top-3 w-5 h-5 text-gray-400" />
            <input
              type="text"
              placeholder="Search customers..."
              value={searchTerm}
              onChange={handleSearch}
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            onClick={openCreateForm}
            className="flex items-center gap-2 bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 text-white px-4 py-2 rounded-lg font-medium transition-all"
          >
            <Plus className="w-5 h-5" />
            Add Customer
          </button>
        </div>

        {/* Customers Table */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader className="w-8 h-8 text-blue-600 animate-spin" />
            </div>
          ) : customers.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-gray-500">No customers found</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead className="bg-gray-50 border-b border-gray-200">
                  <tr>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Customer ID</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Target Format</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tax Value</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Tax %</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Validation Fields</th>
                    <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase">Actions</th>
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
                      <tr key={customer.id} className="hover:bg-gray-50">
                        <td className="px-6 py-4 text-sm font-medium text-gray-900">{customer.customer_id}</td>
                        <td className="px-6 py-4">
                          <span className={cn("px-2 py-1 rounded-full text-xs font-medium", formatInfo.bgColor, formatInfo.color)}>
                            {customer.target_format}
                          </span>
                        </td>
                        <td className="px-6 py-4 text-sm text-gray-700">${customer.tax_value}</td>
                        <td className="px-6 py-4 text-sm text-gray-700">{customer.tax_percentage}%</td>
                        <td className="px-6 py-4 text-sm text-gray-700">
                          {validationCount > 0 ? `${validationCount} field(s)` : 'None'}
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => openEditForm(customer)}
                              className="p-1 text-blue-600 hover:bg-blue-50 rounded"
                              title="Edit"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => {
                                setCustomerToDelete(customer);
                                setShowDeleteConfirm(true);
                              }}
                              className="p-1 text-red-600 hover:bg-red-50 rounded"
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
            <div className="px-6 py-4 bg-gray-50 border-t border-gray-200 flex items-center justify-between">
              <p className="text-sm text-gray-700">
                Showing {currentPage * itemsPerPage + 1} - {Math.min((currentPage + 1) * itemsPerPage, totalCustomers)} of {totalCustomers}
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => setCurrentPage(prev => Math.max(0, prev - 1))}
                  disabled={currentPage === 0}
                  className="px-3 py-1 border border-gray-300 rounded disabled:opacity-50"
                >
                  Previous
                </button>
                <button
                  onClick={() => setCurrentPage(prev => Math.min(totalPages - 1, prev + 1))}
                  disabled={currentPage >= totalPages - 1}
                  className="px-3 py-1 border border-gray-300 rounded disabled:opacity-50"
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
            <div className="bg-white rounded-lg shadow-xl max-w-3xl w-full max-h-[90vh] overflow-y-auto">
              <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4">
                <h2 className="text-2xl font-bold text-gray-900">
                  {editingCustomer ? 'Edit Customer' : 'Create Customer'}
                </h2>
              </div>

              <form onSubmit={handleSubmit} className="p-6 space-y-6">
                {/* Customer ID */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Customer ID <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={formData.customer_id}
                    onChange={(e) => setFormData({ ...formData, customer_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., CUST-001"
                  />
                </div>

                {/* Target Format */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Target Format <span className="text-red-500">*</span>
                  </label>
                  <select
                    required
                    value={formData.target_format}
                    onChange={(e) => setFormData({ ...formData, target_format: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {supportedFormats.map(format => (
                      <option key={format} value={format}>
                        {format} - {FORMAT_INFO[format]?.description || format}
                      </option>
                    ))}
                  </select>
                </div>

                {/* Tax Fields */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      <DollarSign className="w-4 h-4 inline mr-1" />
                      Tax Value <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      required
                      value={formData.tax_value}
                      onChange={(e) => setFormData({ ...formData, tax_value: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g., 208.11"
                    />
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      <Percent className="w-4 h-4 inline mr-1" />
                      Tax Percentage <span className="text-red-500">*</span>
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      required
                      value={formData.tax_percentage}
                      onChange={(e) => setFormData({ ...formData, tax_percentage: e.target.value })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="e.g., 15"
                    />
                  </div>
                </div>

                {/* Validation Fields */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-3">
                    Validation Fields <span className="text-gray-500">(Optional)</span>
                  </label>
                  <p className="text-sm text-gray-600 mb-4">
                    Select invoice fields to validate. Checked fields must match exact values during conversion.
                  </p>

                  <div className="space-y-3 max-h-64 overflow-y-auto border border-gray-200 rounded-lg p-4">
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
                            <label htmlFor={`field-${field.name}`} className="text-sm font-medium text-gray-700">
                              {field.label}
                            </label>
                          </div>

                          {isSelected && (
                            <input
                              type="text"
                              value={validationFields[field.name] || ''}
                              onChange={(e) => updateValidationFieldValue(field.name, e.target.value)}
                              className="ml-6 w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 text-sm"
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
                    className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={submitting}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2"
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
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-6">
              <h3 className="text-lg font-bold text-gray-900 mb-4">Confirm Deletion</h3>
              <p className="text-gray-700 mb-6">
                Are you sure you want to delete customer <strong>{customerToDelete.customer_id}</strong>?
              </p>
              <div className="flex gap-3 justify-end">
                <button
                  onClick={() => {
                    setShowDeleteConfirm(false);
                    setCustomerToDelete(null);
                  }}
                  disabled={submitting}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={submitting}
                  className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 flex items-center gap-2"
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
      </div>
    </div>
  );
}
