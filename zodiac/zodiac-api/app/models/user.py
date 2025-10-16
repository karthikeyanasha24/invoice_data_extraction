from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from passlib.context import CryptContext
from datetime import datetime
import uuid
import bcrypt
import hashlib
import base64
import secrets

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
    
    # API Key fields
    api_user_identifier = Column(String, unique=True, index=True, default=lambda: str(uuid.uuid4()))
    api_user_allowed = Column(Boolean, default=True)
    api_key_hashed = Column(String, nullable=True)
    api_key_created_at = Column(DateTime(timezone=True), nullable=True)
    api_key_updated_at = Column(DateTime(timezone=True), nullable=True)
    api_key_deactivated_at = Column(DateTime(timezone=True), nullable=True)
    api_key_allow_list = Column(JSON, nullable=True)  # List of allowed IP addresses
    
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

# API Key functions
def generate_api_key() -> str:
    """Generate a secure API key."""
    # Generate a long random string
    key = secrets.token_urlsafe(64)  # 64 bytes = ~86 characters
    return key

def hash_api_key(api_key: str, salt: str = None) -> str:
    """Hash an API key with optional salt."""
    import os
    hash_key = os.getenv('API_HASH_KEY', 'default-hash-key-change-in-production')
    
    if salt is None:
        salt = secrets.token_hex(16)
    
    # Combine key, salt, and hash_key
    combined = f"{api_key}:{salt}:{hash_key}"
    
    # Create SHA-256 hash
    hashed = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    
    # Return salt:hash format for verification
    return f"{salt}:{hashed}"

def verify_api_key(api_key: str, hashed_key: str) -> bool:
    """Verify an API key against its hash."""
    try:
        if not hashed_key or ':' not in hashed_key:
            return False
        
        salt, stored_hash = hashed_key.split(':', 1)
        
        # Recreate the hash
        import os
        hash_key = os.getenv('API_HASH_KEY', 'default-hash-key-change-in-production')
        combined = f"{api_key}:{salt}:{hash_key}"
        computed_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()
        
        return computed_hash == stored_hash
    except Exception:
        return False

def encode_api_key_for_transport(api_key: str) -> str:
    """Encode API key for transport (base64)."""
    return base64.b64encode(api_key.encode('utf-8')).decode('utf-8')

def decode_api_key_from_transport(encoded_key: str) -> str:
    """Decode API key from transport (base64)."""
    try:
        return base64.b64decode(encoded_key.encode('utf-8')).decode('utf-8')
    except Exception:
        return None
