from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class ConvertedInvoiceBase(BaseModel):
    """Base schema for converted invoices"""
    validated_invoice_id: int = Field(..., description="ID of the validated invoice")
    customer_id: Optional[str] = Field(None, description="Customer ID for reference")
    target_format: str = Field(..., description="Target format (X12, EDIFACT, PDF, etc.)")
    conversion_status: str = Field(default="pending", description="Status: success, failed, pending")
    conversion_notes: Optional[str] = Field(None, description="Notes or warnings from conversion")
    validation_overridden: bool = Field(default=False, description="Whether validation mismatch was overridden")


class ConvertedInvoiceCreate(ConvertedInvoiceBase):
    """Schema for creating a converted invoice record"""
    converted_file_path: Optional[str] = None
    blob_converted_path: Optional[str] = None


class ConvertedInvoiceResponse(ConvertedInvoiceBase):
    """Schema for returning converted invoice data"""
    id: int = Field(..., description="Database ID")
    converted_file_path: Optional[str] = None
    blob_converted_path: Optional[str] = None
    converted_at: datetime = Field(..., description="When conversion occurred")

    class Config:
        from_attributes = True


class ConvertedInvoiceListResponse(BaseModel):
    """Schema for paginated list of converted invoices"""
    total: int = Field(..., description="Total number of converted invoices")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Number of records per page")
    converted_invoices: List[ConvertedInvoiceResponse] = Field(..., description="List of converted invoices")


class ConversionRequest(BaseModel):
    """Schema for requesting invoice conversion"""
    validated_invoice_ids: List[int] = Field(..., description="List of validated invoice IDs to convert")


class ConversionResult(BaseModel):
    """Schema for individual conversion result"""
    validated_invoice_id: int
    status: str  # success, failed, validation_mismatch
    converted_invoice_id: Optional[int] = None
    target_format: Optional[str] = None
    error_message: Optional[str] = None
    validation_mismatches: Optional[Dict[str, Dict[str, Any]]] = None  # {field_name: {expected: x, actual: y}}
    steps: Optional[List[str]] = None  # Detailed step-by-step messages


class ConversionBatchResult(BaseModel):
    """Schema for batch conversion result"""
    total_requested: int
    successful: int
    failed: int
    validation_mismatches: int
    results: List[ConversionResult]


class ValidationOverrideRequest(BaseModel):
    """Schema for overriding validation mismatch"""
    update_customer_fields: bool = Field(False, description="Whether to update customer validation fields with invoice values")
