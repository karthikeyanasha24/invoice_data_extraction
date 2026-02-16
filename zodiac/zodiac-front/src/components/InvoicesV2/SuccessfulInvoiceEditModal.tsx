'use client';

import { useState, useEffect } from 'react';
import { X, Save, Plus, Trash2 } from 'lucide-react';
import { invoicesV2Api } from '@/lib/api';

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
}

interface SuccessfulInvoiceEditModalProps {
  invoice: any;
  onClose: () => void;
  onSuccess: () => void;
}

export default function SuccessfulInvoiceEditModal({ invoice, onClose, onSuccess }: SuccessfulInvoiceEditModalProps) {
  const [lineItems, setLineItems] = useState<LineItem[]>([]);
  const [editableFields, setEditableFields] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showFieldsEditor, setShowFieldsEditor] = useState(false);

  // List of commonly edited fields
  const commonEditableFields = [
    'invoice_number', 'issue_date', 'due_date',
    'customer_id', 'customer_name', 'customer_tax_id',
    'supplier_id', 'supplier_name', 'supplier_tax_id',
    'total', 'tax_amount', 'subtotal',
    'currency', 'payment_terms'
  ];

  useEffect(() => {
    // Initialize line items from invoice data
    if (invoice.invoice_data.line_items && Array.isArray(invoice.invoice_data.line_items)) {
      setLineItems(invoice.invoice_data.line_items.map((item: any) => ({
        line_id: item.line_id || item.id || '',
        item_name: item.item_name || '',
        item_description: item.item_description || '',
        quantity: String(item.quantity || ''),
        unit_code: item.unit_code || '',
        price: String(item.price || ''),
        line_amount: String(item.line_amount || ''),
        seller_item_id: item.seller_item_id || '',
        buyer_item_id: item.buyer_item_id || '',
        standard_item_id: item.standard_item_id || '',
        tax_percentage: String(item.tax_percentage || ''),
      })));
    }

    // Initialize editable fields
    const initial: Record<string, string> = {};
    commonEditableFields.forEach(field => {
      const value = invoice.invoice_data[field];
      if (value !== undefined && value !== null && typeof value !== 'object') {
        initial[field] = String(value);
      } else {
        initial[field] = '';
      }
    });
    setEditableFields(initial);
  }, [invoice]);

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

  const handleFieldChange = (field: string, value: string) => {
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

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);

      const updates: Record<string, any> = {};

      // Add line items if modified
      if (lineItems.length > 0) {
        const formattedLineItems = lineItems.map(item => {
          const cleaned: any = {
            line_id: item.line_id || '',
            item_name: item.item_name || '',
            quantity: parseFloat(item.quantity || '0'),
            unit_code: item.unit_code || 'C62',
            price: parseFloat(item.price || '0'),
            line_amount: parseFloat(item.line_amount || '0'),
          };
          
          // Add optional fields if they have values
          if (item.item_description) cleaned.item_description = item.item_description;
          if (item.seller_item_id) cleaned.seller_item_id = item.seller_item_id;
          if (item.buyer_item_id) cleaned.buyer_item_id = item.buyer_item_id;
          if (item.standard_item_id) cleaned.standard_item_id = item.standard_item_id;
          if (item.tax_percentage) cleaned.tax_percentage = parseFloat(item.tax_percentage);
          
          return cleaned;
        });
        updates['line_items'] = formattedLineItems;
      }

      // Add modified fields
      commonEditableFields.forEach(field => {
        const newValue = editableFields[field]?.trim();
        const oldValue = invoice.invoice_data[field] ? String(invoice.invoice_data[field]) : '';
        
        if (newValue && newValue !== oldValue) {
          updates[field] = newValue;
        }
      });

      if (Object.keys(updates).length === 0) {
        setError('No changes detected. Please modify at least one field.');
        setSaving(false);
        return;
      }

      console.log('💾 Saving updates for successful invoice:', updates);

      // Call the new simplified update endpoint
      await invoicesV2Api.updateSuccessfulInvoice(invoice.id, updates);

      alert(`✅ Updated ${Object.keys(updates).length} field(s) successfully!`);
      onSuccess();
    } catch (err: any) {
      console.error('Failed to save:', err);
      setError(err.message || 'Failed to save changes');
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
      {/* Overlay */}
      <div className="fixed inset-0 bg-gray-500 bg-opacity-75 transition-opacity" onClick={onClose}></div>

      {/* Modal */}
      <div className="flex min-h-full items-end justify-center p-4 text-center sm:items-center sm:p-0">
        <div className="relative transform overflow-hidden rounded-lg bg-white text-left shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-4xl">
          {/* Header */}
          <div className="bg-white px-6 py-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xl font-semibold text-gray-900" id="modal-title">
                  Edit Invoice
                </h3>
                <p className="text-sm text-gray-500 mt-1">
                  Invoice: {invoice.invoice_data.invoice_number || 'N/A'} • Edit any field without validation
                </p>
              </div>
              <button
                onClick={onClose}
                className="text-gray-400 hover:text-gray-500"
              >
                <X className="h-6 w-6" />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="bg-white px-6 py-4 max-h-[70vh] overflow-y-auto">
            {error && (
              <div className="mb-4 p-4 bg-red-50 border border-red-200 rounded-md">
                <p className="text-sm text-red-700">{error}</p>
              </div>
            )}

            {/* Invoice Fields Section */}
            <div className="mb-6">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-lg font-semibold text-gray-900">Invoice Fields</h4>
                <button
                  onClick={() => setShowFieldsEditor(!showFieldsEditor)}
                  className="text-sm text-blue-600 hover:text-blue-800"
                >
                  {showFieldsEditor ? 'Hide' : 'Show'} Editor
                </button>
              </div>

              {showFieldsEditor && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 p-4 bg-gray-50 rounded-lg">
                  {commonEditableFields.map(field => (
                    <div key={field}>
                      <label className="block text-sm font-medium text-gray-700 mb-1">
                        {formatFieldName(field)}
                      </label>
                      <input
                        type="text"
                        value={editableFields[field] || ''}
                        onChange={(e) => handleFieldChange(field, e.target.value)}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                        placeholder={`Enter ${formatFieldName(field).toLowerCase()}`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Line Items Section */}
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-lg font-semibold text-gray-900">
                  Line Items / Products ({lineItems.length})
                </h4>
                <button
                  onClick={handleAddLineItem}
                  className="px-3 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm flex items-center gap-2"
                >
                  <Plus className="h-4 w-4" />
                  Add Product
                </button>
              </div>

              {lineItems.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <p>No line items. Click "Add Product" to add one.</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {lineItems.map((item, index) => (
                    <div key={index} className="border border-gray-200 rounded-lg p-4 bg-gray-50">
                      <div className="flex items-center justify-between mb-3">
                        <h5 className="font-semibold text-gray-900">Product {index + 1}</h5>
                        <button
                          onClick={() => handleRemoveLineItem(index)}
                          className="text-red-600 hover:text-red-800"
                          title="Remove product"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {/* Item Name */}
                        <div className="col-span-2">
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Item Name *
                          </label>
                          <input
                            type="text"
                            value={item.item_name}
                            onChange={(e) => handleLineItemChange(index, 'item_name', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="e.g., True-Widgets"
                          />
                        </div>

                        {/* Quantity */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Quantity *
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            value={item.quantity}
                            onChange={(e) => handleLineItemChange(index, 'quantity', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="1"
                          />
                        </div>

                        {/* Unit Code */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Unit of Measure *
                          </label>
                          <input
                            type="text"
                            value={item.unit_code}
                            onChange={(e) => handleLineItemChange(index, 'unit_code', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="e.g., C62, DAY, E99"
                          />
                        </div>

                        {/* Unit Price */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Unit Price
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            value={item.price}
                            onChange={(e) => handleLineItemChange(index, 'price', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="0.00"
                          />
                        </div>

                        {/* Line Amount */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Line Amount
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            value={item.line_amount}
                            onChange={(e) => handleLineItemChange(index, 'line_amount', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="0.00"
                          />
                        </div>

                        {/* Item Description */}
                        <div className="col-span-2">
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Description
                          </label>
                          <textarea
                            value={item.item_description}
                            onChange={(e) => handleLineItemChange(index, 'item_description', e.target.value)}
                            rows={2}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="Product description..."
                          />
                        </div>

                        {/* Seller Item ID */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Seller Item ID
                          </label>
                          <input
                            type="text"
                            value={item.seller_item_id}
                            onChange={(e) => handleLineItemChange(index, 'seller_item_id', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="Optional"
                          />
                        </div>

                        {/* Buyer Item ID */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Buyer Item ID
                          </label>
                          <input
                            type="text"
                            value={item.buyer_item_id}
                            onChange={(e) => handleLineItemChange(index, 'buyer_item_id', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="Optional"
                          />
                        </div>

                        {/* Standard Item ID */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Standard Item ID
                          </label>
                          <input
                            type="text"
                            value={item.standard_item_id}
                            onChange={(e) => handleLineItemChange(index, 'standard_item_id', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="Optional"
                          />
                        </div>

                        {/* Tax Percentage */}
                        <div>
                          <label className="block text-sm font-medium text-gray-700 mb-1">
                            Tax Percentage
                          </label>
                          <input
                            type="number"
                            step="0.01"
                            value={item.tax_percentage}
                            onChange={(e) => handleLineItemChange(index, 'tax_percentage', e.target.value)}
                            className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-blue-500 focus:border-blue-500"
                            placeholder="e.g., 15"
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Footer */}
          <div className="bg-gray-50 px-6 py-4 flex items-center justify-end gap-3 border-t border-gray-200">
            <button
              onClick={onClose}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 rounded-md hover:bg-green-700 disabled:opacity-50 flex items-center gap-2"
            >
              {saving ? (
                <>
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
                  Saving...
                </>
              ) : (
                <>
                  <Save className="h-4 w-4" />
                  Save Changes
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
