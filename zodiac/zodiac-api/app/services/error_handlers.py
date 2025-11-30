class ErrorContext:
    """Container for detailed error context information."""
    
    def __init__(
        self,
        error_code: str,
        error_category: str,
        error_message: str,
        severity: str,
        step_name: str,
        step_number: int,
        tracking_id: str = None,
        user_id: int = None,
        file_name: str = None,
        timestamp: float = None,
        stack_trace: str = None,
        additional_context: dict = None
    ):
        self.error_code = error_code
        self.error_category = error_category
        self.error_message = error_message
        self.severity = severity  # CRITICAL, ERROR, WARNING, INFO
        self.step_name = step_name
        self.step_number = step_number
        self.tracking_id = tracking_id
        self.user_id = user_id
        self.file_name = file_name
        self.timestamp = timestamp
        self.stack_trace = stack_trace
        self.additional_context = additional_context or {}
    
    def to_dict(self):
        """Convert error context to dictionary."""
        return {
            "error_code": self.error_code,
            "error_category": self.error_category,
            "error_message": self.error_message,
            "severity": self.severity,
            "step_name": self.step_name,
            "step_number": self.step_number,
            "tracking_id": self.tracking_id,
            "user_id": self.user_id,
            "file_name": self.file_name,
            "timestamp": self.timestamp,
            "stack_trace": self.stack_trace,
            "additional_context": self.additional_context
        }


class ErrorFeedback:
    """Container for actionable error feedback and remediation guidance."""
    
    def __init__(
        self,
        error_context: ErrorContext,
        user_message: str,
        technical_details: str,
        suggested_actions: list,
        documentation_links: list = None,
        related_errors: list = None,
        is_recoverable: bool = True,
        estimated_fix_time: str = None
    ):
        self.error_context = error_context
        self.user_message = user_message
        self.technical_details = technical_details
        self.suggested_actions = suggested_actions
        self.documentation_links = documentation_links or []
        self.related_errors = related_errors or []
        self.is_recoverable = is_recoverable
        self.estimated_fix_time = estimated_fix_time
    
    def to_dict(self):
        """Convert error feedback to dictionary."""
        return {
            "error_context": self.error_context.to_dict(),
            "user_message": self.user_message,
            "technical_details": self.technical_details,
            "suggested_actions": self.suggested_actions,
            "documentation_links": self.documentation_links,
            "related_errors": self.related_errors,
            "is_recoverable": self.is_recoverable,
            "estimated_fix_time": self.estimated_fix_time
        }


