"""
Customer Delivery Schemas
Schemas for customer file delivery functionality
"""
from pydantic import BaseModel, Field
from typing import Optional


class SendToCustomerResponse(BaseModel):
    """Response schema for sending files to customer"""
    success: bool = Field(..., description="Whether the file was successfully sent to customer")
    message: str = Field(..., description="Result message")
    remote_path: Optional[str] = Field(None, description="Remote path where file was delivered (if applicable)")
    
    class Config:
        from_attributes = True
