# Customer Management UI Guide

## Overview
Visual guide to the updated Customer Management interface with validation rules support.

---

## Customer Table Layout

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  Customer Management                                                    [+ Add] │
├─────────────────────────────────────────────────────────────────────────────────┤
│  [Search customers...]                                                          │
├─────────────────────────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ Total        │  │ EDIFACT      │  │ X12          │  │ XML Embed    │      │
│  │ Customers    │  │ Customers    │  │ Customers    │  │ Customers    │      │
│  │     25       │  │     12       │  │      8       │  │      5       │      │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘      │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  Customer ID  │ Source  │ Target Format │ Required Fields │ Created │ Actions │
│  ────────────────────────────────────────────────────────────────────────────  │
│  • ACME_01    │ [XML]   │ [EDIFACT] ⓘ  │ ✓ 8 fields     │ Dec 10  │ ✏️ 🗑️  │
│  • SUPPLIER_X │ [XML]   │ [X12] ⓘ      │ ✓ 12 fields    │ Dec 09  │ ✏️ 🗑️  │
│  • CLIENT_Y   │ [XML]   │ [XML+X12] ⓘ  │ —              │ Dec 08  │ ✏️ 🗑️  │
│                                                                                 │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Color Coding

### Format Badges

| Format | Color | Badge Example |
|--------|-------|---------------|
| EDIFACT | Purple | `🟣 EDIFACT` |
| X12 | Orange | `🟠 X12` |
| XML | Blue | `🔵 XML` |
| X12 Embed | Indigo | `🟣 XML+X12` |
| XML Embed | Teal | `🔵 XML+EDIFACT` |

---

## Customer Form

### Create/Edit Customer Modal

```
┌────────────────────────────────────────────┐
│  Create New Customer                    [×]│
├────────────────────────────────────────────┤
│                                            │
│  Customer ID *                             │
│  [ACME_CORP_01________________]            │
│                                            │
│  Processing Format                         │
│  [▼ EDIFACT - European standard for EDI]   │
│                                            │
│  ┌──────────────────────────────────────┐ │
│  │ ℹ️ XML → EDIFACT                     │ │
│  │ European standard for electronic     │ │
│  │ data interchange                     │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  Required XML Fields (Optional)            │
│  Specify XPath expressions for required    │
│  fields in the XML invoice.                │
│  ┌──────────────────────────────────────┐ │
│  │ {                                    │ │
│  │   "required_fields": [               │ │
│  │     "//cbc:ID",                      │ │
│  │     "//cac:AccountingSupplierParty", │ │
│  │     "//cbc:InvoiceTypeCode"          │ │
│  │   ]                                  │ │
│  │ }                                    │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  ┌──────────────────────────────────────┐ │
│  │ Example: Use XPath notation          │ │
│  │ //cbc:ID - Invoice ID                │ │
│  │ //cac:AccountingSupplierParty        │ │
│  └──────────────────────────────────────┘ │
│                                            │
│  [Cancel]              [✓ Save Customer]  │
└────────────────────────────────────────────┘
```

---

## Format Information Modal

### Clicking the ⓘ icon opens:

```
┌─────────────────────────────────────────────┐
│  📄 EDIFACT Format                      [×] │
├─────────────────────────────────────────────┤
│                                             │
│  Description                                │
│  European standard for electronic data      │
│  interchange                                │
│                                             │
│  Conversion Path                            │
│  ┌─────────────────────────────────────┐   │
│  │ [XML] → [EDIFACT]                   │   │
│  └─────────────────────────────────────┘   │
│                                             │
│  Processing Steps                           │
│  ① XML Validation                           │
│  ② XML → EDIFACT Conversion                 │
│  ③ Database Save                            │
│                                             │
│  ⚠️ Processing times vary by file size      │
│     Average: 3-15 seconds                   │
│                                             │
│  [Close]                                    │
└─────────────────────────────────────────────┘
```

---

## Required Fields Display

### In Customer Table

When customer has validation rules:
```
✓ 8 fields
```
Shows count of custom required fields (green checkmark)

When customer has no validation rules:
```
—
```
Shows dash (gray, indicating no custom rules)

