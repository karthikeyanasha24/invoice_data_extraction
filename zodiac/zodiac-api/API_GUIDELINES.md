# Invoice Data Extraction API Guidelines

## Overview

This document provides comprehensive guidelines for the Invoice Data Extraction API endpoints. The API processes invoice files (XML format), validates them, converts them to EDI format, and manages the processing workflow.

---

## Authentication

### Web UI Authentication
- Endpoints prefixed without `/api/` use session-based authentication (cookies)
- Requires an active session established through the login flow
- Used by: `/invoices/process`, `/invoices/success`, `/invoices/failed`

### API Key Authentication
- Endpoints prefixed with `/api/` use API Key authentication
- Include the API key in the request header: `X-API-Key: <api_key>`
- Used by: `/invoices/api/process`
- API keys can be generated via `/invoices/api-key/generate`

---

## Endpoints

### 1. POST `/invoices/process`

**Description:** Process an uploaded invoice file with XML validation and EDI conversion. This endpoint is used by the Web UI and requires session authentication.

**Authentication:** Session-based (Cookie)

**Request Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `file` | File | Yes | Invoice file in XML format (multipart/form-data) |
| `strict_validation` | Boolean | No | Enable strict validation mode (default: false) |

**Request Example:**
```bash
curl -X POST "http://localhost:8000/invoices/process" \
  -H "Cookie: session=..." \
  -F "file=@invoice.xml" \
  -F "strict_validation=false"
```

**Response Model:** `InvoiceProcessingResponse`

**Success Response (200 OK):**
```json
{
  "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
  "processing_steps": [
    {
      "step_name": "File Upload",
      "step_number": 1,
      "success": true,
      "duration_seconds": 0.123,
      "message": "File uploaded successfully",
      "status": {
        "file_upload_pass": true,
        "file_upload_message": "Invoice file received"
      },
      "error_details": null
    },
    {
      "step_name": "XML Validation",
      "step_number": 2,
      "success": true,
      "duration_seconds": 0.456,
      "message": "XML validation passed",
      "status": {
        "xml_validation_pass": true,
        "xml_convert_message": "Valid PEPPOL UBL 2.1 invoice"
      },
      "error_details": null
    },
    {
      "step_name": "Customer Lookup",
      "step_number": 3,
      "success": true,
      "duration_seconds": 0.089,
      "message": "Customer found and configured",
      "status": null,
      "error_details": null
    },
    {
      "step_name": "EDI Conversion",
      "step_number": 4,
      "success": true,
      "duration_seconds": 0.234,
      "message": "X12 EDI conversion successful",
      "status": {
        "edi_convert_pass": true,
        "edi_convert_message": "X12 810 format generated"
      },
      "error_details": null
    },
    {
      "step_name": "Third-party Endpoint",
      "step_number": 5,
      "success": true,
      "duration_seconds": 1.567,
      "message": "Document sent to external service",
      "status": null,
      "error_details": null
    },
    {
      "step_name": "Database Save",
      "step_number": 6,
      "success": true,
      "duration_seconds": 0.045,
      "message": "Invoice saved to success table",
      "status": null,
      "error_details": null
    }
  ]
}
```

**Error Response (4xx/5xx):**
```json
{
  "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
  "processing_steps": [
    {
      "step_name": "XML Validation",
      "step_number": 2,
      "success": false,
      "duration_seconds": 0.234,
      "message": "XML validation failed",
      "status": {
        "xml_validation_pass": false,
        "xml_convert_message": "Invalid PEPPOL CustomizationID"
      },
      "error_details": [
        {
          "error_code": "E2003",
          "error_category": "XML_VALIDATION",
          "error_message": "Missing required element: cbc:ID in cac:OrderReference",
          "severity": "CRITICAL",
          "user_message": "The invoice is missing the OrderReference ID. This is a required field in PEPPOL invoices.",
          "technical_details": "The XML element at path //cac:OrderReference/cbc:ID is required but not present in the invoice document.",
          "suggested_actions": [
            "Add an OrderReference ID to your invoice",
            "Verify the invoice structure matches PEPPOL UBL 2.1 standard",
            "Check the invoice template used for generation"
          ],
          "severity": "CRITICAL",
          "is_recoverable": true,
          "estimated_fix_time": "5-10 minutes",
          "documentation_links": [
            "https://peppol.eu/invoice-specification/"
          ]
        }
      ]
    }
  ]
}
```

**Status Codes:**
| Code | Description |
|------|-------------|
| 200 | Processing completed (check processing_steps for status details) |
| 400 | Invalid request (missing file, invalid format) |
| 401 | Unauthorized (no valid session) |
| 500 | Server error during processing |

