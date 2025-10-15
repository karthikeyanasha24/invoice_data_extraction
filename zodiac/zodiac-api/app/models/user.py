from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from passlib.context import CryptContext
from datetime import datetime
import uuid
import bcrypt

from ..database import Base

class ZodiacUser(Base):
    __tablename__ = "zodiac_users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relationships
    successful_invoices = relationship("ZodiacInvoiceSuccessEdi", back_populates="user")
    failed_invoices = relationship("ZodiacInvoiceFailedEdi", back_populates="user")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        # Truncate password to 72 bytes if necessary
        if len(plain_password.encode('utf-8')) > 72:
            plain_password = plain_password[:72]
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        # Fallback to direct bcrypt verification
        try:
            if len(plain_password.encode('utf-8')) > 72:
                plain_password = plain_password[:72]
            return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
        except Exception:
            return False

def get_password_hash(password: str) -> str:
    """Hash a password."""
    try:
        # Truncate password to 72 bytes if necessary
        if len(password.encode('utf-8')) > 72:
            password = password[:72]
        return pwd_context.hash(password)
    except Exception as e:
        # Fallback to direct bcrypt hashing
        if len(password.encode('utf-8')) > 72:
            password = password[:72]
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
