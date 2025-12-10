# Invoice Processing Workflow Documentation

## Overview

The Zodiac Invoice Management System processes XML invoice files and converts them to various EDI formats (EDIFACT, X12) based on customer requirements. The system includes intelligent error correction, format validation, and third-party API integration.

---

## Accepted File Formats

### Input Files
- **Content Type**: `text/xml` or `application/xml`
- **File Extension**: `.xml`
- **Format**: UBL (Universal Business Language) XML invoices

### Output Formats
Based on customer configuration, the system converts XML to:
- **EDIFACT**: European standard for electronic data interchange
- **X12**: North American EDI standard
- **XML Embed**: XML with embedded EDIFACT/X12 content

---

## Processing Steps

### Step 1: File Upload
**Duration**: ~0.1-0.5s  
**Purpose**: Receive and store the uploaded XML file

**Actions**:
- Validate content type (`text/xml` or `application/xml`)
- Validate filename exists
- Generate tracking ID (UUID)
- Save file to storage (local or Vercel Blob)
- Initialize status tracker for real-time updates

**Success Criteria**:
- File successfully uploaded and saved
- Tracking ID generated

**Possible Errors**:
- Invalid content type
- Missing filename
- Storage failure

---

### Step 2: Early XML Parsing Check
**Duration**: ~0.1-0.3s  
**Purpose**: Fast-fail for malformed XML before heavy processing

**Actions**:
- Read uploaded XML content
- Perform XML parsing validation with 5-second timeout
- Check if XML is well-formed

**Success Criteria**:
- XML can be parsed without errors
- No timeout during parsing

**Possible Errors**:
- XML syntax errors
- Parsing timeout (file too large or malformed)
- Failed to read file

---

### Step 3: XML Validation
**Duration**: ~0.5-2.0s  
**Purpose**: Validate XML content against UBL invoice schema

**Actions**:
- Extract customer information (ID and name)
- Determine customer format from database
- Validate XML structure and required fields
- Check for:
  - Sender/Receiver IDs
  - Valid dates
  - Valid amounts
  - Required elements

**Success Criteria**:
- XML passes structural validation
- All required fields present
- Data formats valid

**Possible Errors**:
- Missing sender/receiver IDs
- Invalid date formats
- Missing required elements
- Schema validation failures

**Intelligent Correction** (if validation fails):
1. Check correction cache for similar errors
2. If cached correction found, apply it
3. Otherwise, call AI (GPT-4o-mini) for correction
4. Save successful corrections to cache
5. Re-validate corrected XML

---

### Step 4: Format Conversion
**Duration**: ~1.0-3.0s  
**Purpose**: Convert XML to target EDI format (EDIFACT or X12)

**Format Decision Path**:
```
Customer Format → Processing Path
├── EDIFACT → XML → EDIFACT conversion
├── X12 → XML → X12 conversion
└── XML_EMBED → XML → EDIFACT → Embed in XML
```

**Actions**:
- Determine target format from customer configuration
- Call appropriate converter:
  - `convert_xml_to_edifact()` for EDIFACT
  - `convert_xml_to_x12()` for X12
- Save converted file
- Store content for embed workflow if needed

**Success Criteria**:
- Conversion completes without errors
- EDI file generated successfully

**Possible Errors**:
- Missing required data for conversion
- Party information incomplete
- Line item errors
- XML parsing errors during conversion

**Intelligent Correction** (if conversion fails):
1. Check correction cache for EDI errors
2. Apply cached correction if available
3. Otherwise, call AI for EDI correction
4. Save successful corrections to cache

**Skipped For**:
- XML passthrough formats (no conversion needed)

---

### Step 5: EDI Format Validation
**Duration**: ~0.3-1.0s  
**Purpose**: Validate EDI format fields, values, and lengths

**Actions**:
- Validate segment structure
- Check field formats and lengths
- Verify data consistency
- **Note**: Skipped for EDIFACT (different segment structure)

**Success Criteria**:
- All segments valid
- Field lengths correct
- Data formats conform to standard

**Possible Errors**:
- Invalid segment structure
- Field length violations
- Invalid field values

**Intelligent Correction** (if validation fails):
1. Check cache for format corrections
2. Apply rule-based corrections if available

**Skipped For**:
- EDIFACT conversions (uses different validation)
- XML passthrough formats

---

### Step 4A: EDINation X12 Validation (Optional)
**Duration**: ~0.5-2.0s  
**Purpose**: Third-party validation using EDINation API

**Actions**:
- Send X12 content to EDINation API
- Get detailed validation results
- Log warnings/errors

**Success Criteria**:
- EDINation API returns success
- No critical validation errors

**Applied To**:
- X12 format conversions only

**Skipped For**:
- EDIFACT conversions
- XML passthrough formats

---

### Step 4B: XML Embed Workflow (Optional)
**Duration**: ~0.2-0.5s  
**Purpose**: Embed converted EDI content into XML

