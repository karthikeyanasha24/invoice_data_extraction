from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid

class ErrorDetail(BaseModel):
    """Detailed error information for specific validation steps"""
    step: str  # e.g., "XML_VALIDATION", "EDI_CONVERSION", "EDI_FORMAT_VALIDATION"
    error_type: str  # e.g., "VALIDATION_ERROR", "FORMAT_ERROR", "DATA_TYPE_ERROR"
    field_name: Optional[str] = None  # Specific field that failed
    error_message: str
    expected_format: Optional[str] = None
    actual_value: Optional[str] = None
    suggestions: Optional[List[str]] = None

class ProcessingStepResult(BaseModel):
    """Result of a specific processing step"""
    step_name: str
    step_number: int
    success: bool
    duration_seconds: Optional[float] = None
    error_details: Optional[List[ErrorDetail]] = None
    message: Optional[str] = None

class InvoiceProcessingResponse(BaseModel):
    invoice_operation_success: bool
    file_upload_pass: bool
    file_upload_message: Optional[str] = None
    xml_validation_pass: bool
    xml_convert_message: Optional[str] = None
    edi_convert_pass: bool
    edi_convert_message: Optional[str] = None
    tracking_id: Optional[uuid.UUID] = None
    
    # Enhanced error information
    processing_steps: Optional[List[ProcessingStepResult]] = None
    error_summary: Optional[Dict[str, Any]] = None
    file_content_preview: Optional[str] = None  # First 500 chars of XML file
    suggested_actions: Optional[List[str]] = None
    warnings: Optional[List[str]] = None  # Non-blocking validation warnings

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
    processing_steps_error: Optional[List[ErrorDetail]] = None
    
    class Config:
        from_attributes = True