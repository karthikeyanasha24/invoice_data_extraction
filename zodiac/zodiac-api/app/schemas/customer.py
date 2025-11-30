from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CustomerBase(BaseModel):
    """Base customer schema with common fields"""
    customer_id: str = Field(..., description="Unique customer identifier")
    format: str = Field(default="edifact", description="Target format for this customer (e.g., 'edifact', 'x12', 'xml')")
    api_address: Optional[str] = Field(None, description="API endpoint address for this customer")
    validation_rules: Optional[str] = Field(None, description="JSON string containing validation rules")


class CustomerCreate(CustomerBase):
    """Schema for creating a new customer"""
    pass


class CustomerUpdate(BaseModel):
    """Schema for updating an existing customer"""
    customer_id: Optional[str] = None
    format: Optional[str] = None
    api_address: Optional[str] = None
    validation_rules: Optional[str] = None


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