**Actions**:
- Read converted EDI/EDIFACT content
- Embed into XML structure
- Save modified XML file

**Success Criteria**:
- EDI content successfully embedded
- Modified XML valid

**Applied To**:
- Customers with XML_EMBED format

**Skipped For**:
- Standard EDIFACT/X12 customers

---

### Step 6: Third Party Endpoint
**Duration**: ~1.0-5.0s  
**Purpose**: Send processed invoice to external API

**Actions**:
- Read final XML content
- Send to third-party API endpoint
- Receive and log response
- Parse success/failure status

**Success Criteria**:
- API returns success response
- Invoice accepted by external system

**Possible Errors**:
- Authentication failures (401/403)
- Validation errors from API
- Timeout
- Connection failures
- Customization value issues

**Applied To**:
- Customers requiring third-party integration
- XML_EMBED format customers

**Skipped For**:
- Standard EDIFACT/X12 customers without API integration

---

### Step 7: Database Save
**Duration**: ~0.1-0.3s  
**Purpose**: Persist invoice record and processing results

**Actions**:
- Determine overall workflow success/failure
- Convert processing steps to JSON
- Save to appropriate table:
  - `zodiac_invoice_success_edi` if successful
  - `zodiac_invoice_failed_edi` if failed
- Mark status tracker as completed

**Data Stored**:
- Tracking ID
- User ID
- File paths (local and blob URLs)
- Validation results
- Conversion results
- Processing steps with timestamps
- Error details (if any)
- External API status
- Target format

**Success Criteria**:
- Database record created
- Status tracker updated

---

## Processing Path Examples

### Example 1: EDIFACT Customer
```
Step 1: File Upload ✓
Step 2: Early XML Check ✓
Step 3: XML Validation ✓
Step 4: XML → EDIFACT Conversion ✓
Step 5: EDI Format Validation (SKIPPED for EDIFACT)
Step 6: Third Party Endpoint (SKIPPED)
Step 7: Database Save ✓
```

### Example 2: X12 Customer with EDINation
```
Step 1: File Upload ✓
Step 2: Early XML Check ✓
Step 3: XML Validation ✓
Step 4: XML → X12 Conversion ✓
Step 5: EDI Format Validation ✓
Step 4A: EDINation Validation ✓
Step 6: Third Party Endpoint (SKIPPED)
Step 7: Database Save ✓
```

### Example 3: XML Embed Customer
```
Step 1: File Upload ✓
Step 2: Early XML Check ✓
Step 3: XML Validation (SKIPPED)
Step 4: Format Conversion (SKIPPED)
Step 5: EDI Format Validation (SKIPPED)
Step 4B: XML Embed Workflow ✓
Step 6: Third Party Endpoint ✓
Step 7: Database Save ✓
```

---

## Intelligent Correction System

### Correction Cache
**Purpose**: Store and reuse successful corrections to avoid repeated AI calls

**Features**:
- **Customer-specific**: Corrections are associated with customer IDs
- **Error-specific**: Each error type has its own correction rules
- **Success tracking**: Monitors success/failure rates
- **Auto-disable**: Corrections with <30% success rate are disabled

**Correction Types**:
- **XML corrections**: Missing elements, invalid values, structural issues
- **EDI corrections**: Conversion errors, format issues
- **Rule-based**: Simple transformations (add element, pad field)
- **AI-full**: Complex corrections requiring AI re-application

### AI Integration
**Model**: GPT-4o-mini

**XML Correction**:
- Analyzes validation errors
- Suggests and applies fixes
- Re-validates corrected XML
- Caches successful corrections

**EDI Correction**:
- Reviews conversion errors
- Proposes EDI format fixes
- Validates corrected EDI
- Caches successful corrections

---

## Request Types

### Web Request
- **Authentication**: JWT token
- **Source**: Frontend web application
- **Processing**: Background task with real-time status updates
- **Response**: Immediate (202 Accepted) with tracking ID

### API Request
- **Authentication**: API key
- **Source**: External API clients
- **Processing**: Synchronous
- **Response**: Full processing result

---

## Status Tracking

### In-Memory Tracker
**Purpose**: Real-time status updates during processing

**Limitations**:
- ⚠️ **Serverless environments**: In-memory cache not shared between containers
- Works best in traditional server deployments

**Features**:
- Step-by-step updates
- Real-time progress tracking
- Completion marking
- Auto-cleanup after 24 hours

### Database Persistence
**Purpose**: Permanent record of processing results

**Storage**:
- Success table: `zodiac_invoice_success_edi`
- Failed table: `zodiac_invoice_failed_edi`

**Includes**:
- All processing steps
- Detailed error information
- File paths and blob URLs
- Timestamps and durations

---

## Error Handling

### Error Categories

1. **File Upload Errors**
   - Invalid content type
   - Missing filename
   - Storage failures

