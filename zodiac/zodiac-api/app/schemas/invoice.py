from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

class DetailedErrorInfo(BaseModel):
    """Comprehensive error information with all context and remediation guidance"""
    error_code: str  # e.g., "E2003", "E4010"
    error_category: str  # e.g., "XML_VALIDATION", "EDI_FORMAT_VALIDATION"
    error_message: str  # Technical error message
    severity: str  # "CRITICAL", "ERROR", "WARNING"
    user_message: str  # User-friendly message
    technical_details: str  # Detailed technical explanation
    suggested_actions: Optional[List[str]] = None
    file_name: Optional[str] = None
    timestamp: Optional[float] = None
    additional_context: Optional[Dict[str, Any]] = None
    documentation_links: Optional[List[str]] = None
    is_recoverable: Optional[bool] = None
    estimated_fix_time: Optional[str] = None

class StepStatus(BaseModel):
    """Status information specific to each processing step"""
    # File Upload Step
    file_upload_pass: Optional[bool] = None
    file_upload_message: Optional[str] = None
    # XML Validation Step
    xml_validation_pass: Optional[bool] = None
    xml_convert_message: Optional[str] = None
    # EDI Conversion Step
    edi_convert_pass: Optional[bool] = None
    edi_convert_message: Optional[str] = None

class ProcessingStepResult(BaseModel):
    """Result of a specific processing step with complete error details"""
    step_name: str
    step_number: int
    success: bool
    duration_seconds: Optional[float] = None
    message: Optional[str] = None
    status: Optional[StepStatus] = None  # Step-specific status fields
    error_details: Optional[List[DetailedErrorInfo]] = None  # Complete error information

class InvoiceProcessingResponse(BaseModel):
    """Simplified response structure with only tracking_id and processing_steps"""
    tracking_id: Optional[uuid.UUID] = None
    processing_steps: Optional[List[ProcessingStepResult]] = None

class InvoiceResponse(BaseModel):
    """Response format that matches frontend Invoice interface"""
    id: int
    filename: str
    customerId: Optional[str] = None
    customerName: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    status: str
    accepted: int = 0
    rejected: int = 0
    aktId: Optional[str] = None
    formate: str = "XML"  # Keep as 'formate' to match frontend
    destinationCountry: Optional[str] = None
    export: bool = True
    country: Optional[str] = None
    # Error details for failed invoices
    xml_validation_pass: Optional[bool] = None
    xml_convert_message: Optional[str] = None
    edi_convert_pass: Optional[bool] = None
    edi_convert_message: Optional[str] = None
    tracking_id: Optional[str] = None
    uploaded_at: Optional[str] = None
    deleted_at: Optional[str] = None

class ZodiacInvoiceSuccessEdi(BaseModel):
    id: int
    tracking_id: uuid.UUID
    user_id: int
    uploaded_at: datetime
    xml_path: Optional[str] = None
    xml_validation_pass: bool
    xml_convert_message: Optional[str] = None
    edi_path: Optional[str] = None
    edi_convert_pass: bool
    edi_convert_message: Optional[str] = None
    blob_xml_path: Optional[str] = None
    blob_edi_path: Optional[str] = None
    xml_content: Optional[str] = None
    edi_content: Optional[str] = None
    invoice_id: Optional[str] = None
    customer_name: Optional[str] = None
    
    class Config:
        from_attributes = True

class ZodiacInvoiceFailedEdi(BaseModel):
    id: int
    tracking_id: uuid.UUID
    user_id: int
    uploaded_at: datetime
    xml_path: Optional[str] = None
    xml_validation_pass: bool
    xml_convert_message: Optional[str] = None
    edi_path: Optional[str] = None
    edi_convert_pass: bool
    edi_convert_message: Optional[str] = None
    blob_xml_path: Optional[str] = None
    blob_edi_path: Optional[str] = None
    xml_content: Optional[str] = None
    edi_content: Optional[str] = None
    processing_steps: Optional[List[Dict[str, Any]]] = None
    
    class Config:
        from_attributes = True