class ErrorTracker:
    """Main error tracking and feedback generation system."""
    
    # Error code definitions
    ERROR_CODES = {
        # File Upload Errors (E1xxx)
        "E1001": "Invalid file type",
        "E1002": "Missing filename",
        "E1003": "File too large",
        "E1004": "Empty file",
        "E1005": "File upload failed",
        "E1006": "Storage system unavailable",
        
        # XML Validation Errors (E2xxx)
        "E2001": "XML malformed",
        "E2002": "XML parsing error",
        "E2003": "Missing sender ID",
        "E2004": "Missing receiver ID",
        "E2005": "Missing required element",
        "E2006": "Invalid XML structure",
        "E2007": "Namespace error",
        "E2008": "Invalid date format",
        "E2009": "Invalid amount format",
        "E2010": "Strict validation failed",
        
        # EDI Conversion Errors (E3xxx)
        "E3001": "EDI conversion failed",
        "E3002": "Missing invoice data",
        "E3003": "Invalid data format",
        "E3004": "Party information incomplete",
        "E3005": "Line item conversion error",
        "E3006": "Amount calculation error",
        
        # EDI Format Validation Errors (E4xxx)
        "E4001": "ISA segment invalid",
        "E4002": "GS segment invalid",
        "E4003": "ST segment invalid",
        "E4004": "BIG segment invalid",
        "E4005": "N1 segment invalid",
        "E4006": "IT1 segment invalid",
        "E4007": "TDS segment invalid",
        "E4008": "Trailer segment missing",
        "E4009": "Field length mismatch",
        "E4010": "Invalid segment order",
        
        # Third Party API Errors (E5xxx)
        "E5001": "Third party authentication failed",
        "E5002": "Third party API unavailable",
        "E5003": "Third party timeout",
        "E5004": "Third party rejected file",
        "E5005": "Invalid API response",
        
        # Database Errors (E6xxx)
        "E6001": "Database connection failed",
        "E6002": "Database save failed",
        "E6003": "Database query error",
        "E6004": "Transaction rollback",
        
        # AI Correction Errors (E7xxx)
        "E7001": "AI service unavailable",
        "E7002": "AI correction failed",
        "E7003": "AI timeout",
        "E7004": "AI invalid response",
        
        # System Errors (E9xxx)
        "E9001": "Unexpected system error",
        "E9002": "Configuration error",
        "E9003": "Resource unavailable",
        "E9004": "Timeout error"
    }
    
    @staticmethod
    def create_file_upload_error(
        error_type: str,
        file_name: str = None,
        file_size: int = None,
        content_type: str = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for file upload errors."""
        
        error_mappings = {
            "invalid_type": {
                "code": "E1001",
                "message": f"Invalid file type '{content_type}'. Only XML files are accepted.",
                "details": f"The uploaded file has content type '{content_type}', but only 'text/xml' or 'application/xml' are supported.",
                "actions": [
                    "Ensure the file is a valid XML document",
                    "Check that the file extension is .xml",
                    "Verify the file was not corrupted during upload",
                    "If using an API, set Content-Type header to 'text/xml' or 'application/xml'"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "Immediate - upload correct file type"
            },
            "missing_filename": {
                "code": "E1002",
                "message": "No filename was provided with the upload.",
                "details": "The file upload request did not include a filename parameter.",
                "actions": [
                    "Ensure the file input includes a filename",
                    "Check the form data or multipart upload configuration",
                    "Verify the upload request structure",
                    "If using an API, include the filename in the request"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "Immediate - resubmit with filename"
            },
            "file_too_large": {
                "code": "E1003",
                "message": f"File size ({file_size} bytes) exceeds maximum allowed limit.",
                "details": f"The uploaded file is {file_size} bytes, which is larger than the system limit.",
                "actions": [
                    "Reduce the file size by removing unnecessary data",
                    "Split large invoices into multiple files",
                    "Compress XML content (remove whitespace)",
                    "Contact support for increased file size limits"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "5-15 minutes - file optimization required"
            },
            "empty_file": {
                "code": "E1004",
                "message": "The uploaded file is empty (0 bytes).",
                "details": "The file contains no content.",
                "actions": [
                    "Verify the file was saved correctly before upload",
                    "Check that the file generation process completed",
                    "Ensure the file wasn't corrupted during transfer",
                    "Try re-exporting the invoice data"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "Immediate - upload valid file"
            },
            "storage_failed": {
                "code": "E1005",
                "message": "Failed to save the uploaded file to storage.",
                "details": "The system could not persist the file to the storage backend.",
                "actions": [
                    "Retry the upload",
                    "Check system status page for storage issues",
                    "Contact support if problem persists",
                    "Verify network connectivity"
                ],
                "severity": "CRITICAL",
                "recoverable": True,
                "fix_time": "1-5 minutes - retry or contact support"
            }
        }
        
        mapping = error_mappings.get(error_type, error_mappings["storage_failed"])
        
        context = ErrorContext(
            error_code=mapping["code"],
            error_category="FILE_UPLOAD",
            error_message=mapping["message"],
            severity=mapping["severity"],
            step_name="File Upload",
            step_number=1,
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "file_size": file_size,
                "content_type": content_type
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=mapping["message"],
            technical_details=mapping["details"],
            suggested_actions=mapping["actions"],
            is_recoverable=mapping["recoverable"],
            estimated_fix_time=mapping["fix_time"]
        )
    
    @staticmethod
    def create_xml_validation_error(
        error_type: str,
        error_message: str,
        file_name: str = None,
        xml_preview: str = None,
        line_number: int = None,
        column_number: int = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for XML validation errors."""
        
        error_mappings = {
            "malformed": {
                "code": "E2001",
                "category": "XML_PARSING",
                "user_message": "The XML file is malformed and cannot be parsed.",
                "details": f"XML parsing failed: {error_message}",
                "actions": [
                    "Check for unclosed XML tags",
                    "Verify proper XML structure (opening and closing tags match)",
                    "Ensure special characters are properly escaped (&, <, >, \", ')",
                    "Validate XML using an online XML validator",
                    "Check for invalid characters in XML content"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "5-30 minutes - XML structure fixes required"
            },
            "missing_sender_id": {
                "code": "E2003",
                "category": "XML_VALIDATION",
                "user_message": "Sender ID (Supplier) is missing or empty in the XML.",
                "details": "The XML must contain a valid Supplier EndpointID or CompanyID in AccountingSupplierParty.",
                "actions": [
                    "Add <cbc:EndpointID> element in AccountingSupplierParty/cac:Party",
                    "Or add <cbc:CompanyID> in AccountingSupplierParty/cac:Party/cac:PartyLegalEntity",
                    "Ensure the ID value is not empty or whitespace",
                    "Verify the supplier identification in your invoice system",
                    "Check UBL 2.1 specification for proper party identification"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "10-20 minutes - add required identification"
            },
            "missing_receiver_id": {
                "code": "E2004",
                "category": "XML_VALIDATION",
                "user_message": "Receiver ID (Customer) is missing or empty in the XML.",
                "details": "The XML must contain a valid Customer EndpointID or CompanyID in AccountingCustomerParty.",
                "actions": [
                    "Add <cbc:EndpointID> element in AccountingCustomerParty/cac:Party",
                    "Or add <cbc:CompanyID> in AccountingCustomerParty/cac:Party/cac:PartyLegalEntity",
                    "Ensure the ID value is not empty or whitespace",
                    "Verify the customer identification in your invoice system",
                    "Check UBL 2.1 specification for proper party identification"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "10-20 minutes - add required identification"
            },
            "missing_element": {
                "code": "E2005",
                "category": "XML_VALIDATION",
                "user_message": f"Required XML element is missing: {error_message}",
                "details": f"The UBL invoice is missing a required element: {error_message}",
                "actions": [
                    "Review UBL 2.1 invoice specification",
                    "Add the missing required element",
                    "Check your invoice generation logic",
                    "Validate against UBL XSD schema",
                    "Use AI assistant for automatic correction"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "15-45 minutes - add missing elements"
            },
            "invalid_date": {
                "code": "E2008",
                "category": "XML_VALIDATION",
                "user_message": "Date format is invalid in the XML.",
                "details": f"Date validation failed: {error_message}. Expected format: YYYY-MM-DD",
                "actions": [
                    "Ensure dates are in YYYY-MM-DD format (e.g., 2024-03-15)",
                    "Check IssueDate, DueDate, and other date fields",
                    "Verify date values are valid (no 2024-13-45)",
                    "Ensure timezone information is correctly formatted if present",
                    "Review UBL date field requirements"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "5-15 minutes - correct date formats"
            },
            "invalid_amount": {
                "code": "E2009",
                "category": "XML_VALIDATION",
                "user_message": "Amount format is invalid in the XML.",
                "details": f"Amount validation failed: {error_message}. Expected format: decimal number",
                "actions": [
                    "Ensure amounts are numeric decimal values",
                    "Check PayableAmount, TaxAmount, LineExtensionAmount fields",
                    "Remove currency symbols from amount fields",
                    "Use correct decimal separator (period, not comma)",
                    "Verify amount calculations are correct"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "5-15 minutes - correct amount formats"
            },
            "strict_validation": {
                "code": "E2010",
                "category": "XML_VALIDATION",
                "user_message": "Strict validation failed - data quality issues detected.",
                "details": f"Strict validation errors: {error_message}",
                "actions": [
                    "Review all validation warnings",
                    "Ensure all data fields contain valid, non-empty values",
                    "Check field length constraints",
                    "Verify data types match UBL specification",
                    "Use AI assistant for detailed correction guidance"
                ],
                "severity": "WARNING",
                "recoverable": True,
                "fix_time": "20-60 minutes - comprehensive data review"
            }
        }
        
        mapping = error_mappings.get(error_type, error_mappings["missing_element"])
        
        context = ErrorContext(
            error_code=mapping["code"],
            error_category=mapping["category"],
            error_message=mapping["user_message"],
            severity=mapping["severity"],
            step_name="XML Validation",
            step_number=2,
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "xml_preview": xml_preview[:500] if xml_preview else None,
                "line_number": line_number,
                "column_number": column_number,
                "original_error": error_message
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=mapping["user_message"],
            technical_details=mapping["details"],
            suggested_actions=mapping["actions"],
            documentation_links=[
                "https://docs.oasis-open.org/ubl/UBL-2.1.html",
                "https://www.w3.org/TR/xml/"
            ],
            is_recoverable=mapping["recoverable"],
            estimated_fix_time=mapping["fix_time"]
        )
    
    @staticmethod
    def create_edi_conversion_error(
        error_type: str,
        error_message: str,
        file_name: str = None,
        missing_fields: list = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for EDI conversion errors."""
        
        error_mappings = {
            "conversion_failed": {
                "code": "E3001",
                "user_message": "Failed to convert XML to EDI format.",
                "details": f"EDI conversion error: {error_message}",
                "actions": [
                    "Verify XML contains all required invoice data",
                    "Check party information is complete (supplier and customer)",
                    "Ensure invoice lines contain valid quantities and prices",
                    "Verify totals and amounts are present",
                    "Review XML structure matches UBL invoice specification",
                    "Try AI-assisted correction"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "15-45 minutes - data completeness review"
            },
            "missing_data": {
                "code": "E3002",
                "user_message": f"Required invoice data is missing: {', '.join(missing_fields) if missing_fields else 'unknown'}",
                "details": f"The following required fields are missing for EDI conversion: {missing_fields}",
                "actions": [
                    "Add missing invoice fields to XML",
                    "Check invoice ID, date, and amounts",
                    "Verify supplier and customer information",
                    "Ensure at least one invoice line is present",
                    "Review EDI 810 requirements"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "20-45 minutes - add missing data"
            },
            "party_incomplete": {
                "code": "E3004",
                "user_message": "Supplier or customer information is incomplete.",
                "details": "EDI conversion requires complete party information including name, ID, and address.",
                "actions": [
                    "Add complete supplier party information",
                    "Add complete customer party information",
                    "Include party names, IDs, and addresses",
                    "Verify EndpointID or CompanyID is present",
                    "Check postal address elements"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "15-30 minutes - complete party data"
            },
            "line_item_error": {
                "code": "E3005",
                "user_message": "Invoice line item conversion failed.",
                "details": f"Error converting invoice lines: {error_message}",
                "actions": [
                    "Ensure all invoice lines have valid IDs",
                    "Check quantities are numeric and non-zero",
                    "Verify prices are present and numeric",
                    "Ensure item descriptions are not empty",
                    "Review line item totals"
                ],
                "severity": "ERROR",
                "recoverable": True,
                "fix_time": "10-30 minutes - fix line item data"
            }
        }
        
        mapping = error_mappings.get(error_type, error_mappings["conversion_failed"])
        
        context = ErrorContext(
            error_code=mapping["code"],
            error_category="EDI_CONVERSION",
            error_message=mapping["user_message"],
            severity=mapping["severity"],
            step_name="EDI Conversion",
            step_number=3,
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "missing_fields": missing_fields,
                "original_error": error_message
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=mapping["user_message"],
            technical_details=mapping["details"],
            suggested_actions=mapping["actions"],
            documentation_links=[
                "https://x12.org/products/edi-standards/edi-standards-810",
                "https://www.stedi.com/edi/x12-810"
            ],
            is_recoverable=mapping["recoverable"],
            estimated_fix_time=mapping["fix_time"]
        )
    
    @staticmethod
    def create_edi_validation_error(
        segment_name: str,
        field_errors: list,
        edi_preview: str = None,
        file_name: str = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for EDI format validation errors."""
        
        segment_guidance = {
            "ISA": {
                "code": "E4001",
                "description": "Interchange Control Header segment",
                "requirements": [
                    "ISA06 (Sender ID): Must be exactly 15 characters",
                    "ISA08 (Receiver ID): Must be exactly 15 characters",
                    "ISA09 (Date): Must be YYMMDD format",
                    "ISA10 (Time): Must be HHMM format",
                    "Must have exactly 16 fields"
                ],
                "fix_actions": [
                    "Pad sender and receiver IDs to 15 characters (right-pad with spaces)",
                    "Format date as YYMMDD (e.g., 240315 for March 15, 2024)",
                    "Format time as HHMM (e.g., 1430 for 2:30 PM)",
                    "Verify all 16 ISA fields are present",
                    "Use AI assistant for automatic correction"
                ]
            },
            "GS": {
                "code": "E4002",
                "description": "Functional Group Header segment",
                "requirements": [
                    "GS01: Functional Identifier must be 'IN' for Invoice",
                    "GS02: Application Sender Code must be 2 characters",
                    "GS03: Application Receiver Code must be 2 characters",
                    "Must have at least 8 fields"
                ],
                "fix_actions": [
                    "Set GS01 to 'IN' for invoice transactions",
                    "Use first 2 characters of sender ID for GS02",
                    "Use first 2 characters of receiver ID for GS03",
                    "Ensure date/time formats are correct",
                    "Verify group control number is present"
                ]
            },
            "N1": {
                "code": "E4005",
                "description": "Name/Party identification segment",
                "requirements": [
                    "Must have at least 2 N1 segments (Buyer and Seller)",
                    "N1*BY for Buyer (customer)",
                    "N1*SE for Seller (supplier)",
                    "Each must include party name and ID"
                ],
                "fix_actions": [
                    "Add N1*SE segment for supplier/seller",
                    "Add N1*BY segment for buyer/customer",
                    "Do not use N1*SU (should be SE)",
                    "Include complete party information",
                    "Ensure IDs match ISA segment IDs"
                ]
            },
            "BIG": {
                "code": "E4004",
                "description": "Beginning Segment for Invoice",
                "requirements": [
                    "BIG01: Invoice date in YYYYMMDD format",
                    "BIG02: Invoice number (cannot be empty)",
                    "Must have at least 3 fields"
                ],
                "fix_actions": [
                    "Format date as YYYYMMDD (e.g., 20240315)",
                    "Ensure invoice number is not empty",
                    "Verify date is valid (month 01-12, day 01-31)",
                    "Include purchase order number if available"
                ]
            },
            "IT1": {
                "code": "E4006",
                "description": "Baseline Item Data segment",
                "requirements": [
                    "IT102: Quantity must be numeric and > 0",
                    "IT104: Unit price must be present",
                    "Must have at least 6 fields"
                ],
                "fix_actions": [
                    "Ensure quantity is numeric and greater than zero",
                    "Format price correctly (use cents, not decimal)",
                    "Include unit of measure (e.g., EA for each)",
                    "Add product/item codes",
                    "Verify line item calculations"
                ]
            },
            "TDS": {
                "code": "E4007",
                "description": "Total Monetary Value Summary segment",
                "requirements": [
                    "TDS01: Total invoice amount must be > 0",
                    "Amount must be numeric",
                    "Must match sum of line items"
                ],
                "fix_actions": [
                    "Calculate correct invoice total",
                    "Format amount in cents (multiply by 100)",
                    "Ensure amount matches line item sum",
                    "Verify amount is numeric"
                ]
            }
        }
        
        guidance = segment_guidance.get(segment_name, {
            "code": "E4010",
            "description": f"{segment_name} segment",
            "requirements": ["See X12 810 specification"],
            "fix_actions": ["Review segment structure", "Check field values"]
        })
        
        context = ErrorContext(
            error_code=guidance["code"],
            error_category="EDI_FORMAT_VALIDATION",
            error_message=f"EDI {segment_name} segment validation failed: {len(field_errors)} errors",
            severity="ERROR",
            step_name="EDI Format Validation",
            step_number=4,
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "segment_name": segment_name,
                "field_errors": field_errors,
                "edi_preview": edi_preview[:500] if edi_preview else None
            }
        )
        
        error_details = "\n".join([f"• {error}" for error in field_errors])
        
        return ErrorFeedback(
            error_context=context,
            user_message=f"EDI {segment_name} segment ({guidance['description']}) has validation errors.",
            technical_details=f"Segment: {segment_name}\nErrors:\n{error_details}\n\nRequirements:\n" + 
                            "\n".join([f"• {req}" for req in guidance["requirements"]]),
            suggested_actions=guidance["fix_actions"],
            documentation_links=[
                "https://x12.org/products/edi-standards/edi-standards-810",
                "https://www.stedi.com/edi/x12-810/segment/",
                f"https://www.stedi.com/edi/x12-810/segment/{segment_name.lower()}"
            ],
            is_recoverable=True,
            estimated_fix_time="10-30 minutes - segment corrections"
        )
    
    @staticmethod
    def create_third_party_error(
        error_type: str,
        error_message: str,
        api_endpoint: str = None,
        status_code: int = None,
        response_body: str = None,
        file_name: str = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for third-party API errors."""
        
        error_mappings = {
            "auth_failed": {
                "code": "E5001",
                "user_message": "Authentication with third-party service failed.",
                "details": f"Could not authenticate with external API: {error_message}",
                "actions": [
                    "Verify API credentials are correct",
                    "Check if API token has expired",
                    "Ensure network connectivity to external service",
                    "Contact external service support",
                    "Check system status page"
                ],
                "severity": "WARNING",
                "recoverable": True,
                "fix_time": "5-30 minutes - check credentials or retry"
            },
            "unavailable": {
                "code": "E5002",
                "user_message": "Third-party service is currently unavailable.",
                "details": f"External API returned error: Status {status_code}, {error_message}",
                "actions": [
                    "Wait a few minutes and retry",
                    "Check third-party service status page",
                    "Verify network connectivity",
                    "Contact third-party support if issue persists",
                    "Invoice is saved and can be resubmitted later"
                ],
                "severity": "WARNING",
                "recoverable": True,
                "fix_time": "5-60 minutes - wait for service recovery"
            },
            "timeout": {
                "code": "E5003",
                "user_message": "Request to third-party service timed out.",
                "details": "The external API did not respond within the timeout period.",
                "actions": [
                    "Retry the request",
                    "Check network connectivity",
                    "Verify third-party service is operational",
                    "Contact support if timeouts persist",
                    "Invoice is saved successfully despite timeout"
                ],
                "severity": "WARNING",
                "recoverable": True,
                "fix_time": "Immediate - retry operation"
            },
            "rejected": {
                "code": "E5004",
                "user_message": "Third-party service rejected the file.",
                "details": f"External validation failed: {error_message}",
                "actions": [],  # Will be populated based on error message
                "severity": "WARNING",
                "recoverable": True,
                "fix_time": "30-90 minutes - address validation issues"
            }
        }
        
        mapping = error_mappings.get(error_type, error_mappings["unavailable"])
        
        # Enhance error message and actions based on specific error content
        if "customization" in error_message.lower():
            mapping["user_message"] = "XML Customization ID is not recognized by the third-party service."
            mapping["details"] = error_message
            mapping["actions"] = [
                "Verify the CustomizationID in the XML matches what the third-party service expects",
                "Common valid values: 'urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0'",
                "Check the XML root element has the correct PEPPOL namespaces",
                "Ensure CustomizationID element is properly formatted in the XML",
                "Contact the third-party service to confirm accepted CustomizationID values",
                "Retry after fixing the XML CustomizationID"
            ]
        elif "profileid" in error_message.lower() or "profile" in error_message.lower():
            mapping["user_message"] = "XML Profile ID is not valid for the third-party service."
            mapping["details"] = error_message
            mapping["actions"] = [
                "Verify the ProfileID in the XML is correct",
                "Common valid value: 'urn:fdc:peppol.eu:2017:poacc:billing:01:1.0'",
                "Check that ProfileID matches your PEPPOL version",
                "Ensure the ProfileID and CustomizationID are compatible",
                "Consult PEPPOL documentation for valid ProfileID values",
                "Contact third-party support for their accepted values"
            ]
        elif "namespace" in error_message.lower():
            mapping["user_message"] = "XML namespaces are not valid."
            mapping["details"] = error_message
            mapping["actions"] = [
                "Verify all XML namespace declarations are present and correct",
                "Check namespaces match PEPPOL UBL 2.1 specifications",
                "Ensure no extra or missing namespace prefixes",
                "Validate XML structure against UBL schema",
                "Try regenerating the XML with correct namespace declarations",
                "Contact third-party service for namespace requirements"
            ]
        elif "element" in error_message.lower() or "missing" in error_message.lower():
            mapping["user_message"] = "Required XML elements are missing or invalid."
            mapping["details"] = error_message
            mapping["actions"] = [
                "Review the error message to identify which element is missing",
                "Check that all required PEPPOL invoice elements are present",
                "Verify party information (supplier and customer) is complete",
                "Ensure all invoice lines have required fields (quantity, price, description)",
                "Validate XML against the UBL 2.1 invoice schema",
                "Add any missing elements and retry"
            ]
        elif "validation" in error_message.lower() or "invalid" in error_message.lower():
            mapping["user_message"] = "XML failed third-party validation."
            mapping["details"] = error_message
            mapping["actions"] = [
                "Review the specific validation error from the message",
                "Check data types and formats (dates, amounts, codes)",
                "Verify currency codes and country codes are valid",
                "Ensure email and phone formats are correct",
                "Check that all codes follow required standards (ISO, UNCEFACT, etc.)",
                "Validate XML against PEPPOL rules and retry"
            ]
        else:
            mapping["actions"] = [
                "Review the error message for specific details",
                "Check the XML structure and content",
                "Verify all required information is present",
                "Contact third-party support with the error message",
                "Retry after addressing the identified issue"
            ]
        
        context = ErrorContext(
            error_code=mapping["code"],
            error_category="THIRD_PARTY_API",
            error_message=mapping["user_message"],
            severity=mapping["severity"],
            step_name="Third Party Endpoint",
            step_number=5,
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "api_endpoint": api_endpoint,
                "status_code": status_code,
                "response_body": response_body[:500] if response_body else None,
                "original_error": error_message
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=mapping["user_message"],
            technical_details=mapping["details"],
            suggested_actions=mapping["actions"],
            is_recoverable=mapping["recoverable"],
            estimated_fix_time=mapping["fix_time"]
        )
    
    @staticmethod
    def create_database_error(
        operation: str,
        error_message: str,
        table_name: str = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for database errors."""
        
        context = ErrorContext(
            error_code="E6002",
            error_category="DATABASE",
            error_message=f"Database {operation} operation failed",
            severity="CRITICAL",
            step_name="Database Save",
            step_number=6,
            tracking_id=tracking_id,
            user_id=user_id,
            timestamp=timestamp,
            additional_context={
                "operation": operation,
                "table_name": table_name,
                "original_error": error_message
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=f"Failed to save invoice data to database.",
            technical_details=f"Database operation '{operation}' failed on table '{table_name}': {error_message}",
            suggested_actions=[
                "Retry the operation",
                "Check database connectivity",
                "Verify database is not at capacity",
                "Contact system administrator",
                "Check application logs for details"
            ],
            is_recoverable=True,
            estimated_fix_time="5-30 minutes - system issue"
        )
    
    @staticmethod
    def create_ai_correction_error(
        correction_type: str,
        error_message: str,
        file_name: str = None,
        tracking_id: str = None,
        user_id: int = None,
        timestamp: float = None
    ) -> ErrorFeedback:
        """Create detailed feedback for AI correction errors."""
        
        error_mappings = {
            "unavailable": {
                "code": "E7001",
                "message": "AI correction service is currently unavailable.",
                "details": f"Could not connect to AI service: {error_message}",
                "actions": [
                    "Processing will continue without AI correction",
                    "Manual correction may be required",
                    "Retry the upload to attempt AI correction again",
                    "Contact support if AI service is consistently unavailable"
                ],
                "severity": "WARNING"
            },
            "failed": {
                "code": "E7002",
                "message": "AI correction attempt did not improve the file.",
                "details": f"AI correction failed: {error_message}",
                "actions": [
                    "Review the original validation errors",
                    "Perform manual corrections",
                    "Ensure file has sufficient valid data for AI to work with",
                    "Try simplifying the corrections needed"
                ],
                "severity": "WARNING"
            },
            "timeout": {
                "code": "E7003",
                "message": "AI correction timed out.",
                "details": "AI service did not respond within timeout period.",
                "actions": [
                    "Retry the upload",
                    "File may be too complex for AI correction",
                    "Consider manual corrections",
                    "Contact support if timeouts persist"
                ],
                "severity": "WARNING"
            }
        }
        
        mapping = error_mappings.get(correction_type, error_mappings["failed"])
        
        context = ErrorContext(
            error_code=mapping["code"],
            error_category="AI_CORRECTION",
            error_message=mapping["message"],
            severity=mapping["severity"],
            step_name="AI Auto-Correction",
            step_number=0,  # AI correction is auxiliary
            tracking_id=tracking_id,
            user_id=user_id,
            file_name=file_name,
            timestamp=timestamp,
            additional_context={
                "correction_type": correction_type,
                "original_error": error_message
            }
        )
        
        return ErrorFeedback(
            error_context=context,
            user_message=mapping["message"],
            technical_details=mapping["details"],
            suggested_actions=mapping["actions"],
            is_recoverable=True,
            estimated_fix_time="Variable - depends on manual corrections needed"
        )
    
    @staticmethod
    def generate_error_summary(error_feedbacks: list) -> dict:
        """Generate a comprehensive error summary from multiple errors."""
        
        if not error_feedbacks:
            return {
                "total_errors": 0,
                "severity_breakdown": {},
                "category_breakdown": {},
                "recoverable_count": 0,
                "critical_errors": [],
                "all_suggested_actions": []
            }
        
        severity_counts = {}
        category_counts = {}
        critical_errors = []
        all_actions = set()
        recoverable_count = 0
        
        for feedback in error_feedbacks:
            # Count severities
            severity = feedback.error_context.severity
            severity_counts[severity] = severity_counts.get(severity, 0) + 1
            
            # Count categories
            category = feedback.error_context.error_category
            category_counts[category] = category_counts.get(category, 0) + 1
            
            # Track critical errors
            if severity == "CRITICAL":
                critical_errors.append({
                    "code": feedback.error_context.error_code,
                    "message": feedback.user_message,
                    "step": feedback.error_context.step_name
                })
            
            # Collect unique actions
            all_actions.update(feedback.suggested_actions)
            
            # Count recoverable errors
            if feedback.is_recoverable:
                recoverable_count += 1
        
        return {
            "total_errors": len(error_feedbacks),
            "severity_breakdown": severity_counts,
            "category_breakdown": category_counts,
            "recoverable_count": recoverable_count,
            "critical_errors": critical_errors,
            "all_suggested_actions": list(all_actions),
            "all_recoverable": recoverable_count == len(error_feedbacks)
        }
