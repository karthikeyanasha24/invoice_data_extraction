"""
Customer Token Authentication
Validates X-Customer-Token or Bearer for customer-scoped APIs (e.g. delivery settings).
"""
import logging
from typing import Optional
from fastapi import HTTPException, status, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..models.customer_token import CustomerToken
from ..models.user import verify_api_key

logger = logging.getLogger("zodiac-api.customer_auth")

security = HTTPBearer(auto_error=False)


async def get_customer_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_customer_token: Optional[str] = Header(None, alias="X-Customer-Token"),
    db: Session = Depends(get_db),
) -> CustomerToken:
    """
    Authenticate using customer token from X-Customer-Token header or Bearer.
    """
    token = x_customer_token
    if not token and credentials:
        token = credentials.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer token required. Use X-Customer-Token header or Authorization: Bearer <token>.",
        )

    record = db.query(CustomerToken).filter(
        CustomerToken.token == token,
        CustomerToken.is_active == True,
    ).first()

    if not record:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive customer token",
        )

    if not verify_api_key(token, record.token_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
        )

    if record.expires_at and record.expires_at < datetime.utcnow():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer token has expired. Contact administrator for a new token.",
        )

    record.last_used_at = datetime.utcnow()
    db.commit()

    logger.info("Customer token authenticated: customer_id=%s", record.customer_id)
    return record
