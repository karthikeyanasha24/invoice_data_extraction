# Customer API - CRUD Endpoints Documentation

## Overview
The Customer API provides comprehensive CRUD (Create, Read, Update, Delete) operations for managing customers in the Zodiac system. All endpoints are protected with authentication and require a valid JWT token.

## Base URL
```
http://localhost:8000/api/v1/customers
```

## Authentication
All endpoints require an `Authorization` header with a valid JWT token:
```
Authorization: Bearer <jwt_token>
```

---

## Endpoints

### 1. CREATE - Create a New Customer
**Endpoint:** `POST /api/v1/customers/`

**Description:** Create a new customer record with specified format and validation rules.

**Request Body:**
```json
{
  "customer_id": "ACME_CORP_01",
  "format": "edifact",
  "api_address": "https://api.acme.com/edi",
  "validation_rules": "{\"required_fields\": [\"id\", \"name\"]}"
}
```

**Response (201 Created):**
```json
{
  "id": 1,
  "customer_id": "ACME_CORP_01",
  "format": "edifact",
  "api_address": "https://api.acme.com/edi",
  "validation_rules": "{\"required_fields\": [\"id\", \"name\"]}",
  "created_at": "2025-12-01T10:30:00"
}
```

**Possible Errors:**
- `409 Conflict` - Customer with this ID already exists
- `500 Internal Server Error` - Database error

---

### 2. READ - Get All Customers (with Pagination)
**Endpoint:** `GET /api/v1/customers/`

**Query Parameters:**
- `skip` (integer, default: 0) - Number of records to skip
- `limit` (integer, default: 100, max: 500) - Number of records per page
- `search` (string, optional) - Search by customer_id (case-sensitive substring match)

**Examples:**
```
GET /api/v1/customers/
GET /api/v1/customers/?skip=0&limit=50
GET /api/v1/customers/?search=ACME
GET /api/v1/customers/?skip=10&limit=25&search=CORP
```

**Response (200 OK):**
```json
{
  "total": 42,
  "skip": 0,
  "limit": 10,
  "customers": [
    {
      "id": 1,
      "customer_id": "ACME_CORP_01",
      "format": "edifact",
      "api_address": "https://api.acme.com/edi",
      "validation_rules": "{...}",
      "created_at": "2025-12-01T10:30:00"
    },
    {
      "id": 2,
      "customer_id": "BETA_INC_02",
      "format": "x12",
      "api_address": "https://api.beta.com/edi",
      "validation_rules": null,
      "created_at": "2025-12-01T11:15:00"
    }
  ]
}
```

**Possible Errors:**
- `500 Internal Server Error` - Database error

---

### 3. READ - Get Customer by Customer ID
**Endpoint:** `GET /api/v1/customers/{customer_id}`

**Path Parameters:**
- `customer_id` (string) - Unique customer identifier

**Example:**
```
GET /api/v1/customers/ACME_CORP_01
```

**Response (200 OK):**
```json
{
  "id": 1,
  "customer_id": "ACME_CORP_01",
  "format": "edifact",
  "api_address": "https://api.acme.com/edi",
  "validation_rules": "{...}",
  "created_at": "2025-12-01T10:30:00"
}
```

**Possible Errors:**
- `404 Not Found` - Customer not found
- `500 Internal Server Error` - Database error

---

### 4. READ - Get Customer by Database ID
**Endpoint:** `GET /api/v1/customers/by-id/{db_id}`

**Path Parameters:**
- `db_id` (integer) - Internal database ID

**Example:**
```
GET /api/v1/customers/by-id/1
```

**Response (200 OK):**
```json
{
  "id": 1,
  "customer_id": "ACME_CORP_01",
  "format": "edifact",
  "api_address": "https://api.acme.com/edi",
  "validation_rules": "{...}",
  "created_at": "2025-12-01T10:30:00"
}
```

**Possible Errors:**
- `404 Not Found` - Customer not found
- `500 Internal Server Error` - Database error

---

### 5. UPDATE - Update Customer
**Endpoint:** `PUT /api/v1/customers/{customer_id}`

**Path Parameters:**
- `customer_id` (string) - Unique customer identifier

**Request Body (all fields optional):**
```json
{
  "customer_id": "ACME_CORP_01_UPDATED",
  "format": "x12",
  "api_address": "https://api-new.acme.com/edi",
  "validation_rules": "{\"strict_mode\": true}"
}
```

**Response (200 OK):**
```json
{
  "id": 1,
  "customer_id": "ACME_CORP_01_UPDATED",
  "format": "x12",
  "api_address": "https://api-new.acme.com/edi",
  "validation_rules": "{\"strict_mode\": true}",
  "created_at": "2025-12-01T10:30:00"
}
```

**Possible Errors:**
- `404 Not Found` - Customer not found
- `409 Conflict` - New customer_id already exists
- `500 Internal Server Error` - Database error

---

### 6. DELETE - Delete Customer by Customer ID
**Endpoint:** `DELETE /api/v1/customers/{customer_id}`

**Path Parameters:**
- `customer_id` (string) - Unique customer identifier

