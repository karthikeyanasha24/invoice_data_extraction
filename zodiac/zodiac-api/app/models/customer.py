from sqlalchemy import Column, Integer, String, Text, DateTime, Numeric, func
from ..database import Base


class Customer(Base):
    """Customer model for zodiac_customers table (V2)"""
    __tablename__ = "zodiac_customers"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String(255), unique=True, nullable=False, index=True)
    target_format = Column(String(32), nullable=False, default="xml")  # Renamed from 'format'
    tax_value = Column(Numeric(10, 2), nullable=False, default=0)  # NEW: Fixed tax amount
    tax_percentage = Column(Numeric(5, 2), nullable=False, default=0)  # NEW: Tax rate %
    validation_fields = Column(Text, nullable=True)  # Renamed from 'validation_rules': JSON {field_name: expected_value}
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<Customer(id={self.id}, customer_id='{self.customer_id}', target_format='{self.target_format}')>"
