# Validation Rules - Quick Start Guide

## 5-Minute Setup

### 1. Open Customer Management
Navigate to **Customers** page in Zodiac UI

### 2. Add/Edit Customer
Click **"Add Customer"** or edit existing customer

### 3. Enter Validation Rules

Copy and paste this template:

```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:InvoiceTypeCode",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
  ]
}
```

### 4. Save
Click **"Save Customer"**

### 5. Test
Upload an invoice for this customer and check validation results!

---

## Common Templates

### Minimal (Basic Invoice)
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate"
  ]
}
```

### Standard (Business Invoice)
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cbc:DueDate",
    "//cbc:InvoiceTypeCode",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID"
  ]
}
```

### PEPPOL Compliant
```json
{
  "required_fields": [
    "//cbc:CustomizationID",
    "//cbc:ProfileID",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
  ]
}
```

### Complete (Full Validation)
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

---

## XPath Cheat Sheet

### Basic Syntax
| Pattern | Finds |
|---------|-------|
| `//cbc:ID` | Invoice ID (anywhere) |
| `//cbc:IssueDate` | Invoice date |
| `//cac:AccountingSupplierParty` | Supplier info |
| `//cac:AccountingCustomerParty` | Customer info |

### Party Information
| Pattern | Finds |
|---------|-------|
| `//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID` | Supplier endpoint |
| `//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID` | Customer endpoint |
| `//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name` | Supplier name |

### Financial Fields
| Pattern | Finds |
|---------|-------|
| `//cac:LegalMonetaryTotal/cbc:PayableAmount` | Total amount |
| `//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount` | Amount with tax |
| `//cac:TaxTotal/cbc:TaxAmount` | Tax amount |

### Line Items
| Pattern | Finds |
|---------|-------|
| `//cac:InvoiceLine` | At least one line item |
| `//cac:InvoiceLine/cbc:ID` | Line item IDs |
| `//cac:InvoiceLine/cac:Item/cbc:Name` | Item names |
| `//cac:InvoiceLine/cbc:InvoicedQuantity` | Quantities |

---

## Troubleshooting

### ❌ "Invalid JSON"
**Fix**: Check for missing quotes, commas, or brackets
```json
✅ {"required_fields": ["//cbc:ID"]}
❌ {required_fields: ["//cbc:ID"]}
```

### ❌ "Invalid XPath"
**Fix**: Use `//` prefix for searching anywhere
```json
✅ "//cbc:ID"
❌ "cbc:ID"
```

### ❌ "Field exists but validation fails"
**Fix**: Element might be empty
```xml
❌ <cbc:ID></cbc:ID>
✅ <cbc:ID>INV-12345</cbc:ID>
```

---

## Need More Help?

📖 **Full Manual**: See `VALIDATION_RULES_USER_MANUAL.md`  
🔧 **Technical Details**: See `app/services/customer_validation.py`  
📊 **Processing Workflow**: See `PROCESSING_WORKFLOW.md`

---

**Quick Start Complete!** 🎉

Your validation rules are now active and will be applied to all invoices for this customer.

