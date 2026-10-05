'use client';

import { useState, useEffect } from 'react';
import { X, Save, AlertCircle, Edit } from 'lucide-react';
import { invoicesV2Api } from '@/lib/api';

interface ValidatedInvoice {
  id: number;
  invoice_data: {
    customer_id?: string;
    customer_name?: string;
    [key: string]: any;
  };
  missing_fields?: string[];
}

interface Props {
  invoice: ValidatedInvoice;
  onClose: () => void;
  onSuccess: () => void;
  enableReprocess?: boolean; // Kept for backwards compatibility but not used
}

interface LineItem {
  line_id?: string;
  item_name?: string;
  item_description?: string;
  quantity?: string;
  unit_code?: string;
  price?: string;
  line_amount?: string;
  seller_item_id?: string;
  buyer_item_id?: string;
  standard_item_id?: string;
  tax_percentage?: string;
  origin_country?: string;
  commodity_code?: string;
  line_note?: string;
}

export default function ManualEditModal({ invoice, onClose, onSuccess, enableReprocess = false }: Props) {
  const [editableFields, setEditableFields] = useState<Record<string, string>>({});
  const [lineItems, setLineItems] = useState<LineItem[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showLineItemsEditor, setShowLineItemsEditor] = useState(false);

  const missingFields = invoice.missing_fields || [];

  // Define which fields should be editable (exclude complex objects and arrays)
  const editableFieldNames = [
    // Invoice Header & Metadata
    'invoice_number',
    'issue_date',
    'due_date',
    'currency',
    'invoice_type_code',
    'customization_id',
    'profile_id',
    'note',
    'accounting_cost',
    'buyer_reference',
    // Invoice Period
    'invoice_period_start',
    'invoice_period_end',
    // References
    'order_reference',
    'sales_order_id',
    'contract_reference',
    'project_reference',
    // Customer Information
    'customer_id',
    'customer_id_scheme',
    'customer_name',
    'customer_tax_id',
    'customer_legal_name',
    'customer_company_legal_form',
    'customer_contact_name',
    'customer_contact_telephone',
    'customer_contact_email',
    // Supplier Information
    'supplier_id',
    'supplier_id_scheme',
    'supplier_name',
    'supplier_tax_id',
    'supplier_legal_name',
    'supplier_company_legal_form',
    'supplier_contact_name',
    'supplier_contact_telephone',
    'supplier_contact_email',
    // Payment Information
    'payment_means_code',
    'payment_means_name',
    'payment_id',
    'payment_terms',
    // Tax Information
    'tax_amount',
    'tax_percentage',
    'taxable_amount',
    'tax_category_id',
    'tax_scheme',
    // Monetary Totals
    'line_extension_amount',
    'subtotal',
    'total',
    'payable_amount',
    'allowance_total_amount',
    'charge_total_amount',
    'prepaid_amount',
    // Delivery Information
    'delivery_date',
    'delivery_location_id',
    'delivery_party_name'
  ];

  // Initialize with current values
  useEffect(() => {
    const initial: Record<string, string> = {};
    editableFieldNames.forEach(field => {
      const value = invoice.invoice_data[field];
      if (value !== undefined && value !== null && typeof value !== 'object') {
        initial[field] = String(value);
      } else {
        initial[field] = '';
      }
    });
    setEditableFields(initial);

    // Initialize line items
    if (invoice.invoice_data.line_items && Array.isArray(invoice.invoice_data.line_items)) {
      setLineItems(invoice.invoice_data.line_items.map((item: any) => ({
        line_id: item.line_id || item.id || '',
        item_name: item.item_name || '',
        item_description: item.item_description || '',
        quantity: item.quantity || '',
        unit_code: item.unit_code || '',
        price: item.price || '',
        line_amount: item.line_amount || '',
        seller_item_id: item.seller_item_id || '',
        buyer_item_id: item.buyer_item_id || '',
        standard_item_id: item.standard_item_id || '',
        tax_percentage: item.tax_percentage || '',
        origin_country: item.origin_country || '',
        commodity_code: item.commodity_code || '',
        line_note: item.line_note || '',
      })));
    } else {
      setLineItems([]);
    }
  }, [invoice]);

  const handleChange = (field: string, value: string) => {
    setEditableFields(prev => ({
      ...prev,
      [field]: value
    }));
  };

  const formatFieldName = (field: string) => {
    return field
      .split('_')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  };

  const getFieldPlaceholder = (field: string): string => {
    const placeholders: Record<string, string> = {
      // IDs
      supplier_id: 'e.g., 9429033821733',
      customer_id: 'e.g., 9429033591476',
      customer_id_scheme: 'e.g., 0088',
      supplier_id_scheme: 'e.g., 0088',
      // Dates
      due_date: 'YYYY-MM-DD',
      issue_date: 'YYYY-MM-DD',
      invoice_period_start: 'YYYY-MM-DD',
      invoice_period_end: 'YYYY-MM-DD',
      delivery_date: 'YYYY-MM-DD',
      // Currency & Amounts
      currency: 'e.g., NZD',
      total: 'e.g., 1595.51',
      subtotal: 'e.g., 1387.40',
      tax_amount: 'e.g., 208.11',
      taxable_amount: 'e.g., 1387.40',
      payable_amount: 'e.g., 1595.51',
      line_extension_amount: 'e.g., 1487.40',
      allowance_total_amount: 'e.g., 100.00',
      prepaid_amount: 'e.g., 0.00',
      // Tax
      tax_percentage: 'e.g., 15',
      tax_category_id: 'e.g., S',
      tax_scheme: 'e.g., GST',
      // Contact
      customer_contact_email: 'e.g., contact@customer.com',
      supplier_contact_email: 'e.g., contact@supplier.com',
      customer_contact_telephone: 'e.g., +64 21 123 4567',
      supplier_contact_telephone: 'e.g., +64 21 890 1234',
      // Payment
      payment_means_code: 'e.g., 30',
      payment_means_name: 'e.g., Credit transfer',
      payment_id: 'e.g., INV-12345',
      payment_terms: 'e.g., Payment within 30 days',
      // References
      order_reference: 'e.g., PO-12345',
      sales_order_id: 'e.g., SO-67890',
      contract_reference: 'e.g., CT-11111',
      project_reference: 'e.g., PRJ-22222',
    };
    return placeholders[field] || `Enter ${formatFieldName(field).toLowerCase()}`;
  };

  const handleLineItemChange = (index: number, field: keyof LineItem, value: string) => {
    setLineItems(prev => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  };

  const handleAddLineItem = () => {
    setLineItems(prev => [
      ...prev,
      {
        line_id: String(prev.length + 1),
        item_name: '',
        quantity: '1',
        unit_code: 'C62',
        price: '0',
        line_amount: '0'
      }
    ]);
  };

  const handleRemoveLineItem = (index: number) => {
    setLineItems(prev => prev.filter((_, i) => i !== index));
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);

      // Find fields that have been changed or filled (only send corrections)
      const corrections: Record<string, any> = {};
      const originalData = invoice.invoice_data;

      editableFieldNames.forEach(field => {
        const newValue = editableFields[field]?.trim();
        const oldValue = originalData[field] ? String(originalData[field]) : '';
        
        // Include if it's a missing field or if value changed
        if (missingFields.includes(field) || (newValue && newValue !== oldValue)) {
          if (newValue) {
            corrections[field] = newValue;
          }
        }
      });

      // Add line items if they were edited
      const originalLineItems = originalData.line_items || [];
      
      // Normalize line items for comparison (convert to same format)
      const normalizeLineItem = (item: any) => ({
        line_id: String(item.line_id || item.id || ''),
        item_name: String(item.item_name || ''),
        item_description: String(item.item_description || ''),
        quantity: String(item.quantity || ''),
        unit_code: String(item.unit_code || ''),
        price: String(item.price || ''),
        line_amount: String(item.line_amount || ''),
        seller_item_id: String(item.seller_item_id || ''),
        buyer_item_id: String(item.buyer_item_id || ''),
        standard_item_id: String(item.standard_item_id || ''),
        tax_percentage: String(item.tax_percentage || ''),
        origin_country: String(item.origin_country || ''),
        commodity_code: String(item.commodity_code || ''),
        line_note: String(item.line_note || ''),
      });
      
      const normalizedCurrent = lineItems.map(normalizeLineItem);
      const normalizedOriginal = originalLineItems.map(normalizeLineItem);
      
      const lineItemsChanged = JSON.stringify(normalizedCurrent) !== JSON.stringify(normalizedOriginal);
      
      if (lineItemsChanged) {
        // Send line items with proper structure (convert back to appropriate types)
        corrections['line_items'] = lineItems.map(item => {
          const cleaned: any = {
            line_id: item.line_id || String(lineItems.indexOf(item) + 1),
            item_name: item.item_name || '',
            quantity: parseFloat(item.quantity ?? '') || 0,
            unit_code: item.unit_code || 'C62',
            price: parseFloat(item.price ?? '') || 0,
            line_amount: parseFloat(item.line_amount ?? '') || 0,
          };
          
          // Add optional fields if they have values
          if (item.item_description) cleaned.item_description = item.item_description;
          if (item.seller_item_id) cleaned.seller_item_id = item.seller_item_id;
          if (item.buyer_item_id) cleaned.buyer_item_id = item.buyer_item_id;
          if (item.standard_item_id) cleaned.standard_item_id = item.standard_item_id;
          if (item.tax_percentage) cleaned.tax_percentage = parseFloat(item.tax_percentage ?? '');
          if (item.origin_country) cleaned.origin_country = item.origin_country;
          if (item.commodity_code) cleaned.commodity_code = item.commodity_code;
          if (item.line_note) cleaned.line_note = item.line_note;
          
          return cleaned;
        });
        
        console.log('✏️ Line items changed, sending to backend:', corrections['line_items']);
      }

      if (Object.keys(corrections).length === 0) {
        setError('No changes detected. Please modify at least one field.');
        setSaving(false);
        return;
      }

      // Call API to save corrections (backend will auto-validate and update status)
      const result = await invoicesV2Api.manualFix(invoice.id, corrections);

      // Show success message with new status
      const statusMessage = result.new_status === 'success' 
        ? 'Invoice is now validated successfully!' 
        : `${result.remaining_missing_fields?.length || 0} field(s) still missing.`;
      
      alert(`Successfully saved ${Object.keys(corrections).length} correction(s)! ${statusMessage}`);
      onSuccess();
    } catch (err: any) {
      console.error('Failed to save corrections:', err);
      setError(err.message || 'Failed to save corrections');
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
      {/* Overlay */}
      <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>

      {/* Modal */}
      <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div className="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-2xl">
          {/* Header */}
          <div className="bg-white px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-gray-900" id="modal-title">
                Edit Invoice Fields
              </h3>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500 transition-colors"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
          </div>

          {/* Content */}
          <div className="bg-white px-6 py-6">
            <div className="space-y-6">
              {/* Info Alert */}
              <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
                <div className="flex items-start">
                  <Edit className="h-5 w-5 text-blue-600 mr-3 flex-shrink-0 mt-0.5" />
                  <div>
                    <h4 className="text-sm font-medium text-blue-800 mb-1">Edit Invoice Fields</h4>
                    <p className="text-sm text-blue-700">
                      You can edit any field below. Corrections for <strong>{invoice.invoice_data.customer_name || 'this customer'}</strong> will be saved
                      to the cache and automatically applied to future invoices with the same customer ID.
                      <span className="block mt-2 font-semibold">
                        ✨ After saving, the invoice will be automatically re-validated. If all required fields are present, it will move to the Successful tab!
                      </span>
                    </p>
                  </div>
                </div>
              </div>

              {/* Error Message */}
              {error && (
                <div className="bg-red-50 border border-red-200 rounded-md p-4">
                  <p className="text-sm text-red-700">{error}</p>
                </div>
              )}

              {/* Missing Fields Alert */}
              {missingFields.length > 0 && (
                <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
                  <div className="flex items-start">
                    <AlertCircle className="h-5 w-5 text-yellow-600 mr-3 flex-shrink-0 mt-0.5" />
                    <div>
                      <h4 className="text-sm font-medium text-yellow-800 mb-1">Missing Fields</h4>
                      <p className="text-sm text-yellow-700">
                        {missingFields.map(formatFieldName).join(', ')}
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Editable Fields - Organized by Section */}
              <div className="space-y-6">
                {/* Invoice Header Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Invoice Header
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['invoice_number', 'issue_date', 'due_date', 'currency', 'invoice_type_code']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Customer Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Customer Information
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['customer_id', 'customer_name', 'customer_tax_id', 'customer_legal_name']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Supplier Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Supplier Information
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['supplier_id', 'supplier_name', 'supplier_tax_id', 'supplier_legal_name']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Monetary Fields */}
                <div className="space-y-3">
                  <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide border-b pb-2">
                    Monetary Details
                  </h4>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {['subtotal', 'tax_amount', 'total', 'line_extension_amount', 'payable_amount']
                      .filter(field => editableFields[field] !== undefined)
                      .map(field => (
                        <div key={field}>
                          <label htmlFor={field} className="block text-sm font-medium text-gray-700 mb-1">
                            {formatFieldName(field)}
                            {missingFields.includes(field) && <span className="text-red-500 ml-1">* Missing</span>}
                          </label>
                          <input
                            type="text"
                            id={field}
                            value={editableFields[field] || ''}
                            onChange={(e) => handleChange(field, e.target.value)}
                            placeholder={getFieldPlaceholder(field)}
                            className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                          />
                        </div>
                      ))}
                  </div>
                </div>

                {/* Line Items (Products) Editor */}
                <div className="space-y-3">
                  <div className="flex items-center justify-between border-b pb-2">
                    <h4 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
                      Line Items / Products ({lineItems.length})
                    </h4>
                    <button
                      type="button"
                      onClick={() => setShowLineItemsEditor(!showLineItemsEditor)}
                      className="text-xs text-blue-600 hover:text-blue-700 font-medium"
                    >
                      {showLineItemsEditor ? 'Hide' : 'Show'} Editor
                    </button>
                  </div>

                  {showLineItemsEditor && (
                    <div className="space-y-4">
                      <button
                        type="button"
                        onClick={handleAddLineItem}
                        className="w-full py-2 px-4 border border-dashed border-gray-300 rounded-md text-sm text-gray-600 hover:border-blue-500 hover:text-blue-600 transition-colors"
                      >
                        + Add Product Line
                      </button>

                      {lineItems.map((item, index) => (
                        <div key={index} className="border border-gray-200 rounded-lg p-4 space-y-3 bg-gray-50">
                          <div className="flex items-center justify-between mb-2">
                            <h5 className="text-sm font-medium text-gray-900">Product #{index + 1}</h5>
                            <button
                              type="button"
                              onClick={() => handleRemoveLineItem(index)}
                              className="text-xs text-red-600 hover:text-red-700 font-medium"
                            >
                              Remove
                            </button>
                          </div>

                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {/* Item Name */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Item Name *
                              </label>
                              <input
                                type="text"
                                value={item.item_name || ''}
                                onChange={(e) => handleLineItemChange(index, 'item_name', e.target.value)}
                                placeholder="e.g., True-Widgets"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Quantity */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Quantity *
                              </label>
                              <input
                                type="text"
                                value={item.quantity || ''}
                                onChange={(e) => handleLineItemChange(index, 'quantity', e.target.value)}
                                placeholder="e.g., 10"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Unit Code */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Unit of Measure *
                              </label>
                              <input
                                type="text"
                                value={item.unit_code || ''}
                                onChange={(e) => handleLineItemChange(index, 'unit_code', e.target.value)}
                                placeholder="e.g., C62, DAY, M66"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Price */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Unit Price
                              </label>
                              <input
                                type="text"
                                value={item.price || ''}
                                onChange={(e) => handleLineItemChange(index, 'price', e.target.value)}
                                placeholder="e.g., 29.99"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Line Amount */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Line Amount
                              </label>
                              <input
                                type="text"
                                value={item.line_amount || ''}
                                onChange={(e) => handleLineItemChange(index, 'line_amount', e.target.value)}
                                placeholder="e.g., 299.90"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Seller Item ID */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Seller Item ID
                              </label>
                              <input
                                type="text"
                                value={item.seller_item_id || ''}
                                onChange={(e) => handleLineItemChange(index, 'seller_item_id', e.target.value)}
                                placeholder="e.g., WG546767"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Buyer Item ID */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Buyer Item ID
                              </label>
                              <input
                                type="text"
                                value={item.buyer_item_id || ''}
                                onChange={(e) => handleLineItemChange(index, 'buyer_item_id', e.target.value)}
                                placeholder="e.g., W659590"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Standard Item ID */}
                            <div>
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Standard Item ID
                              </label>
                              <input
                                type="text"
                                value={item.standard_item_id || ''}
                                onChange={(e) => handleLineItemChange(index, 'standard_item_id', e.target.value)}
                                placeholder="e.g., WG546767"
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>

                            {/* Item Description */}
                            <div className="md:col-span-2">
                              <label className="block text-xs font-medium text-gray-700 mb-1">
                                Item Description
                              </label>
                              <textarea
                                value={item.item_description || ''}
                                onChange={(e) => handleLineItemChange(index, 'item_description', e.target.value)}
                                placeholder="e.g., Widgets True and Fair"
                                rows={2}
                                className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 text-sm"
                              />
                            </div>
                          </div>
                        </div>
                      ))}

                      {lineItems.length === 0 && (
                        <div className="text-center py-6 text-gray-500 text-sm">
                          No line items. Click "Add Product Line" to create one.
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Footer */}
          <div className="bg-gray-50 px-6 py-4 border-t border-gray-200 flex justify-end gap-3">
            <button
              onClick={onClose}
              disabled={saving}
              className="px-4 py-2 bg-white border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="inline-flex items-center px-4 py-2 bg-blue-600 border border-transparent rounded-md text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {saving ? (
                <>
                  <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                  </svg>
                  Saving & Validating...
                </>
              ) : (
                <>
                  <Save className="h-4 w-4 mr-2" />
                  Save & Validate
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