**Example:**
```
DELETE /api/v1/customers/ACME_CORP_01
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Customer 'ACME_CORP_01' deleted successfully",
  "deleted_id": 1
}
```

**Possible Errors:**
- `404 Not Found` - Customer not found
- `500 Internal Server Error` - Database error

---

### 7. DELETE - Delete Customer by Database ID
**Endpoint:** `POST /api/v1/customers/by-id/{db_id}/delete`

**Path Parameters:**
- `db_id` (integer) - Internal database ID

**Example:**
```
POST /api/v1/customers/by-id/1/delete
```

**Response (200 OK):**
```json
{
  "success": true,
  "message": "Customer 'ACME_CORP_01' (database ID: 1) deleted successfully",
  "deleted_id": 1
}
```

**Possible Errors:**
- `404 Not Found` - Customer not found
- `500 Internal Server Error` - Database error

---

### 8. UTILITY - Get Supported Formats
**Endpoint:** `GET /api/v1/customers/formats/list`

**Description:** Get list of all supported file formats with descriptions.

**Response (200 OK):**
```json
{
  "supported_formats": [
    "edifact",
    "x12",
    "x12_embed",
    "xml"
  ],
  "descriptions": {
    "edifact": "UN/EDIFACT electronic data interchange format",
    "x12": "ASC X12 EDI format",
    "x12_embed": "X12 embedded in another format",
    "xml": "XML format"
  }
}
```

---

### 9. BULK - Create Multiple Customers
**Endpoint:** `POST /api/v1/customers/bulk/create`

**Description:** Create multiple customers in a single request.

**Request Body:**
```json
[
  {
    "customer_id": "CUSTOMER_001",
    "format": "edifact",
    "api_address": "https://api1.example.com",
    "validation_rules": null
  },
  {
    "customer_id": "CUSTOMER_002",
    "format": "x12",
    "api_address": "https://api2.example.com",
    "validation_rules": "{}"
  },
  {
    "customer_id": "CUSTOMER_003",
    "format": "xml",
    "api_address": null,
    "validation_rules": null
  }
]
```

**Response (200 OK):**
```json
{
  "total": 3,
  "created": 2,
  "failed": 1,
  "created_customer_ids": [
    "CUSTOMER_001",
    "CUSTOMER_002"
  ],
  "failed_customers": [
    {
      "customer_id": "CUSTOMER_003",
      "reason": "Customer already exists"
    }
  ]
}
```

**Possible Errors:**
- `500 Internal Server Error` - Database error

---

## Request/Response Details

### Supported Formats
- `edifact` - UN/EDIFACT electronic data interchange format
- `x12` - ASC X12 EDI format
- `x12_embed` - X12 embedded in another format
- `xml` - XML format

### Field Descriptions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | integer | No | Database ID (read-only) |
| `customer_id` | string | Yes | Unique customer identifier |
| `format` | string | No | Target format (default: "edifact") |
| `api_address` | string | No | API endpoint for this customer |
| `validation_rules` | string | No | JSON string with validation rules |
| `created_at` | datetime | No | Creation timestamp (read-only) |

---

## Error Responses

### 400 Bad Request
```json
{
  "detail": "Invalid request parameters"
}
```

### 404 Not Found
```json
{
  "detail": "Customer with ID 'UNKNOWN' not found"
}
```

### 409 Conflict
```json
{
  "detail": "Customer with ID 'ACME_CORP_01' already exists"
}
```

### 500 Internal Server Error
```json
{
  "detail": "Error creating customer: [error details]"
}
```

---

## Usage Examples

### cURL Examples

**Create a customer:**
```bash
curl -X POST "http://localhost:8000/api/v1/customers/" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "ACME_001",
    "format": "edifact",
    "api_address": "https://api.acme.com"
  }'
```

**List customers with pagination:**
```bash
curl -X GET "http://localhost:8000/api/v1/customers/?skip=0&limit=25" \
  -H "Authorization: Bearer <token>"
```

**Search customers:**
```bash
curl -X GET "http://localhost:8000/api/v1/customers/?search=ACME" \
  -H "Authorization: Bearer <token>"
```

**Get specific customer:**
```bash
curl -X GET "http://localhost:8000/api/v1/customers/ACME_001" \
  -H "Authorization: Bearer <token>"
```

**Update customer:**
```bash
curl -X PUT "http://localhost:8000/api/v1/customers/ACME_001" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "format": "x12",
    "api_address": "https://api-new.acme.com"
  }'
```

**Delete customer:**
```bash
curl -X DELETE "http://localhost:8000/api/v1/customers/ACME_001" \
  -H "Authorization: Bearer <token>"
```

---

## Security Notes

1. All endpoints require authentication via JWT token
2. All customer IDs must be unique
3. Validation rules should be valid JSON when provided
4. API addresses should be valid URLs
5. Bulk operations process all customers even if some fail
6. Database IDs are immutable

---

## Pagination Guidelines

- Default `limit` is 100 records
- Maximum `limit` is 500 records
- Use `skip` parameter to navigate through pages
- Total count is returned for implementing pagination UI

Example: To get page 2 with 25 items per page:
```
GET /api/v1/customers/?skip=25&limit=25
```