**Processing Steps Details:**

1. **File Upload** - Validates file type and size
2. **XML Validation** - Validates PEPPOL UBL 2.1 invoice structure
3. **Customer Lookup** - Identifies customer and applies configuration
4. **EDI Conversion** - Converts XML to X12 810 format
5. **Third-party Endpoint** - Sends EDI file to external validation/processing service
6. **Database Save** - Saves invoice to success or failed table based on workflow status

**Notes:**
- Use `tracking_id` to retrieve detailed invoice information later
- All steps are tracked even on failure for debugging purposes
- The invoice is saved to the database regardless of success/failure status
- Check `processing_steps[].success` to determine overall workflow result

---

### 2. GET `/invoices/success`

**Description:** Retrieve a paginated list of successfully processed invoices for the current user.

**Authentication:** Session-based (Cookie)

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `skip` | Integer | No | 0 | Number of records to skip for pagination |
| `limit` | Integer | No | 100 | Maximum number of records to return (max 1000) |

**Request Example:**
```bash
curl -X GET "http://localhost:8000/invoices/success?skip=0&limit=10" \
  -H "Cookie: session=..."
```

**Response Model:** `List[ZodiacInvoiceSuccessEdi]`

**Success Response (200 OK):**
```json
[
  {
    "id": 1,
    "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
    "user_id": 5,
    "uploaded_at": "2025-01-15T10:30:45.123456",
    "xml_path": "/uploads/invoice_001.xml",
    "xml_validation_pass": true,
    "xml_convert_message": "Valid PEPPOL UBL 2.1 invoice",
    "edi_path": "/uploads/invoice_001.x12",
    "edi_convert_pass": true,
    "edi_convert_message": "X12 810 conversion successful",
    "blob_xml_path": "az://container/invoice_001.xml",
    "blob_edi_path": "az://container/invoice_001.x12",
    "xml_content": "",
    "edi_content": "",
    "external_status": "SUCCESS",
    "external_message": "Document accepted",
    "target_file_format": "x12",
    "invoice_id": "INV-2025-001",
    "customer_name": "Acme Corporation"
  },
  {
    "id": 2,
    "tracking_id": "660f9511-f40c-52e5-b827-557766551111",
    "user_id": 5,
    "uploaded_at": "2025-01-15T11:45:30.654321",
    "xml_path": "/uploads/invoice_002.xml",
    "xml_validation_pass": true,
    "xml_convert_message": "Valid PEPPOL UBL 2.1 invoice",
    "edi_path": "/uploads/invoice_002.x12",
    "edi_convert_pass": true,
    "edi_convert_message": "X12 810 conversion successful",
    "blob_xml_path": "az://container/invoice_002.xml",
    "blob_edi_path": "az://container/invoice_002.x12",
    "xml_content": "",
    "edi_content": "",
    "external_status": "SUCCESS",
    "external_message": "Document accepted",
    "target_file_format": "x12",
    "invoice_id": "INV-2025-002",
    "customer_name": "Beta Industries"
  }
]
```

**Error Response (401 Unauthorized):**
```json
{
  "detail": "Not authenticated"
}
```

**Status Codes:**
| Code | Description |
|------|-------------|
| 200 | Successfully retrieved invoices |
| 401 | Unauthorized (no valid session) |
| 500 | Server error |

**Field Descriptions:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | Integer | Unique database record identifier |
| `tracking_id` | UUID | Unique tracking identifier for the invoice processing |
| `user_id` | Integer | ID of the user who uploaded the invoice |
| `uploaded_at` | DateTime | ISO 8601 timestamp of upload |
| `xml_path` | String | Local file path to XML file |
| `xml_validation_pass` | Boolean | Whether XML validation succeeded |
| `xml_convert_message` | String | Message from XML validation step |
| `edi_path` | String | Local file path to EDI file |
| `edi_convert_pass` | Boolean | Whether EDI conversion succeeded |
| `edi_convert_message` | String | Message from EDI conversion step |
| `blob_xml_path` | String | Azure Blob Storage path to XML (if enabled) |
| `blob_edi_path` | String | Azure Blob Storage path to EDI (if enabled) |
| `target_file_format` | String | Target EDI format (x12, edifact, etc.) |
| `external_status` | String | Status from external service (SUCCESS, ERROR, etc.) |
| `external_message` | String | Message from external service |

**Pagination Notes:**
- Total count not included in response; use skip and limit for navigation
- Results are ordered by `uploaded_at` DESC (newest first)
- Maximum limit of 1000 records per request

