# SAP Integration Guide - Zodiac API

## Base URL
```
Production: https://zodiac-back.vercel.app
```

## Authentication
SAP uses **API Key authentication** via header:
```
X-API-Key: <your-api-key>
```

---

## Available Endpoints for SAP

### 1. Health Check Endpoint (Test Connectivity)
**Endpoint:** `GET /api/v1/invoices/api/health-check`

**Purpose:** Test if SAP can reach the API and authenticate

**Request Example:**
```bash
curl -X GET "https://zodiac-back.vercel.app/api/v1/invoices/api/health-check" \
  -H "X-API-Key: YOUR_API_KEY"
```

**Success Response:**
```json
{
  "status": "ok",
  "authenticated": true,
  "user_id": 123,
  "username": "sap_user",
  "email": "sap@example.com",
  "is_active": true,
  "timestamp": "2026-03-02T10:30:00",
  "version": "1.0.0",
  "message": "SAP integration is ready to receive invoices",
  "endpoints": {
    "health_check": "/api/v1/invoices/api/health-check",
    "upload_invoice": "/api/v1/invoices/api/process",
    "check_status": "/api/v1/invoices/status/{tracking_id}"
  }
}
```

---

### 2. Upload Invoice (Main SAP Endpoint)
**Endpoint:** `POST /api/v1/invoices/api/process`

**Purpose:** Upload and process invoice XML files

**Request Example:**
```bash
curl -X POST "https://zodiac-back.vercel.app/api/v1/invoices/api/process" \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@invoice.xml" \
  -F "strict_validation=false"
```

**Parameters:**
- `file` (required): XML invoice file (multipart/form-data)
- `strict_validation` (optional): true/false (default: false)

**Success Response:**
```json
{
  "tracking_id": "INV_20260302_ABC123",
  "status": "processing",
  "message": "Invoice received and processing started",
  "invoice_id": 456,
  "created_at": "2026-03-02T10:35:00"
}
```

**Error Response (Duplicate Invoice):**
```json
{
  "error": "Duplicate invoice detected",
  "invoice_number": "F001-12345",
  "existing_invoice_id": 123,
  "message": "Invoice #F001-12345 has already been successfully processed"
}
```

---

### 3. Check Processing Status
**Endpoint:** `GET /api/v1/invoices/status/{tracking_id}`

**Purpose:** Check the status of a submitted invoice

**Request Example:**
```bash
curl -X GET "https://zodiac-back.vercel.app/api/v1/invoices/status/INV_20260302_ABC123" \
  -H "X-API-Key: YOUR_API_KEY"
```

**Response:**
```json
{
  "tracking_id": "INV_20260302_ABC123",
  "status": "completed",
  "invoice_id": 456,
  "result": {
    "invoice_number": "F001-12345",
    "validation_status": "success",
    "conversion_status": "completed"
  }
}
```

---

## Testing Steps

### Test 1: Verify Connectivity (Health Check)
```bash
curl -X GET "https://zodiac-back.vercel.app/api/v1/invoices/api/health-check" \
  -H "X-API-Key: YOUR_API_KEY" \
  -v
```

**Expected Result:** HTTP 200 with authentication confirmation

**If SSL Error:** Follow SSL certificate installation steps below

---

### Test 2: Upload Test Invoice
```bash
curl -X POST "https://zodiac-back.vercel.app/api/v1/invoices/api/process" \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@test_invoice.xml" \
  -F "strict_validation=false"
```

**Expected Result:** HTTP 200 with tracking_id

---

## SSL Certificate Fix for SAP

### Method 1: Download and Import Certificate to SAP

**Step 1: Download Vercel's Certificate Chain**

Run this on a machine with OpenSSL:
```bash
openssl s_client -servername zodiac-back.vercel.app -connect zodiac-back.vercel.app:443 -showcerts < /dev/null 2>/dev/null | openssl x509 -outform PEM > zodiac_vercel_cert.pem
```

**Step 2: Import Certificate into SAP Trust Manager**

1. Open SAP GUI
2. Run transaction: `STRUST`
3. Select: **SSL Client (Anonymous)** in the tree
4. Double-click to edit
5. Click **"Import Certificate"** button
6. Browse to `zodiac_vercel_cert.pem`
7. Click **"Add to Certificate List"**
8. Click **Save** (disk icon)

**Step 3: Restart SAP ICM**

1. Run transaction: `SMICM`
2. Go to: **Administration → ICM → Exit Soft → Global**
3. Wait 30 seconds
4. ICM will restart automatically

**Step 4: Test Connection**
- Go back to SAP and try your HTTP connection again
- SSL error should be resolved

---

### Method 2: Use Custom Domain (Alternative)

Instead of `zodiac-back.vercel.app`, configure a custom domain like `api.bridgeedi.com` that uses a certificate SAP already trusts (like Let's Encrypt).

---

## Quick Reference: Your API Keys

You need to provide SAP with an API key. To get or create one:

**Option 1: Check existing API keys in your database**
```sql
SELECT id, username, api_key FROM zodiac_users WHERE api_key IS NOT NULL;
```

**Option 2: Generate a new API key for SAP user**
- Log into your admin panel
- Create a user specifically for SAP (e.g., username: "sap_integration")
- Generate an API key for this user
- Use this key in SAP's HTTP configuration

---

## SAP Configuration Settings

In SAP, when configuring the HTTP destination:

| Field | Value |
|-------|-------|
| **Host** | `zodiac-back.vercel.app` |
| **Port** | `443` |
| **Path Prefix** | `/api/v1` |
| **SSL** | Active |
| **Authentication** | Header Field |
| **Header Field Name** | `X-API-Key` |
| **Header Field Value** | `<your-api-key>` |

---

## Testing Checklist

- [ ] Backend deployed successfully on Vercel
- [ ] `/health` endpoint returns 200 OK
- [ ] Certificate imported into SAP STRUST
- [ ] SAP ICM restarted
- [ ] SAP can call health check endpoint successfully
- [ ] SAP can upload a test invoice
- [ ] Invoice processing completes without errors

---

## Need Help?

If you get stuck on any step, let me know which step and what error you're seeing!
