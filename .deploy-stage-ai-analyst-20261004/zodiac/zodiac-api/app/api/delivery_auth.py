"""
Unified delivery authentication: mTLS (client certificate) or token-based authentication.
Supports hybrid authentication: X-Customer-Token, X-Supplier-Token, Bearer, or client certificate.
Returns customer_id for the delivery-settings API.
"""
import logging
from typing import Optional
from fastapi import HTTPException, status, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from datetime import datetime

from ..database import get_db
from ..models.customer_token import CustomerToken
from ..models.supplier_token import SupplierToken
from ..models.user import verify_api_key
from ..api.supplier_auth import get_client_ip, validate_ip_whitelist
from ..middleware.mtls_auth import validate_mtls_request

logger = logging.getLogger("zodiac-api.delivery_auth")

security = HTTPBearer(auto_error=False)


async def get_delivery_customer_id(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_customer_token: Optional[str] = Header(None, alias="X-Customer-Token"),
    x_supplier_token: Optional[str] = Header(None, alias="X-Supplier-Token"),
    db: Session = Depends(get_db),
) -> str:
    """
    Hybrid authentication for delivery API: mTLS (client certificate), customer token, or supplier token.
    Priority order:
    1. Client certificate (mTLS) - highest priority
    2. X-Customer-Token
    3. X-Supplier-Token
    4. Bearer token
    
    Returns the customer_id to use for delivery settings.
    """
    # Priority 1: Try mTLS authentication (client certificate)
    is_mtls_valid, mtls_customer_id, mtls_cert, mtls_error = await validate_mtls_request(
        request=request,
        db=db,
        require_certificate=False,
    )
    
    if is_mtls_valid and mtls_customer_id:
        logger.info("Delivery auth: mTLS certificate customer_id=%s (cert_id=%s)", mtls_customer_id, mtls_cert.id)
        return mtls_customer_id
    
    # Priority 2-4: Token-based authentication
    token_customer = x_customer_token
    token_supplier = x_supplier_token
    if credentials:
        bearer = credentials.credentials
        if not token_customer and not token_supplier:
            token_customer = bearer
            token_supplier = bearer
        elif not token_customer:
            token_customer = bearer
        elif not token_supplier:
            token_supplier = bearer

    # Try X-Customer-Token
    if token_customer:
        record = db.query(CustomerToken).filter(
            CustomerToken.token == token_customer,
            CustomerToken.is_active == True,
        ).first()
        if record and verify_api_key(token_customer, record.token_hash):
            if record.expires_at and record.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Customer token has expired.",
                )
            record.last_used_at = datetime.utcnow()
            db.commit()
            logger.info("Delivery auth: customer token customer_id=%s", record.customer_id)
            return record.customer_id.strip()

    # Then try supplier token
    if token_supplier:
        st = db.query(SupplierToken).filter(
            SupplierToken.token == token_supplier,
            SupplierToken.is_active == True,
        ).first()
        if st and verify_api_key(token_supplier, st.token_hash):
            if st.expires_at and st.expires_at < datetime.utcnow():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Supplier token has expired.",
                )
            client_ip = get_client_ip(request)
            if not validate_ip_whitelist(client_ip, st.ip_whitelist):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="IP address not authorized for this supplier token",
                )
            st.last_used_at = datetime.utcnow()
            db.commit()
            customer_id = st.supplier_rfc.strip()
            logger.info("Delivery auth: supplier token customer_id=%s", customer_id)
            return customer_id

    # No valid authentication found
    error_detail = "Authentication required. Use client certificate (mTLS), X-Customer-Token, or X-Supplier-Token header."
    if mtls_error:
        error_detail += f" Certificate error: {mtls_error}"
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=error_detail,
    )