---

### 3. GET `/invoices/failed`

**Description:** Retrieve a paginated list of failed invoices for the current user. Failed invoices include detailed error information in the `processing_steps` field.

**Authentication:** Session-based (Cookie)

**Query Parameters:**
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `skip` | Integer | No | 0 | Number of records to skip for pagination |
| `limit` | Integer | No | 100 | Maximum number of records to return (max 1000) |

**Request Example:**
```bash
curl -X GET "http://localhost:8000/invoices/failed?skip=0&limit=10" \
  -H "Cookie: session=..."
```

**Response Model:** `List[ZodiacInvoiceFailedEdi]`

**Success Response (200 OK):**
```json
[
  {
    "id": 42,
    "tracking_id": "770g0622-g51d-63f6-c938-668877662222",
    "user_id": 5,
    "uploaded_at": "2025-01-14T14:22:15.987654",
    "xml_path": "/uploads/bad_invoice_001.xml",
    "xml_validation_pass": false,
    "xml_convert_message": "XML validation failed",
    "edi_path": null,
    "edi_convert_pass": false,
    "edi_convert_message": "EDI conversion skipped due to earlier failure",
    "blob_xml_path": "az://container/bad_invoice_001.xml",
    "blob_edi_path": null,
    "xml_content": "<?xml version=\"1.0\"?>...",
    "edi_content": "",
    "target_file_format": "x12",
    "processing_steps": [
      {
        "step_name": "File Upload",
        "step_number": 1,
        "success": true,
        "duration_seconds": 0.105,
        "message": "File uploaded successfully",
        "status": {
          "file_upload_pass": true,
          "file_upload_message": "Invoice file received"
        },
        "error_details": null
      },
      {
        "step_name": "XML Validation",
        "step_number": 2,
        "success": false,
        "duration_seconds": 0.234,
        "message": "XML validation failed",
        "status": {
          "xml_validation_pass": false,
          "xml_convert_message": "Invalid PEPPOL CustomizationID"
        },
        "error_details": [
          {
            "error_code": "E2001",
            "error_category": "XML_VALIDATION",
            "error_message": "Invalid CustomizationID: Expected 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0'",
            "severity": "CRITICAL",
            "user_message": "Your invoice has an invalid CustomizationID. This field must match the PEPPOL standard format.",
            "technical_details": "The cbc:CustomizationID element contains an invalid identifier. Valid PEPPOL CustomizationID: urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
            "suggested_actions": [
              "Update your invoice template to use the correct PEPPOL CustomizationID",
              "Verify your XML generation tool supports PEPPOL UBL 2.1",
              "Check the invoice structure against the PEPPOL specification"
            ],
            "severity": "CRITICAL",
            "is_recoverable": true,
            "estimated_fix_time": "5-15 minutes",
            "documentation_links": [
              "https://peppol.eu/invoice-specification/",
              "https://docs.peppol.eu/poacc/billing/3.0/"
            ]
          }
        ]
      }
    ]
  }
]
```

**Error Response (401 Unauthorized):**
```json
{
  "detail": "Not authenticated"
}
```

**Status Codes:**
| Code | Description |
|------|-------------|
| 200 | Successfully retrieved failed invoices |
| 401 | Unauthorized (no valid session) |
| 500 | Server error |

**Key Differences from Success Endpoint:**
- Includes full `processing_steps` array with detailed error information
- `xml_content` and `edi_content` are populated for debugging
- `edi_path` and `edi_convert_pass` may be null/false if conversion never occurred
- Each error in `processing_steps[].error_details` includes comprehensive remediation guidance

**Error Details Structure:**

Each error in `processing_steps[].error_details` contains:

| Field | Type | Description |
|-------|------|-------------|
| `error_code` | String | Unique error identifier (e.g., "E2001", "E4010") |
| `error_category` | String | Category of error (XML_VALIDATION, EDI_FORMAT_VALIDATION, etc.) |
| `error_message` | String | Technical error message |
| `severity` | String | CRITICAL, ERROR, or WARNING |
| `user_message` | String | User-friendly explanation |
| `technical_details` | String | Detailed technical explanation |
| `suggested_actions` | List[String] | Steps to resolve the error |
| `is_recoverable` | Boolean | Whether the invoice can be fixed and reprocessed |
| `estimated_fix_time` | String | Approximate time to fix (e.g., "5-10 minutes") |
| `documentation_links` | List[String] | Links to relevant documentation |

---

