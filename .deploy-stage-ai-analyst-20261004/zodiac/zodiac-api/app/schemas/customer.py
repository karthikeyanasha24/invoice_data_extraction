from pydantic import BaseModel, Field
from typing import Optional, Dict
from datetime import datetime
from decimal import Decimal


class CustomerBase(BaseModel):
    """Base customer schema with common fields (V2)"""
    customer_id: str = Field(..., description="Unique customer identifier")
    target_format: str = Field(..., description="Target format for conversion (x12, edifact, pidx, pdf, xml, ubl, cfdi)")
    tax_value: Decimal = Field(..., description="Fixed tax amount for this customer", ge=0)
    tax_percentage: Decimal = Field(..., description="Tax rate percentage", ge=0, le=100)
    validation_fields: Optional[str] = Field(None, description="JSON string {field_name: expected_value} for validation")


class CustomerCreate(CustomerBase):
    """Schema for creating a new customer"""
    pass


class CustomerUpdate(BaseModel):
    """Schema for updating an existing customer"""
    customer_id: Optional[str] = None
    target_format: Optional[str] = None
    tax_value: Optional[Decimal] = None
    tax_percentage: Optional[Decimal] = None
    validation_fields: Optional[str] = None


class CustomerResponse(CustomerBase):
    """Schema for returning customer data from API"""
    id: int = Field(..., description="Database ID")
    created_at: datetime = Field(..., description="Timestamp when customer was created")

    class Config:
        from_attributes = True


class CustomerListResponse(BaseModel):
    """Schema for returning paginated customer list"""
    total: int = Field(..., description="Total number of customers")
    skip: int = Field(..., description="Number of records skipped")
    limit: int = Field(..., description="Number of records per page")
    customers: list[CustomerResponse] = Field(..., description="List of customers")


class CustomerDelete(BaseModel):
    """Schema for delete response"""
    success: bool = Field(..., description="Whether deletion was successful")
    message: str = Field(..., description="Deletion result message")
    deleted_id: int = Field(..., description="ID of deleted customer")