---

## Validation Rules Examples in UI

### Example 1: Minimal
```json
{
  "required_fields": [
    "//cbc:ID"
  ]
}
```
**Display**: ✓ 1 field

### Example 2: Standard
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cbc:DueDate",
    "//cbc:InvoiceTypeCode",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
  ]
}
```
**Display**: ✓ 5 fields

### Example 3: Comprehensive
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cbc:DueDate",
    "//cbc:InvoiceTypeCode",
    "//cbc:DocumentCurrencyCode",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID",
    "//cac:InvoiceLine/cbc:ID",
    "//cac:InvoiceLine/cac:Item/cbc:Name",
    "//cac:TaxTotal/cbc:TaxAmount"
  ]
}
```
**Display**: ✓ 10 fields

---

## User Workflow

### Creating a Customer with Validation Rules

```
Step 1: Click "Add Customer"
   ↓
Step 2: Enter Customer ID (e.g., ACME_CORP_01)
   ↓
Step 3: Select Processing Format (e.g., EDIFACT)
   ↓
Step 4: Enter Required XML Fields (JSON)
   {
     "required_fields": [
       "//cbc:ID",
       "//cbc:InvoiceTypeCode"
     ]
   }
   ↓
Step 5: Click "Save Customer"
   ↓
Step 6: Customer created with validation rules!
```

### Viewing Format Information

```
Step 1: Find customer in table
   ↓
Step 2: Look at "Target Format" column
   ↓
Step 3: Click the ⓘ icon next to format badge
   ↓
Step 4: Modal opens showing:
   - Format description
   - Conversion path
   - Processing steps
   ↓
Step 5: Click "Close" to dismiss
```

### Editing Validation Rules

```
Step 1: Find customer in table
   ↓
Step 2: Hover over row (shows action buttons)
   ↓
Step 3: Click ✏️ Edit button
   ↓
Step 4: Update "Required XML Fields" textarea
   ↓
Step 5: Click "Save Customer"
   ↓
Step 6: Rules updated immediately!
```

---

## Validation Results Display

### In Processing Steps

After uploading an invoice, you'll see:

```
Processing Steps for Invoice #12345

✅ Step 1: File Upload (0.2s)
   File uploaded successfully

✅ Step 2: Early XML Check (0.1s)
   XML file is parseable

✅ Step 3: XML Validation (0.8s)
   XML validation passed

✅ Step 3A: Customer-specific field validation (0.3s)
   Validation passed: All 8 required fields present

✅ Step 4: Format Conversion (2.1s)
   XML → EDIFACT conversion successful
   
...
```

### When Fields Are Missing

```
⚠️ Step 3A: Customer-specific field validation (0.3s)
   Customer validation warning: 2 required field(s) missing
   
   Missing fields:
   • //cbc:InvoiceTypeCode - Invoice Type Code
   • //cac:PaymentMeans/cbc:PaymentMeansCode - Payment Means
   
   ℹ️ Processing continued (non-strict mode)
```

---

## Statistics Dashboard

### Format Distribution

