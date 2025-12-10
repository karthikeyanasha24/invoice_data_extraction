# Validation Rules User Manual

## Overview

The Zodiac Invoice Management System allows you to define **customer-specific validation rules** to ensure that XML invoices contain all required fields before processing. This feature helps maintain data quality and catch missing information early in the workflow.

---

## Table of Contents

1. [What are Validation Rules?](#what-are-validation-rules)
2. [How Validation Rules Work](#how-validation-rules-work)
3. [Setting Up Validation Rules](#setting-up-validation-rules)
4. [XPath Syntax Guide](#xpath-syntax-guide)
5. [Common Required Fields](#common-required-fields)
6. [Examples](#examples)
7. [Best Practices](#best-practices)
8. [Troubleshooting](#troubleshooting)

---

## What are Validation Rules?

**Validation Rules** are customer-specific requirements that define which XML elements **must be present** in an invoice before it can be processed. 

### Key Features:
- ✅ **Customer-specific**: Each customer can have different requirements
- ✅ **XPath-based**: Use standard XPath notation to specify fields
- ✅ **Non-blocking by default**: Missing fields generate warnings, not errors
- ✅ **Strict mode available**: Can enforce required fields as hard requirements

### Default Validation

Even without custom rules, the system validates these fields by default:
- Invoice ID (`//cbc:ID`)
- Invoice Issue Date (`//cbc:IssueDate`)
- Supplier Information (`//cac:AccountingSupplierParty`)
- Customer Information (`//cac:AccountingCustomerParty`)
- Total Payable Amount (`//cac:LegalMonetaryTotal/cbc:PayableAmount`)

---

## How Validation Rules Work

### Processing Flow

```
1. Upload XML Invoice
   ↓
2. Extract Customer ID/Name from XML
   ↓
3. Look up Customer in Database
   ↓
4. Load Customer's Validation Rules
   ↓
5. Validate XML Against:
   - Default required fields (always checked)
   - Customer-specific required fields (if defined)
   ↓
6. Report Results:
   - All fields present → Continue processing
   - Fields missing → Warning (or error in strict mode)
```

### Validation Modes

#### **Normal Mode** (Default)
- Missing fields generate **warnings**
- Processing continues
- User notified of missing data
- Invoice still processed

#### **Strict Mode**
- Missing fields generate **errors**
- Processing stops
- Invoice saved to failed table
- User must fix and resubmit

---

## Setting Up Validation Rules

### Step 1: Navigate to Customer Management

1. Log in to Zodiac system
2. Click **"Customers"** in the navigation menu
3. You'll see the Customer Management panel

### Step 2: Create or Edit Customer

#### Creating a New Customer:
1. Click **"Add Customer"** button
2. Fill in:
   - **Customer ID**: Unique identifier (e.g., `ACME_CORP_01`)
   - **Processing Format**: Select target format (EDIFACT, X12, etc.)
   - **Required XML Fields**: Define validation rules (see below)

#### Editing an Existing Customer:
1. Find the customer in the table
2. Hover over the row to reveal action buttons
3. Click the **Edit** icon (pencil)
4. Update the **Required XML Fields** section

### Step 3: Define Validation Rules

In the **Required XML Fields** text area, enter a JSON object with this structure:

```json
{
  "required_fields": [
    "//cbc:ID",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cbc:InvoiceTypeCode"
  ]
}
```

### Step 4: Save

Click **"Save Customer"** to apply the validation rules.

---

## XPath Syntax Guide

### What is XPath?

XPath is a query language for selecting elements in XML documents. Think of it as a "path" to find specific data in your XML file.

### Basic Syntax

| Syntax | Meaning | Example |
|--------|---------|---------|
| `//` | Find anywhere in document | `//cbc:ID` |
| `/` | Direct child | `/Invoice/cbc:ID` |
| `@` | Attribute | `//cbc:ID[@schemeID='123']` |
| `[1]` | First element | `//cac:InvoiceLine[1]` |

### UBL Namespaces

UBL XML uses namespaces. The system automatically handles these:

- **cbc**: Common Basic Components (simple fields)
  - Example: `cbc:ID`, `cbc:IssueDate`, `cbc:InvoiceTypeCode`
  
- **cac**: Common Aggregate Components (complex structures)
  - Example: `cac:AccountingSupplierParty`, `cac:InvoiceLine`
  
- **ubl**: UBL Invoice namespace
  - Example: `ubl:Invoice`

### XPath Examples

#### Simple Field
```xpath
//cbc:ID
```
Finds the invoice ID anywhere in the document.

#### Nested Field
```xpath
//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID
```
Finds the supplier's endpoint ID (nested 3 levels deep).

#### Multiple Levels
```xpath
//cac:InvoiceLine/cac:Item/cbc:Name
```
Finds item names within invoice lines.

#### With Conditions
```xpath
//cac:InvoiceLine[cac:Item]
```
Finds invoice lines that contain an Item element.

---

## Common Required Fields

### Invoice Header Fields

```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cbc:DueDate",
    "//cbc:InvoiceTypeCode",
    "//cbc:DocumentCurrencyCode"
  ]
}
```

### Party Information

```json
{
  "required_fields": [
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingSupplierParty/cac:Party/cac:PartyName/cbc:Name",
    "//cac:AccountingCustomerParty/cac:Party/cac:PartyName/cbc:Name"
  ]
}
```

### Financial Information

```json
{
  "required_fields": [
    "//cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount",
    "//cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount",
    "//cac:LegalMonetaryTotal/cbc:PayableAmount",
    "//cac:TaxTotal/cbc:TaxAmount"
  ]
}
```

### Line Items

```json
{
  "required_fields": [
    "//cac:InvoiceLine",
    "//cac:InvoiceLine/cbc:ID",
    "//cac:InvoiceLine/cac:Item/cbc:Name",
    "//cac:InvoiceLine/cbc:InvoicedQuantity",
    "//cac:InvoiceLine/cac:Price/cbc:PriceAmount"
  ]
}
```

---

## Examples

### Example 1: Basic Validation

**Scenario**: Ensure invoice has ID, date, and parties

```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cac:AccountingSupplierParty",
    "//cac:AccountingCustomerParty"
  ]
}
```

**Result**: System checks for these 4 fields + 5 default fields = 9 total validations

### Example 2: PEPPOL Requirements

**Scenario**: Ensure PEPPOL-compliant invoices

```json
{
  "required_fields": [
    "//cbc:CustomizationID",
    "//cbc:ProfileID",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingCustomerParty/cac:Party/cbc:EndpointID",
    "//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID",
    "//cac:AccountingCustomerParty/cac:Party/cac:PartyLegalEntity/cbc:CompanyID"
  ]
}
```

### Example 3: Detailed Line Items

**Scenario**: Ensure all line items have complete information

```json
{
  "required_fields": [
    "//cac:InvoiceLine/cbc:ID",
    "//cac:InvoiceLine/cbc:InvoicedQuantity",
    "//cac:InvoiceLine/cac:Item/cbc:Name",
    "//cac:InvoiceLine/cac:Item/cac:SellersItemIdentification/cbc:ID",
    "//cac:InvoiceLine/cac:Price/cbc:PriceAmount",
    "//cac:InvoiceLine/cbc:LineExtensionAmount"
  ]
}
```

### Example 4: Tax Information

**Scenario**: Ensure tax details are complete

```json
{
  "required_fields": [
    "//cac:TaxTotal/cbc:TaxAmount",
    "//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxableAmount",
    "//cac:TaxTotal/cac:TaxSubtotal/cbc:TaxAmount",
    "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID",
    "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent"
  ]
}
```

### Example 5: No Custom Rules

**Scenario**: Use only default validation

```json
{
  "required_fields": []
}
```

**Or leave the field empty** - both work the same way.

---

## Best Practices

### 1. Start Simple

Begin with a few critical fields:
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cac:AccountingSupplierParty/cac:Party/cbc:EndpointID"
  ]
}
```

Gradually add more as needed.

### 2. Test Your Rules

1. Create a customer with validation rules
2. Upload a test invoice
3. Check the processing steps for validation results
4. Adjust rules based on results

### 3. Use Descriptive Customer IDs

Good: `ACME_CORP_PEPPOL`, `SUPPLIER_X_STRICT`  
Bad: `CUST001`, `TEST`

### 4. Document Your Rules

Add comments in your customer management system about why specific fields are required.

### 5. Balance Strictness

- **Too strict**: Many invoices fail unnecessarily
- **Too lenient**: Bad data gets through
- **Just right**: Catches real issues, allows valid variations

### 6. Consider Format Requirements

Different formats need different fields:

- **EDIFACT**: May need specific party identifiers
- **X12**: May need different tax structures
- **XML Embed**: May need additional metadata

### 7. Monitor Validation Results

Regularly check:
- How many invoices fail validation?
- Which fields are most commonly missing?
- Are rules too strict or too lenient?

---

## Troubleshooting

### Issue: "Invalid XPath expression"

**Cause**: Syntax error in XPath

**Solution**: Check your XPath syntax
- Use `//` for searching anywhere
- Use `/` for direct children
- Check namespace prefixes (`cbc:`, `cac:`)

**Example Fix**:
```
❌ Bad:  /cbc:ID (missing //)
✅ Good: //cbc:ID
```

### Issue: "Field exists but validation fails"

**Cause**: Element exists but is empty

**Solution**: Check if the field has actual content
- System detects empty elements
- Reported as "field_name (empty)"

**Example**:
```xml
<!-- This will fail validation -->
<cbc:ID></cbc:ID>

<!-- This will pass -->
<cbc:ID>INV-12345</cbc:ID>
```

### Issue: "Too many invoices failing"

**Cause**: Rules too strict or incorrect XPath

**Solutions**:
1. Review failed invoices to see common patterns
2. Check if XPath matches actual XML structure
3. Consider making some fields optional
4. Use non-strict mode for warnings instead of errors

### Issue: "Validation rules not applied"

**Cause**: JSON syntax error

**Solution**: Validate your JSON
- Use a JSON validator (jsonlint.com)
- Check for missing quotes, commas, brackets
- Ensure proper escaping

**Example Fix**:
```json
❌ Bad:
{
  required_fields: ["//cbc:ID"]  // Missing quotes around key
}

✅ Good:
{
  "required_fields": ["//cbc:ID"]
}
```

### Issue: "Customer validation error in logs"

**Cause**: Exception during validation (not missing fields)

**Solutions**:
1. Check server logs for detailed error
2. Verify XPath expressions are valid
3. Ensure XML is well-formed
4. Contact support if error persists

---

## Advanced Usage

### Conditional Validation

While the system doesn't support conditional logic directly, you can:

1. **Create multiple customer profiles** for different scenarios
   - `CUSTOMER_A_STANDARD` - Basic validation
   - `CUSTOMER_A_DETAILED` - Strict validation

2. **Use different customer IDs** based on invoice type
   - Route invoices to appropriate customer profile

### Validation in Strict Mode

To enforce required fields as hard requirements:

1. Upload invoice with `strict_validation=true` parameter
2. Missing fields will cause processing to fail
3. Invoice saved to failed table
4. User can edit and resubmit

### Validation Reports

After processing, check the **Processing Steps** to see:
- Which fields were validated
- Which fields were missing
- Validation duration
- Warnings vs errors

---

## Integration with Processing Workflow

### When Validation Runs

```
Step 1: File Upload ✓
Step 2: Early XML Check ✓
Step 3: XML Validation ✓
  ├─ Default field validation
  └─ Customer-specific field validation ← YOUR RULES HERE
Step 4: Format Conversion
Step 5: Format Validation
...
```

### Validation Results

#### All Fields Present
```
✅ Validation passed: All 12 required fields present
```
Processing continues normally.

#### Fields Missing (Normal Mode)
```
⚠️ Customer validation warning: 2 required field(s) missing
- //cac:AccountingSupplierParty/cac:Party/cbc:EndpointID
- //cbc:InvoiceTypeCode
```
Processing continues with warnings.

#### Fields Missing (Strict Mode)
```
❌ Customer validation failed: 2 required field(s) missing
```
Processing stops, invoice saved to failed table.

---

## API Integration

### For API Clients

When uploading via API, validation rules are automatically applied based on the customer identified in the XML.

**Request**:
```bash
curl -X POST "https://api.zodiac.com/api/v1/invoices/api/process" \
  -H "X-API-Key: your-api-key" \
  -F "file=@invoice.xml" \
  -F "strict_validation=false"
```

**Response** (if validation fails):
```json
{
  "tracking_id": "uuid-here",
  "processing_steps": [
    {
      "step_name": "XML Validation",
      "step_number": 3,
      "success": false,
      "message": "Customer validation failed: 2 required field(s) missing",
      "error_details": [
        {
          "error_message": "Missing required field: //cbc:InvoiceTypeCode",
          "severity": "ERROR"
        }
      ]
    }
  ]
}
```

---

## Common Use Cases

### Use Case 1: PEPPOL Invoices

**Requirement**: All PEPPOL invoices must have endpoint IDs

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

### Use Case 2: Tax Compliance

**Requirement**: All invoices must have complete tax information

```json
{
  "required_fields": [
    "//cac:TaxTotal/cbc:TaxAmount",
    "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:ID",
    "//cac:TaxTotal/cac:TaxSubtotal/cac:TaxCategory/cbc:Percent",
    "//cac:AccountingSupplierParty/cac:Party/cac:PartyTaxScheme/cbc:CompanyID"
  ]
}
```

### Use Case 3: Payment Terms

**Requirement**: Invoices must specify payment terms

```json
{
  "required_fields": [
    "//cbc:DueDate",
    "//cac:PaymentMeans/cbc:PaymentMeansCode",
    "//cac:PaymentTerms/cbc:Note"
  ]
}
```

### Use Case 4: Item Details

**Requirement**: All line items must have complete product information

```json
{
  "required_fields": [
    "//cac:InvoiceLine/cac:Item/cbc:Name",
    "//cac:InvoiceLine/cac:Item/cbc:Description",
    "//cac:InvoiceLine/cac:Item/cac:SellersItemIdentification/cbc:ID",
    "//cac:InvoiceLine/cac:Item/cac:StandardItemIdentification/cbc:ID"
  ]
}
```

### Use Case 5: Minimal Validation

**Requirement**: Only check critical fields beyond defaults

```json
{
  "required_fields": [
    "//cbc:InvoiceTypeCode"
  ]
}
```

---

## Testing Your Validation Rules

### Step 1: Create Test Customer

1. Create a customer with ID: `TEST_VALIDATION`
2. Set format: `edifact` (or your preferred format)
3. Add your validation rules

### Step 2: Prepare Test Invoice

Create or use an existing XML invoice that:
- ✅ Has all required fields (should pass)
- ❌ Missing some required fields (should fail/warn)

### Step 3: Upload and Check

1. Upload the test invoice
2. Wait for processing to complete
3. Check the **Processing Steps** section
4. Look for "Customer-specific field validation" step

### Step 4: Review Results

**Success Example**:
```
✅ Step 3A: Customer-specific field validation
   Message: Validation passed: All 8 required fields present
   Duration: 0.2s
```

**Failure Example**:
```
⚠️ Step 3A: Customer-specific field validation
   Message: Customer validation warning: 2 required field(s) missing
   Missing fields:
   - //cbc:InvoiceTypeCode
   - //cac:PaymentMeans/cbc:PaymentMeansCode
```

### Step 5: Adjust Rules

Based on results:
- Add more fields if needed
- Remove overly strict requirements
- Fix XPath syntax errors

---

## Validation Rules JSON Schema

### Complete Schema

```json
{
  "required_fields": [
    "string (XPath expression)",
    "string (XPath expression)",
    "..."
  ]
}
```

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `required_fields` | Array of strings | Yes | List of XPath expressions for required fields |

### Validation

- Must be valid JSON
- `required_fields` must be an array
- Each element must be a string (XPath expression)
- Empty array is valid (no custom validation)

---

## Performance Considerations

### Validation Speed

- **Simple fields**: ~0.01s per field
- **Complex XPath**: ~0.05s per field
- **Total overhead**: Usually <0.5s for 10-20 fields

### Recommendations

1. **Keep it reasonable**: 5-15 custom fields is typical
2. **Avoid wildcards**: Use specific paths when possible
3. **Test performance**: Upload sample invoices to check timing

---

## Security Notes

### XPath Injection

The system uses safe XPath evaluation with:
- ✅ Predefined namespaces only
- ✅ No dynamic code execution
- ✅ Sandboxed XML parsing

### Access Control

- ✅ Only authenticated users can manage customers
- ✅ Validation rules are stored securely in database
- ✅ No external code execution

---

## FAQ

### Q: Can I use wildcards in XPath?

**A**: Yes, but be careful. Example:
```xpath
//cac:InvoiceLine/*/cbc:ID
```
This finds ID elements at any level within InvoiceLine.

### Q: What if my XML uses different namespaces?

**A**: The system automatically handles standard UBL namespaces. For custom namespaces, contact support.

### Q: Can I validate attribute values?

**A**: Yes, use XPath attribute syntax:
```xpath
//cbc:ID[@schemeID='INVOICE']
```

### Q: How do I validate that at least one element exists?

**A**: Just specify the element path:
```xpath
//cac:InvoiceLine
```
This checks that at least one InvoiceLine exists.

### Q: Can I require a minimum number of elements?

**A**: Not directly. The system checks for presence (at least 1). For complex validation, use the validation_rules field for custom logic (future feature).

### Q: What happens if I enter invalid JSON?

**A**: The system logs an error and uses default validation only. Your invoice processing continues, but custom rules are ignored.

### Q: Can I disable default validation?

**A**: No, default fields are always validated. They ensure basic invoice integrity.

### Q: How do I see which fields failed?

**A**: Check the processing steps in the invoice details page. Missing fields are listed with their XPath expressions.

---

## Support

### Getting Help

1. **Check Logs**: Server logs show detailed validation information
2. **Review Processing Steps**: Each invoice shows validation results
3. **Test with Sample Data**: Use test customers to verify rules
4. **Contact Support**: For complex validation requirements

### Useful Resources

- [UBL 2.1 Documentation](http://docs.oasis-open.org/ubl/UBL-2.1.html)
- [XPath Tutorial](https://www.w3schools.com/xml/xpath_intro.asp)
- [PEPPOL BIS Billing 3.0](https://docs.peppol.eu/poacc/billing/3.0/)

---

## Changelog

### Version 1.0 (December 2024)
- Initial release
- XPath-based validation
- Customer-specific rules
- Default required fields
- Strict mode support

---

## Quick Reference Card

### JSON Template
```json
{
  "required_fields": [
    "//cbc:ID",
    "//cbc:IssueDate",
    "//cac:AccountingSupplierParty",
    "//cac:AccountingCustomerParty"
  ]
}
```

### Common XPaths
- Invoice ID: `//cbc:ID`
- Date: `//cbc:IssueDate`
- Supplier: `//cac:AccountingSupplierParty`
- Customer: `//cac:AccountingCustomerParty`
- Amount: `//cac:LegalMonetaryTotal/cbc:PayableAmount`
- Line Items: `//cac:InvoiceLine`

### Validation Flow
1. Upload → 2. Parse XML → 3. Extract Customer → 4. Load Rules → 5. Validate → 6. Report

---

**Last Updated**: December 2024  
**Version**: 1.0  
**System**: Zodiac Invoice Management Platform

