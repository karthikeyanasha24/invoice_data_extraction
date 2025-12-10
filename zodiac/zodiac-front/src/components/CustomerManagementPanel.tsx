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
  FileText,
  ArrowRight,
} from 'lucide-react';
import { cn } from '@/lib/utils';

interface Customer {
  id: number;
  customer_id: string;
  format: string;
  validation_rules?: string;
  created_at: string;
}

// Format information mapping
const FORMAT_INFO: Record<string, {
  name: string;
  description: string;
  targetFormat: string;
  color: string;
  bgColor: string;
  steps: string[];
}> = {
  'edifact': {
    name: 'EDIFACT',
    description: 'European standard for electronic data interchange',
    targetFormat: 'EDIFACT',
    color: 'text-purple-800',
    bgColor: 'bg-purple-100',
    steps: ['XML Validation', 'XML → EDIFACT Conversion', 'Database Save']
  },
  'x12': {
    name: 'X12',
    description: 'North American EDI standard',
    targetFormat: 'X12',
    color: 'text-orange-800',
    bgColor: 'bg-orange-100',
    steps: ['XML Validation', 'XML → X12 Conversion', 'EDI Format Validation', 'EDINation Validation', 'Database Save']
  },
  'xml': {
    name: 'XML Passthrough',
    description: 'XML file without conversion',
    targetFormat: 'XML',
    color: 'text-blue-800',
    bgColor: 'bg-blue-100',
    steps: ['File Upload', 'Database Save']
  },
  'x12_embed': {
    name: 'X12 Embed',
    description: 'XML with embedded X12 content',
    targetFormat: 'XML + X12',
    color: 'text-indigo-800',
    bgColor: 'bg-indigo-100',
    steps: ['XML Validation', 'XML → X12 Conversion', 'Embed X12 in XML', '3rd Party API', 'Database Save']
  },
  'xmlembed': {
    name: 'XML Embed',
    description: 'XML with embedded EDIFACT/X12 content',
    targetFormat: 'XML + EDIFACT',
    color: 'text-teal-800',
    bgColor: 'bg-teal-100',
    steps: ['XML → EDIFACT Conversion', 'Embed in XML', '3rd Party API', 'Database Save']
  },
};

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
    format: 'edifact',
    validation_rules: '',
  });
  
  // Validation rules UI states
  const [selectedFields, setSelectedFields] = useState<Record<string, {selected: boolean, defaultValue: string, expanded: boolean}>>({});
  const [customField, setCustomField] = useState('');
  const [customFieldLabel, setCustomFieldLabel] = useState('');
  const [customFieldError, setCustomFieldError] = useState('');
  const [availableFields] = useState<Array<{value: string, label: string, category: string}>>([
    // Invoice Header
    { value: '//cbc:ID', label: 'Invoice ID', category: 'Invoice Header' },
    { value: '//cbc:IssueDate', label: 'Issue Date', category: 'Invoice Header' },
    { value: '//cbc:DueDate', label: 'Due Date', category: 'Invoice Header' },
    { value: '//cbc:InvoiceTypeCode', label: 'Invoice Type Code', category: 'Invoice Header' },
    { value: '//cbc:DocumentCurrencyCode', label: 'Currency Code', category: 'Invoice Header' },
    
    // Party Information
    { value: '//cac:AccountingSupplierParty', label: 'Supplier Information', category: 'Party Information' },
    { value: '//cac:AccountingCustomerParty', label: 'Customer Information', category: 'Party Information' },
    { value: '//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID', label: 'Supplier Endpoint ID', category: 'Party Information' },
    { value: '//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID', label: 'Customer Endpoint ID', category: 'Party Information' },
    { value: '//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name', label: 'Supplier Name', category: 'Party Information' },
    { value: '//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name', label: 'Customer Name', category: 'Party Information' },
    
    // Tax Information
    { value: '//cac:TaxTotal/cbc:TaxAmount', label: 'Tax Amount', category: 'Tax Information' },
    { value: '//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount', label: 'Taxable Amount', category: 'Tax Information' },
    { value: '//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID', label: 'Tax Category ID', category: 'Tax Information' },
    { value: '//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent', label: 'Tax Percentage', category: 'Tax Information' },
    
    // Financial Information
    { value: '//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount', label: 'Amount Excluding Tax', category: 'Financial Information' },
    { value: '//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount', label: 'Amount Including Tax', category: 'Financial Information' },
    { value: '//cac:LegalMonetaryTotal/cbc:PayableAmount', label: 'Total Payable Amount', category: 'Financial Information' },
    
    // Line Items
    { value: '//cac:InvoiceLine', label: 'Invoice Line Items', category: 'Line Items' },
    { value: '//cac:InvoiceLine/cbc:ID', label: 'Line Item ID', category: 'Line Items' },
    { value: '//cac:InvoiceLine/cac:Item/cbc:Name', label: 'Item Name', category: 'Line Items' },
    { value: '//cac:InvoiceLine/cbc:InvoicedQuantity', label: 'Item Quantity', category: 'Line Items' },
    { value: '//cac:InvoiceLine/cac:Price/cbc:PriceAmount', label: 'Item Price', category: 'Line Items' },
    
    // PEPPOL Specific
    { value: '//cbc:CustomizationID', label: 'PEPPOL Customization ID', category: 'PEPPOL' },
    { value: '//cbc:ProfileID', label: 'PEPPOL Profile ID', category: 'PEPPOL' },
    { value: '//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID', label: 'Supplier Tax ID', category: 'PEPPOL' },
  ]);

  const [submitting, setSubmitting] = useState(false);
  const [supportedFormats, setSupportedFormats] = useState<string[]>([
    'edifact',
    'x12',
    'x12_embed',
    'xml',
    'xmlembed',
  ]);
  const [showFormatInfo, setShowFormatInfo] = useState(false);
  const [selectedFormatInfo, setSelectedFormatInfo] = useState<string | null>(null);

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

  // Helper: Parse validation rules JSON to selected fields
  const parseValidationRules = (rulesJson: string): Record<string, {selected: boolean, defaultValue: string, expanded: boolean}> => {
    if (!rulesJson) return {};
    try {
      const parsed = JSON.parse(rulesJson);
      const result: Record<string, {selected: boolean, defaultValue: string, expanded: boolean}> = {};
      
      if (Array.isArray(parsed.required_fields)) {
        parsed.required_fields.forEach((field: any) => {
          if (typeof field === 'string') {
            // Old format compatibility
            result[field] = { selected: true, defaultValue: '', expanded: false };
          } else if (field.xpath) {
            // New format with default values
            result[field.xpath] = { 
              selected: true, 
              defaultValue: field.default_value || '', 
              expanded: false 
            };
          }
        });
      }
      
      return result;
    } catch {
      return {};
    }
  };

  // Helper: Convert selected fields to validation rules JSON
  const fieldsToValidationRules = (fields: Record<string, {selected: boolean, defaultValue: string, expanded: boolean}>): string => {
    const selectedEntries = Object.entries(fields).filter(([_, data]) => data.selected);
    if (selectedEntries.length === 0) return '';
    
    const requiredFields = selectedEntries.map(([xpath, data]) => ({
      xpath: xpath,
      default_value: data.defaultValue || null
    }));
    
    return JSON.stringify({ required_fields: requiredFields }, null, 2);
  };

  // Helper: Validate custom field XPath
  const validateCustomField = (field: string): string => {
    if (!field.trim()) {
      return 'Field cannot be empty';
    }
    if (!field.startsWith('//')) {
      return 'XPath must start with // (e.g., //cbc:ID)';
    }
    if (!field.includes(':')) {
      return 'XPath must include namespace prefix (e.g., cbc:, cac:)';
    }
    // Check for valid namespace prefixes
    const validPrefixes = ['cbc:', 'cac:', 'ubl:'];
    const hasValidPrefix = validPrefixes.some(prefix => field.includes(prefix));
    if (!hasValidPrefix) {
      return 'XPath must use valid namespace (cbc:, cac:, or ubl:)';
    }
    return '';
  };

  // Handle adding custom field
  const handleAddCustomField = () => {
    const error = validateCustomField(customField);
    if (error) {
      setCustomFieldError(error);
      return;
    }

    // Check if field already exists
    if (selectedFields[customField]) {
      setCustomFieldError('This field already exists');
      return;
    }

    // Add to selected fields
    setSelectedFields({
      ...selectedFields,
      [customField]: { selected: true, defaultValue: '', expanded: false }
    });

    // Clear custom field inputs
    setCustomField('');
    setCustomFieldLabel('');
    setCustomFieldError('');
  };
  
  // Toggle field selection
  const toggleFieldSelection = (xpath: string) => {
    setSelectedFields(prev => ({
      ...prev,
      [xpath]: {
        selected: !prev[xpath]?.selected,
        defaultValue: prev[xpath]?.defaultValue || '',
        expanded: prev[xpath]?.expanded || false
      }
    }));
  };
  
  // Toggle field expansion
  const toggleFieldExpansion = (xpath: string) => {
    setSelectedFields(prev => ({
      ...prev,
      [xpath]: {
        ...prev[xpath],
        expanded: !prev[xpath]?.expanded
      }
    }));
  };
  
  // Update default value
  const updateDefaultValue = (xpath: string, value: string) => {
    setSelectedFields(prev => ({
      ...prev,
      [xpath]: {
        ...prev[xpath],
        defaultValue: value
      }
    }));
  };

  const openCreateForm = () => {
    setEditingCustomer(null);
    setFormData({
      customer_id: '',
      format: 'edifact',
      validation_rules: '',
    });
    setSelectedFields({});
    setCustomField('');
    setCustomFieldLabel('');
    setCustomFieldError('');
    setShowForm(true);
    setError('');
  };

  const openEditForm = (customer: Customer) => {
    setEditingCustomer(customer);
    setFormData({
      customer_id: customer.customer_id,
      format: customer.format,
      validation_rules: customer.validation_rules || '',
    });
    
    // Parse validation rules to selected fields
    const fields = parseValidationRules(customer.validation_rules || '');
    setSelectedFields(fields);
    
    setCustomField('');
    setCustomFieldLabel('');
    setCustomFieldError('');
    setShowForm(true);
    setError('');
  };

  const closeForm = () => {
    setShowForm(false);
    setEditingCustomer(null);
    setFormData({
      customer_id: '',
      format: 'edifact',
      validation_rules: '',
    });
    setSelectedFields({});
    setCustomField('');
    setCustomFieldLabel('');
    setCustomFieldError('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError('');

    try {
      // Convert selected fields to JSON
      const validationRulesJson = fieldsToValidationRules(selectedFields);
      
      if (editingCustomer) {
        // Update existing customer
        const updateData: any = {};
        if (formData.customer_id !== editingCustomer.customer_id) {
          updateData.customer_id = formData.customer_id;
        }
        if (formData.format !== editingCustomer.format) {
          updateData.format = formData.format;
        }
        if (validationRulesJson !== (editingCustomer.validation_rules || '')) {
          updateData.validation_rules = validationRulesJson;
        }

        if (Object.keys(updateData).length > 0) {
          await customerApi.updateCustomer(editingCustomer.customer_id, updateData);
          setSuccess('Customer updated successfully');
        }
      } else {
        // Create new customer
        await customerApi.createCustomer({
          customer_id: formData.customer_id,
          format: formData.format,
          validation_rules: validationRulesJson || null,
        });
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

  const totalPages = Math.ceil(totalCustomers / itemsPerPage);
  const pageNumbers = Array.from(
    { length: totalPages },
    (_, i) => i + 1
  );

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
          <p className="text-gray-600 ml-11">Manage your EDI customers and their processing formats</p>
        </div>

        {/* Alert Messages */}
        {error && (
          <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3 animate-in">
            <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0 mt-0.5" />
            <div>
              <p className="font-semibold text-red-900">Error</p>
              <p className="text-red-700 text-sm">{error}</p>
            </div>
          </div>
        )}

        {success && (
          <div className="mb-4 p-4 bg-green-50 border border-green-200 rounded-lg flex items-start gap-3 animate-in">
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
              className="w-full pl-10 pr-4 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
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

        {/* Main Content */}
        <div className="grid grid-cols-1 lg:grid-cols-4 gap-4 mb-6">
          {/* Stats Cards */}
          <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-600 text-sm font-medium">Total Customers</p>
                <p className="text-2xl font-bold text-gray-900">{totalCustomers}</p>
              </div>
              <Building2 className="w-8 h-8 text-blue-500 opacity-20" />
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-600 text-sm font-medium">EDIFACT</p>
                <p className="text-2xl font-bold text-gray-900">
                  {customers.filter((c) => c.format === 'edifact').length}
                </p>
              </div>
              <FileText className="w-8 h-8 text-purple-500 opacity-20" />
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-600 text-sm font-medium">X12</p>
                <p className="text-2xl font-bold text-gray-900">
                  {customers.filter((c) => c.format === 'x12').length}
                </p>
              </div>
              <FileText className="w-8 h-8 text-orange-500 opacity-20" />
            </div>
          </div>

          <div className="bg-white rounded-lg shadow-sm p-4 border border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-gray-600 text-sm font-medium">XML Embed</p>
                <p className="text-2xl font-bold text-gray-900">
                  {customers.filter((c) => ['x12_embed', 'xmlembed'].includes(c.format)).length}
                </p>
              </div>
              <FileText className="w-8 h-8 text-indigo-500 opacity-20" />
            </div>
          </div>
        </div>

        {/* Customers Table */}
        <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
          {loading ? (
            <div className="p-8 text-center">
              <Loader className="w-8 h-8 text-blue-500 animate-spin mx-auto mb-2" />
              <p className="text-gray-600">Loading customers...</p>
            </div>
          ) : customers.length === 0 ? (
            <div className="p-8 text-center">
              <Building2 className="w-12 h-12 text-gray-400 mx-auto mb-3" />
              <p className="text-gray-600 font-medium mb-2">No customers found</p>
              <p className="text-gray-500 text-sm mb-4">
                {searchTerm ? 'Try a different search term' : 'Create your first customer to get started'}
              </p>
              {!searchTerm && (
                <button
                  onClick={openCreateForm}
                  className="inline-flex items-center gap-2 bg-blue-500 hover:bg-blue-600 text-white px-4 py-2 rounded-lg font-medium transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  Create Customer
                </button>
              )}
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50">
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Customer ID
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Source Format
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Target Format
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Required Fields
                      </th>
                      <th className="px-6 py-3 text-left text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Created
                      </th>
                      <th className="px-6 py-3 text-right text-xs font-semibold text-gray-900 uppercase tracking-wide">
                        Actions
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-200">
                    {customers.map((customer) => (
                      <tr
                        key={customer.id}
                        className="hover:bg-blue-50 transition-colors group"
                      >
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 bg-blue-500 rounded-full"></div>
                            <span className="font-semibold text-gray-900">
                              {customer.customer_id}
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                                FORMAT_INFO[customer.format]?.bgColor || 'bg-gray-100',
                                FORMAT_INFO[customer.format]?.color || 'text-gray-800'
                              )}
                            >
                              XML
                            </span>
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap">
                          <div className="flex items-center gap-2">
                            <span
                              className={cn(
                                'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium',
                                FORMAT_INFO[customer.format]?.bgColor || 'bg-gray-100',
                                FORMAT_INFO[customer.format]?.color || 'text-gray-800'
                              )}
                            >
                              {FORMAT_INFO[customer.format]?.targetFormat || customer.format.toUpperCase()}
                            </span>
                            <button
                              onClick={() => {
                                setSelectedFormatInfo(customer.format);
                                setShowFormatInfo(true);
                              }}
                              className="text-gray-400 hover:text-gray-600 transition-colors"
                              title="View processing steps"
                            >
                              <AlertCircle className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="text-sm text-gray-600">
                            {customer.validation_rules ? (
                              <span className="inline-flex items-center gap-1 text-green-600">
                                <CheckCircle className="w-4 h-4" />
                                {(() => {
                                  try {
                                    const rules = JSON.parse(customer.validation_rules || '{"required_fields": []}');
                                    const fields = rules.required_fields || [];
                                    return fields.length;
                                  } catch {
                                    return 0;
                                  }
                                })()} fields
                              </span>
                            ) : (
                              <span className="text-gray-400">—</span>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-600">
                          {new Date(customer.created_at).toLocaleDateString()}
                        </td>
                        <td className="px-6 py-4 whitespace-nowrap text-right">
                          <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                            <button
                              onClick={() => openEditForm(customer)}
                              className="p-2 hover:bg-blue-100 rounded-lg text-blue-600 transition-colors"
                              title="Edit customer"
                            >
                              <Edit2 className="w-4 h-4" />
                            </button>
                            <button
                              onClick={() => {
                                setCustomerToDelete(customer);
                                setShowDeleteConfirm(true);
                              }}
                              className="p-2 hover:bg-red-100 rounded-lg text-red-600 transition-colors"
                              title="Delete customer"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="px-6 py-4 border-t border-gray-200 flex items-center justify-between">
                  <p className="text-sm text-gray-600">
                    Showing {currentPage * itemsPerPage + 1} to{' '}
                    {Math.min((currentPage + 1) * itemsPerPage, totalCustomers)} of{' '}
                    {totalCustomers} customers
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
                      disabled={currentPage === 0}
                      className="px-3 py-1 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Previous
                    </button>
                    {pageNumbers.slice(0, 5).map((pageNum) => (
                      <button
                        key={pageNum}
                        onClick={() => setCurrentPage(pageNum - 1)}
                        className={cn(
                          'px-3 py-1 rounded-lg text-sm font-medium transition-colors',
                          currentPage === pageNum - 1
                            ? 'bg-blue-500 text-white'
                            : 'border border-gray-300 text-gray-700 hover:bg-gray-50'
                        )}
                      >
                        {pageNum}
                      </button>
                    ))}
                    {totalPages > 5 && (
                      <span className="px-3 py-1 text-gray-500">...</span>
                    )}
                    <button
                      onClick={() => setCurrentPage(Math.min(totalPages - 1, currentPage + 1))}
                      disabled={currentPage === totalPages - 1}
                      className="px-3 py-1 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                    >
                      Next
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Create/Edit Form Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-md max-h-[90vh] overflow-y-auto">
            <div className="sticky top-0 bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-white">
                {editingCustomer ? 'Edit Customer' : 'Create New Customer'}
              </h2>
              <button
                onClick={closeForm}
                className="text-white hover:bg-white/20 rounded-lg p-1 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="p-6 space-y-4">
              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-1">
                  Customer ID *
                </label>
                <input
                  type="text"
                  value={formData.customer_id}
                  onChange={(e) =>
                    setFormData({ ...formData, customer_id: e.target.value })
                  }
                  disabled={!!editingCustomer}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100 disabled:cursor-not-allowed"
                  placeholder="e.g., ACME_CORP_01"
                  required
                />
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-1">
                  Processing Format
                </label>
                <select
                  value={formData.format}
                  onChange={(e) =>
                    setFormData({ ...formData, format: e.target.value })
                  }
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                >
                  {supportedFormats.map((format) => (
                    <option key={format} value={format}>
                      {FORMAT_INFO[format]?.name || format.toUpperCase()} - {FORMAT_INFO[format]?.description || 'Custom format'}
                    </option>
                  ))}
                </select>
                {FORMAT_INFO[formData.format] && (
                  <div className="mt-2 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                    <p className="text-sm text-blue-900 font-medium mb-1">
                      XML → {FORMAT_INFO[formData.format].targetFormat}
                    </p>
                    <p className="text-xs text-blue-700">
                      {FORMAT_INFO[formData.format].description}
                    </p>
                  </div>
                )}
              </div>

              <div>
                <label className="block text-sm font-semibold text-gray-900 mb-2">
                  Required XML Fields (Optional)
                </label>
                <p className="text-xs text-gray-600 mb-3">
                  Select which fields must be present in the XML invoice and optionally set default values.
                </p>
                
                {/* Checkbox list by category */}
                <div className="max-h-96 overflow-y-auto border border-gray-200 rounded-lg p-3 space-y-3">
                  {['Invoice Header', 'Party Information', 'Tax Information', 'Financial Information', 'Line Items', 'PEPPOL'].map(category => {
                    const categoryFields = availableFields.filter(f => f.category === category);
                    return (
                      <div key={category} className="space-y-2">
                        <h4 className="text-xs font-semibold text-gray-700 uppercase tracking-wide">{category}</h4>
                        {categoryFields.map((field) => (
                          <div key={field.value} className="space-y-1">
                            <div className="flex items-center gap-2">
                              <input
                                type="checkbox"
                                id={`field-${field.value}`}
                                checked={selectedFields[field.value]?.selected || false}
                                onChange={() => toggleFieldSelection(field.value)}
                                className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                              />
                              <label htmlFor={`field-${field.value}`} className="flex-1 text-sm text-gray-900 cursor-pointer">
                                {field.label}
                              </label>
                              {selectedFields[field.value]?.selected && (
                                <button
                                  type="button"
                                  onClick={() => toggleFieldExpansion(field.value)}
                                  className="text-xs text-blue-600 hover:text-blue-800 transition-colors flex items-center gap-1"
                                >
                                  {selectedFields[field.value]?.expanded ? '▼' : '▶'} Default
                                </button>
                              )}
                            </div>
                            {selectedFields[field.value]?.selected && selectedFields[field.value]?.expanded && (
                              <div className="ml-6 p-2 bg-gray-50 border border-gray-200 rounded">
                                <input
                                  type="text"
                                  value={selectedFields[field.value]?.defaultValue || ''}
                                  onChange={(e) => updateDefaultValue(field.value, e.target.value)}
                                  placeholder="Enter default value (optional)"
                                  className="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                                />
                                <p className="text-xs text-gray-500 mt-1">
                                  Will be used if field is missing or empty
                                </p>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    );
                  })}
                  
                  {/* Custom fields */}
                  {Object.entries(selectedFields).filter(([xpath]) => !availableFields.some(f => f.value === xpath)).map(([xpath, data]) => (
                    <div key={xpath} className="space-y-1 border-t pt-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="checkbox"
                          id={`field-${xpath}`}
                          checked={data.selected}
                          onChange={() => toggleFieldSelection(xpath)}
                          className="w-4 h-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                        />
                        <label htmlFor={`field-${xpath}`} className="flex-1 text-sm text-gray-900 cursor-pointer font-mono">
                          {xpath}
                        </label>
                        {data.selected && (
                          <button
                            type="button"
                            onClick={() => toggleFieldExpansion(xpath)}
                            className="text-xs text-blue-600 hover:text-blue-800 transition-colors flex items-center gap-1"
                          >
                            {data.expanded ? '▼' : '▶'} Default
                          </button>
                        )}
                      </div>
                      {data.selected && data.expanded && (
                        <div className="ml-6 p-2 bg-gray-50 border border-gray-200 rounded">
                          <input
                            type="text"
                            value={data.defaultValue || ''}
                            onChange={(e) => updateDefaultValue(xpath, e.target.value)}
                            placeholder="Enter default value (optional)"
                            className="w-full px-2 py-1 text-xs border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
                          />
                          <p className="text-xs text-gray-500 mt-1">
                            Will be used if field is missing or empty
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {/* Custom field input */}
                <div className="mt-3 space-y-2">
                  <label className="block text-xs font-medium text-gray-700">
                    Add custom XPath field:
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={customField}
                      onChange={(e) => {
                        setCustomField(e.target.value);
                        setCustomFieldError('');
                      }}
                      onKeyPress={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          handleAddCustomField();
                        }
                      }}
                      className={cn(
                        "flex-1 px-3 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500",
                        customFieldError ? "border-red-300" : "border-gray-300"
                      )}
                      placeholder="e.g., //cbc:CustomField"
                    />
                    <button
                      type="button"
                      onClick={handleAddCustomField}
                      className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 transition-colors text-sm font-medium"
                    >
                      Add
                    </button>
                  </div>
                  {customFieldError && (
                    <p className="text-xs text-red-600">
                      {customFieldError}
                    </p>
                  )}
                </div>

                {/* Selected count */}
                {Object.values(selectedFields).filter(f => f.selected).length > 0 && (
                  <div className="mt-3 p-2 bg-green-50 border border-green-200 rounded text-sm text-green-800">
                    ✓ {Object.values(selectedFields).filter(f => f.selected).length} field{Object.values(selectedFields).filter(f => f.selected).length !== 1 ? 's' : ''} selected
                  </div>
                )}
              </div>

              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
                  {error}
                </div>
              )}

              <div className="flex gap-3 pt-4">
                <button
                  type="button"
                  onClick={closeForm}
                  disabled={submitting}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 text-white rounded-lg font-medium transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {submitting ? (
                    <>
                      <Loader className="w-4 h-4 animate-spin" />
                      Saving...
                    </>
                  ) : (
                    <>
                      <Check className="w-4 h-4" />
                      Save Customer
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
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-sm">
            <div className="p-6">
              <div className="flex items-center justify-center w-12 h-12 bg-red-100 rounded-full mx-auto mb-4">
                <AlertCircle className="w-6 h-6 text-red-600" />
              </div>
              <h3 className="text-lg font-bold text-gray-900 text-center mb-2">
                Delete Customer?
              </h3>
              <p className="text-gray-600 text-center mb-6">
                Are you sure you want to delete{' '}
                <span className="font-semibold">{customerToDelete.customer_id}</span>?
                This action cannot be undone.
              </p>

              <div className="flex gap-3">
                <button
                  onClick={() => setShowDeleteConfirm(false)}
                  disabled={submitting}
                  className="flex-1 px-4 py-2 border border-gray-300 rounded-lg text-gray-700 font-medium hover:bg-gray-50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  Cancel
                </button>
                <button
                  onClick={handleDelete}
                  disabled={submitting}
                  className="flex-1 flex items-center justify-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
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
        </div>
      )}

      {/* Format Information Modal */}
      {showFormatInfo && selectedFormatInfo && FORMAT_INFO[selectedFormatInfo] && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-lg shadow-xl w-full max-w-lg">
            <div className="sticky top-0 bg-gradient-to-r from-blue-500 to-indigo-600 px-6 py-4 flex items-center justify-between rounded-t-lg">
              <div className="flex items-center gap-3">
                <FileText className="w-6 h-6 text-white" />
                <h2 className="text-lg font-bold text-white">
                  {FORMAT_INFO[selectedFormatInfo].name} Format
                </h2>
              </div>
              <button
                onClick={() => {
                  setShowFormatInfo(false);
                  setSelectedFormatInfo(null);
                }}
                className="text-white hover:bg-white/20 rounded-lg p-1 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-4">
              {/* Format Description */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-2">Description</h3>
                <p className="text-sm text-gray-600">
                  {FORMAT_INFO[selectedFormatInfo].description}
                </p>
              </div>

              {/* Conversion Path */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-2">Conversion Path</h3>
                <div className="flex items-center gap-2 p-3 bg-gray-50 rounded-lg">
                  <span className="px-2.5 py-1 bg-blue-100 text-blue-800 rounded text-xs font-medium">
                    XML
                  </span>
                  <ArrowRight className="w-4 h-4 text-gray-400" />
                  <span className={cn(
                    'px-2.5 py-1 rounded text-xs font-medium',
                    FORMAT_INFO[selectedFormatInfo].bgColor,
                    FORMAT_INFO[selectedFormatInfo].color
                  )}>
                    {FORMAT_INFO[selectedFormatInfo].targetFormat}
                  </span>
                </div>
              </div>

              {/* Processing Steps */}
              <div>
                <h3 className="text-sm font-semibold text-gray-900 mb-2">Processing Steps</h3>
                <div className="space-y-2">
                  {FORMAT_INFO[selectedFormatInfo].steps.map((step, index) => (
                    <div key={index} className="flex items-start gap-3 p-2 rounded-lg hover:bg-gray-50">
                      <div className="flex-shrink-0 w-6 h-6 bg-blue-500 text-white rounded-full flex items-center justify-center text-xs font-bold mt-0.5">
                        {index + 1}
                      </div>
                      <span className="text-sm text-gray-700 flex-1">{step}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Note */}
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg">
                <div className="flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-amber-600 flex-shrink-0 mt-0.5" />
                  <p className="text-xs text-amber-800">
                    Processing times vary by file size and complexity. Average: 3-15 seconds.
                  </p>
                </div>
              </div>
            </div>

            <div className="px-6 pb-6">
              <button
                onClick={() => {
                  setShowFormatInfo(false);
                  setSelectedFormatInfo(null);
                }}
                className="w-full px-4 py-2 bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 text-white rounded-lg font-medium transition-all"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