### 4. GET `/invoices/failed/{tracking_id}`

**Description:** Retrieve a specific failed invoice by its tracking ID. Includes all file contents (XML and EDI) and detailed error information.

**Authentication:** Session-based (Cookie)

**Path Parameters:**
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `tracking_id` | UUID | Yes | The unique tracking ID from the processing response |

**Request Example:**
```bash
curl -X GET "http://localhost:8000/invoices/failed/550e8400-e29b-41d4-a716-446655440000" \
  -H "Cookie: session=..."
```

**Response Model:** `ZodiacInvoiceFailedEdi`

**Success Response (200 OK):**
```json
{
  "id": 42,
  "tracking_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": 5,
  "uploaded_at": "2025-01-14T14:22:15.987654",
  "xml_path": "/uploads/bad_invoice_001.xml",
  "xml_validation_pass": false,
  "xml_convert_message": "XML validation failed - Invalid CustomizationID",
  "edi_path": null,
  "edi_convert_pass": false,
  "edi_convert_message": "EDI conversion skipped due to earlier failure",
  "blob_xml_path": "az://container/bad_invoice_001.xml",
  "blob_edi_path": null,
  "xml_content": "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<Invoice xmlns=\"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2\" xmlns:cac=\"urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2\" xmlns:cbc=\"urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2\">...",
  "edi_content": "",
  "target_file_format": "x12",
  "processing_steps": [
    {
      "step_name": "File Upload",
      "step_number": 1,
      "success": true,
      "duration_seconds": 0.105,
      "message": "File uploaded successfully",
      "status": {
        "file_upload_pass": true,
        "file_upload_message": "Invoice file received"
      },
      "error_details": null
    },
    {
      "step_name": "XML Validation",
      "step_number": 2,
      "success": false,
      "duration_seconds": 0.234,
      "message": "XML validation failed",
      "status": {
        "xml_validation_pass": false,
        "xml_convert_message": "Invalid PEPPOL CustomizationID"
      },
      "error_details": [
        {
          "error_code": "E2001",
          "error_category": "XML_VALIDATION",
          "error_message": "Invalid CustomizationID: Expected 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0'",
          "severity": "CRITICAL",
          "user_message": "Your invoice has an invalid CustomizationID. This field must match the PEPPOL standard format.",
          "technical_details": "The cbc:CustomizationID element contains: 'urn:wrong:customization:id'. Valid PEPPOL CustomizationID: urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0",
          "suggested_actions": [
            "Update your invoice template to use the correct PEPPOL CustomizationID",
            "Verify your XML generation tool supports PEPPOL UBL 2.1",
            "Check the invoice structure against the PEPPOL specification"
          ],
          "severity": "CRITICAL",
          "is_recoverable": true,
          "estimated_fix_time": "5-15 minutes",
          "documentation_links": [
            "https://peppol.eu/invoice-specification/",
            "https://docs.peppol.eu/poacc/billing/3.0/"
          ]
        }
      ]
    },
    {
      "step_name": "Customer Lookup",
      "step_number": 3,
      "success": false,
      "duration_seconds": 0.045,
      "message": "Customer lookup skipped due to earlier failure",
      "status": null,
      "error_details": null
    }
  ]
}
```

**Not Found Response (404):**
```json
{
  "detail": "Failed invoice not found"
}
```

**Unauthorized Response (401):**
```json
{
  "detail": "Not authenticated"
}
```

**Status Codes:**
| Code | Description |
|------|-------------|
| 200 | Successfully retrieved invoice |
| 401 | Unauthorized (no valid session) |
| 404 | Invoice not found or doesn't belong to current user |
| 500 | Server error |

**Use Cases:**
1. **Display detailed error information** - Show user the exact problem and how to fix it
2. **Debug invoice processing** - View full XML and error context
3. **Retrieve processing history** - Access complete processing timeline with step durations
4. **Implement retry logic** - Use `is_recoverable` flag to determine if reprocessing is possible

**Differences from /failed Endpoint:**
- Returns single invoice instead of paginated list
- Includes full `xml_content` for debugging
- Provides access to specific tracking_id without pagination
- More detailed response for single-invoice workflows

---

## Common Response Structures

### DetailedErrorInfo Object
```json
{
  "error_code": "E2001",
  "error_category": "XML_VALIDATION",
  "error_message": "Technical error message",
  "severity": "CRITICAL",
  "user_message": "User-friendly explanation",
  "technical_details": "Detailed technical info",
  "suggested_actions": [
    "Action 1",
    "Action 2"
  ],
  "is_recoverable": true,
  "estimated_fix_time": "5-10 minutes",
  "documentation_links": [
    "https://docs.example.com"
  ]
}
```

