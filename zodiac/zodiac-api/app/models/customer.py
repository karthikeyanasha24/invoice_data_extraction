from sqlalchemy import Column, Integer, String, Text, DateTime, func
from ..database import Base


class Customer(Base):
    """Customer model for zodiac_customers table"""
    __tablename__ = "zodiac_customers"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(String(255), unique=True, nullable=False, index=True)
    format = Column(String(32), nullable=False, default="xml")
    validation_rules = Column(Text, nullable=True)  # JSON string with required XML fields
    created_at = Column(DateTime, server_default=func.now())

    def __repr__(self):
        return f"<Customer(id={self.id}, customer_id='{self.customer_id}', format='{self.format}')>"