2. **XML Validation Errors**
   - Missing sender/receiver IDs
   - Invalid dates/amounts
   - Missing required elements
   - Schema validation failures

3. **XML Parsing Errors**
   - Malformed XML
   - Syntax errors
   - Parsing timeouts

4. **EDI Conversion Errors**
   - Missing data
   - Party information incomplete
   - Line item errors

5. **EDI Format Errors**
   - Invalid segment structure
   - Field length violations
   - Invalid field values

6. **Third Party API Errors**
   - Authentication failures
   - Validation rejections
   - Timeout
   - Connection failures

7. **Database Errors**
   - Save failures
   - Connection issues

### Error Recovery

**Automatic Recovery**:
1. Check correction cache
2. Apply cached correction if available
3. Otherwise, call AI for intelligent correction
4. Re-validate after correction
5. Cache successful corrections

**Non-recoverable Errors**:
- Saved to failed table
- Detailed error information provided
- User can edit and reprocess

---

## File Storage

### Local Storage (Development)
- **Path**: `uploads/` directory
- **Format**: `{tracking_id}_{original_filename}`

### Vercel Blob Storage (Production)
- **Service**: Vercel Blob Storage
- **URLs**: Permanent blob URLs
- **Structure**:
  ```json
  {
    "url": "https://blob.vercel-storage.com/...",
    "pathname": "uploads/filename.xml",
    "contentType": "text/xml"
  }
  ```

---

## Performance Metrics

### Typical Processing Times

| Step | Duration | Notes |
|------|----------|-------|
| File Upload | 0.1-0.5s | Depends on file size |
| Early XML Check | 0.1-0.3s | Fast fail for bad XML |
| XML Validation | 0.5-2.0s | Schema validation |
| Format Conversion | 1.0-3.0s | EDIFACT or X12 |
| EDI Validation | 0.3-1.0s | Format checking |
| EDINation | 0.5-2.0s | External API call |
| Third Party API | 1.0-5.0s | Network dependent |
| Database Save | 0.1-0.3s | Record persistence |

**Total**: ~3-15 seconds (varies by format and corrections needed)

### With AI Correction
- **Cache hit**: +0.1-0.5s (rule application)
- **AI call**: +2-5s (OpenAI API)

---

## Configuration

### Customer-Specific Settings
Stored in `zodiac_customers` table:
- `customer_id`: Unique customer identifier
- `format`: Target format (EDIFACT, X12, XML_EMBED, etc.)
- `api_address`: Third-party API endpoint (optional)
- `validation_rules`: Custom validation rules (optional)

### Processing Path Configuration
Determined by `format_router.get_processing_path()`:
- XML validation requirements
- Conversion needs and target format
- EDINation validation (X12 only)
- Embed workflow requirements
- Third-party API integration

---

## Logging

### Log Levels
- **INFO**: Normal processing flow
- **WARNING**: Non-critical issues, continuing processing
- **ERROR**: Critical failures, processing stopped

### Key Log Markers
- 🚀 Processing started
- ✅ Step completed successfully
- ❌ Step failed
- ⚠️ Warning/non-critical issue
- 🧠 AI correction attempted
- 💾 Database operation
- 🔍 Validation/checking
- 📊 Status/metrics
- 🎉 Processing completed

---

## Best Practices

### For API Clients
1. **Always use tracking ID**: Store it for status queries
2. **Poll for status**: Check `/status/{tracking_id}` regularly
3. **Handle all error types**: Different errors require different actions
4. **Use correct content type**: `text/xml` or `application/xml`

### For Web UI
1. **Show real-time progress**: Use status polling (500ms interval)
2. **Display detailed errors**: Help users understand issues
3. **Allow reprocessing**: Failed invoices can be edited and resubmitted
4. **Handle 202 responses**: Processing is asynchronous

### For System Administrators
1. **Monitor correction cache**: High cache hit rate = good
2. **Review AI usage**: Track costs and effectiveness
3. **Check third-party API**: Monitor success rates
4. **Database cleanup**: Archive old records periodically

---

## Future Enhancements

### Recommended Improvements
1. **Redis for status tracking**: Share state across containers
2. **WebSocket support**: Real-time push updates
3. **Batch processing**: Handle multiple files efficiently
4. **Advanced caching**: Redis-based correction cache
5. **Rate limiting**: API protection and quotas
6. **Audit logging**: Compliance and debugging

---

## Support

### Troubleshooting
- Check processing steps for failure point
- Review error details for specific issues
- Check blob storage URLs accessibility
- Verify database connectivity
- Monitor AI API quotas

### Common Issues
1. **Status not found**: Serverless container issue, keep polling
2. **Timeout errors**: Large files or slow AI responses
3. **Third party failures**: Check customer API configuration
4. **Conversion errors**: Verify customer format settings

---

**Last Updated**: December 2024  
**Version**: 1.0  
**System**: Zodiac Invoice Management Platform