### ProcessingStepResult Object
```json
{
  "step_name": "Step Name",
  "step_number": 1,
  "success": true,
  "duration_seconds": 0.123,
  "message": "Step message",
  "status": {
    "field_pass": true,
    "field_message": "Status message"
  },
  "error_details": []
}
```

---

## Error Handling

### HTTP Status Codes
| Code | Meaning | Action |
|------|---------|--------|
| 200 | Success | Use the response data |
| 400 | Bad Request | Verify request parameters |
| 401 | Unauthorized | Check authentication/session |
| 403 | Forbidden | User lacks permission |
| 404 | Not Found | Resource doesn't exist |
| 500 | Server Error | Check server logs, retry later |

### Processing Failures
Even when the HTTP response is 200, check `processing_steps[].success` for each step:
- `success: true` - Step completed without errors
- `success: false` - Step failed; check `error_details` for remediation

### Error Categories
| Category | Description |
|----------|-------------|
| FILE_UPLOAD | Issues with file upload or format |
| XML_VALIDATION | XML structure or PEPPOL compliance issues |
| CUSTOMER_LOOKUP | Customer not found or misconfigured |
| EDI_CONVERSION | Errors during XML to EDI conversion |
| THIRD_PARTY_API | Issues with external service communication |
| DATABASE | Errors saving to database |

---

## Best Practices

### 1. Use Tracking IDs for Audit Trail
```javascript
// Store tracking_id for customer support reference
const trackingId = response.tracking_id;
console.log(`Invoice processing tracked under ID: ${trackingId}`);
```

### 2. Parse Processing Steps for Detailed Feedback
```javascript
// Check each step's success status
response.processing_steps.forEach(step => {
  if (!step.success && step.error_details) {
    console.error(`Step ${step.step_number} (${step.step_name}) failed:`);
    step.error_details.forEach(error => {
      console.error(`  - ${error.user_message}`);
      console.error(`  - Suggested actions: ${error.suggested_actions.join(', ')}`);
    });
  }
});
```

### 3. Implement Retry Logic for Recoverable Errors
```javascript
// Only allow retry if all errors are marked as recoverable
const canRetry = response.processing_steps
  .filter(step => !step.success)
  .every(step => step.error_details?.every(err => err.is_recoverable));

if (canRetry) {
  console.log("Invoice can be corrected and reprocessed");
}
```

### 4. Display User-Friendly Messages
```javascript
// Use user_message for UI display, technical_details for support
if (!step.success && step.error_details) {
  step.error_details.forEach(error => {
    // Show to user
    ui.showError(error.user_message);
    
    // Log for debugging
    console.debug(error.technical_details);
    
    // Show suggested actions
    ui.showActions(error.suggested_actions);
  });
}
```

### 5. Handle Pagination Correctly
```javascript
// Get all failed invoices with pagination
let allFailed = [];
let skip = 0;
const limit = 100;

while (true) {
  const response = await fetch(`/invoices/failed?skip=${skip}&limit=${limit}`);
  const invoices = await response.json();
  
  if (invoices.length === 0) break;
  
  allFailed = allFailed.concat(invoices);
  skip += limit;
}
```

### 6. Store Tracking IDs for Later Reference
```javascript
// After processing, store tracking_id in your database
const invoice = {
  tracking_id: response.tracking_id,
  uploaded_at: new Date(),
  status: 'processing',
  ...otherData
};

// Later, retrieve specific invoice details
const failedInvoice = await fetch(
  `/invoices/failed/${invoice.tracking_id}`
);
```

---

## Rate Limiting

- Currently: **No rate limiting enforced**
- Recommended: Implement client-side rate limiting
  - Max 10 requests/second per user
  - Max 100 concurrent requests

---

## Data Retention

- **Successful invoices**: Retained indefinitely
- **Failed invoices**: Retained indefinitely
- **File contents**: Stored in local filesystem or Azure Blob Storage
- **Processing history**: Stored in `processing_steps` field

---

## Support

For issues or questions about the API:
1. Check the error details in the response (user_message, suggested_actions)
2. Review the documentation_links provided in error responses
3. Contact support with the tracking_id for investigation

---

## Changelog

### Version 1.0 (Current)
- Initial release with core endpoints: /process, /success, /failed, /failed/{tracking_id}
- Comprehensive error details with suggested actions
- Processing steps tracking with step-level error information
- Support for both local filesystem and Azure Blob Storage