The Customer Management page shows:

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Total        │  │ EDIFACT      │  │ X12          │  │ XML Embed    │
│ Customers    │  │ Customers    │  │ Customers    │  │ Customers    │
│              │  │              │  │              │  │              │
│     25       │  │     12       │  │      8       │  │      5       │
└──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘
```

---

## Mobile Responsive Design

### Desktop View
- Full table with all columns
- Hover effects on action buttons
- Inline format information

### Tablet View
- Scrollable table
- All columns visible
- Touch-friendly buttons

### Mobile View
- Stacked card layout
- Essential information prioritized
- Tap to expand details

---

## Keyboard Shortcuts

| Action | Shortcut |
|--------|----------|
| Add Customer | (Click button) |
| Search | Click search box |
| Close Modal | ESC or click X |
| Save Form | Enter (when in form) |

---

## Accessibility

### Features
- ✅ Keyboard navigation support
- ✅ Screen reader friendly
- ✅ High contrast color schemes
- ✅ Clear focus indicators
- ✅ Descriptive ARIA labels

---

## Tips & Tricks

### 💡 Tip 1: Copy Validation Rules
When creating similar customers, copy validation rules from existing customer and modify.

### 💡 Tip 2: Use Format Info
Click the ⓘ icon to understand what processing steps will run for each format.

### 💡 Tip 3: Start Simple
Begin with 2-3 critical fields, then expand based on needs.

### 💡 Tip 4: Test First
Always test validation rules with sample invoices before production use.

### 💡 Tip 5: Monitor Results
Regularly check processing steps to see if rules are working as expected.

---

## Visual Elements

### Icons Used

| Icon | Meaning |
|------|---------|
| ⓘ | Information - Click to view details |
| ✏️ | Edit - Modify customer |
| 🗑️ | Delete - Remove customer |
| ✓ | Success - Fields configured |
| — | None - No custom rules |
| • | Bullet - Customer entry |

### Status Indicators

| Indicator | Meaning |
|-----------|---------|
| Green checkmark | Custom validation rules defined |
| Gray dash | No custom validation rules |
| Number badge | Count of required fields |

---

## Common Workflows

### Workflow 1: Add PEPPOL Customer

1. Click "Add Customer"
2. Customer ID: `CUSTOMER_PEPPOL_01`
3. Format: `EDIFACT`
4. Required Fields:
   ```json
   {
     "required_fields": [
       "//cbc:CustomizationID",
       "//cbc:ProfileID",
       "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
       "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID"
     ]
   }
   ```
5. Save

### Workflow 2: Update Existing Customer

1. Search for customer
2. Click ✏️ Edit
3. Modify "Required XML Fields"
4. Save
5. Rules apply immediately to new uploads

### Workflow 3: View Format Details

1. Find customer in table
2. Click ⓘ next to Target Format
3. Review processing steps
4. Close modal

---

## Error Handling

### Invalid JSON

**What you see:**
```
❌ Error
Failed to save customer: Invalid JSON in validation rules
```

**How to fix:**
1. Check JSON syntax (use jsonlint.com)
2. Ensure quotes around keys and values
3. Check for missing commas or brackets

### Duplicate Customer ID

**What you see:**
```
❌ Error
Customer with ID 'ACME_01' already exists
```

**How to fix:**
1. Use a different Customer ID
2. Or edit the existing customer instead

### Network Error

**What you see:**
```
❌ Error
Failed to load customers: Network error
```

**How to fix:**
1. Check internet connection
2. Verify API server is running
3. Refresh the page

---

## Best Practices for UI Usage

### ✅ DO:
- Use descriptive Customer IDs
- Test validation rules before production
- Review format information before selecting
- Keep validation rules simple and focused
- Regularly review customer list

### ❌ DON'T:
- Use generic IDs like "TEST" or "CUSTOMER1"
- Add too many required fields (>20)
- Forget to test after creating rules
- Mix different validation approaches for same customer type
- Leave validation rules field with invalid JSON

---

## Quick Reference

### Customer ID Naming Convention

**Recommended Format**: `COMPANY_FORMAT_VERSION`

Examples:
- `ACME_EDIFACT_V1`
- `SUPPLIER_X_X12_STRICT`
- `CLIENT_Y_PEPPOL`

### Format Selection Guide

| Choose | When |
|--------|------|
| EDIFACT | European customers, UN/EDIFACT standard |
| X12 | North American customers, ANSI X12 standard |
| XML | No conversion needed, passthrough |
| X12 Embed | Need X12 embedded in XML for API |
| XML Embed | Need EDIFACT embedded in XML for API |

### Validation Rules Template

Copy this template to get started:

```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
  ]
}
```

Then customize by adding/removing fields.

---

## Support

### Need Help?

1. **In-app Help**: Click ⓘ icons for context-specific information
2. **Documentation**: See `VALIDATION_RULES_USER_MANUAL.md`
3. **Quick Start**: See `VALIDATION_RULES_QUICK_START.md`
4. **Technical Support**: Contact your system administrator

---

**UI Version**: 2.0  
**Last Updated**: December 2024  
**Platform**: Zodiac Invoice Management System

