from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Optional
from datetime import datetime, timedelta
from ..models.customer import Customer
from ..models.user import ZodiacUser
from ..models.customer_receiver_rfc import CustomerReceiverRfc
from ..schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerListResponse,
    CustomerDelete,
)
from ..models.customer_token import CustomerToken
from ..models.user import ZodiacUser, generate_api_key, hash_api_key
from ..database import get_db
from ..api.auth import get_current_user
import logging

router = APIRouter(prefix="/customers", tags=["customers"])
logger = logging.getLogger("zodiac-api.customers")


@router.post("/", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    customer: CustomerCreate,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Create a new customer record"""
    try:
        logger.info(f"👤 Creating customer: {customer.customer_id}")

        # Check if customer already exists
        existing_customer = db.query(Customer).filter(
            Customer.customer_id == customer.customer_id
        ).first()

        if existing_customer:
            logger.warning(f"⚠️ Customer already exists: {customer.customer_id}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Customer with ID '{customer.customer_id}' already exists",
            )

        # Create new customer
        db_customer = Customer(
            customer_id=customer.customer_id,
            target_format=customer.target_format,
            tax_value=customer.tax_value,
            tax_percentage=customer.tax_percentage,
            validation_fields=customer.validation_fields,
        )
        db.add(db_customer)
        db.commit()
        db.refresh(db_customer)

        logger.info(f"✅ Customer created successfully: {db_customer.id}")
        return db_customer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error creating customer: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating customer: {str(e)}",
        )


@router.get("/", response_model=CustomerListResponse)
def list_customers(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(100, ge=1, le=500, description="Number of records to return"),
    search: str = Query(None, description="Search by customer_id"),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Get all customers with pagination and optional search"""
    try:
        logger.info(f"📋 Fetching customers - skip: {skip}, limit: {limit}")

        # Build query
        query = db.query(Customer)

        # Apply search filter if provided
        if search:
            logger.info(f"🔍 Searching customers with: {search}")
            query = query.filter(Customer.customer_id.contains(search))

        # Get total count
        total = query.count()

        # Apply pagination
        customers = query.offset(skip).limit(limit).all()

        logger.info(f"✅ Retrieved {len(customers)} customers (total: {total})")
        return CustomerListResponse(
            total=total,
            skip=skip,
            limit=limit,
            customers=customers,
        )

    except Exception as e:
        logger.error(f"❌ Error fetching customers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching customers: {str(e)}",
        )


def _require_admin(current_user: ZodiacUser) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


class ReceiverRfcsBody(BaseModel):
    receiver_rfcs: list[str]


class CustomerTokenGenerateBody(BaseModel):
    expires_in_days: Optional[int] = 365
    notes: Optional[str] = None


class CustomerTokenGenerateResponse(BaseModel):
    success: bool
    token: str
    customer_id: str
    expires_at: Optional[datetime]
    message: str


class CustomerTokenInfoResponse(BaseModel):
    has_token: bool
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    is_active: Optional[bool] = None


@router.get("/{customer_id}/receiver-rfcs", response_model=list[str])
def get_customer_receiver_rfcs(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """List receiver RFCs for a customer (for To ERP / inbound). Admin only."""
    _require_admin(current_user)
    rows = db.query(CustomerReceiverRfc.receiver_rfc).filter(
        CustomerReceiverRfc.customer_id == customer_id
    ).all()
    return [r[0] for r in rows]


@router.put("/{customer_id}/receiver-rfcs", response_model=list[str])
def set_customer_receiver_rfcs(
    customer_id: str,
    body: ReceiverRfcsBody,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Set receiver RFCs for a customer (for To ERP / inbound). Admin only."""
    _require_admin(current_user)
    db.query(CustomerReceiverRfc).filter(
        CustomerReceiverRfc.customer_id == customer_id
    ).delete()
    for rfc in (body.receiver_rfcs or []):
        rfc = (rfc or "").strip().upper()
        if rfc:
            db.add(CustomerReceiverRfc(customer_id=customer_id, receiver_rfc=rfc))
    db.commit()
    rows = db.query(CustomerReceiverRfc.receiver_rfc).filter(
        CustomerReceiverRfc.customer_id == customer_id
    ).all()
    return [r[0] for r in rows]


# ---------- Delivery settings (install certificate / SFTP) ----------


def _ensure_customer_exists(db: Session, customer_id: str) -> None:
    """Raise 404 if customer does not exist."""
    if not db.query(Customer).filter(Customer.customer_id == customer_id).first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Customer '{customer_id}' not found",
        )


# --- Customer token (for API authentication) ---

@router.post("/{customer_id}/token/generate", response_model=CustomerTokenGenerateResponse)
def generate_customer_token(
    customer_id: str,
    body: Optional[CustomerTokenGenerateBody] = Body(None),
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Generate an API token for a customer for API authentication. Admin only. Token is shown once."""
    _require_admin(current_user)
    _ensure_customer_exists(db, customer_id)
    body = body or CustomerTokenGenerateBody()
    expires_in_days = body.expires_in_days or 365
    expires_at = datetime.utcnow() + timedelta(days=expires_in_days) if expires_in_days else None

    plain_token = generate_api_key()
    token_hash = hash_api_key(plain_token)

    existing = db.query(CustomerToken).filter(CustomerToken.customer_id == customer_id).first()
    if existing:
        existing.token = plain_token
        existing.token_hash = token_hash
        existing.is_active = True
        existing.expires_at = expires_at
        existing.notes = body.notes
        existing.created_by = current_user.id
        db.commit()
        db.refresh(existing)
        return CustomerTokenGenerateResponse(
            success=True,
            token=plain_token,
            customer_id=customer_id,
            expires_at=expires_at,
            message="Token regenerated. Store it securely; it will not be shown again.",
        )

    record = CustomerToken(
        customer_id=customer_id,
        token=plain_token,
        token_hash=token_hash,
        is_active=True,
        expires_at=expires_at,
        created_by=current_user.id,
        notes=body.notes,
    )
    db.add(record)
    db.commit()
    return CustomerTokenGenerateResponse(
        success=True,
        token=plain_token,
        customer_id=customer_id,
        expires_at=expires_at,
        message="Token created. Store it securely; it will not be shown again.",
    )


@router.get("/{customer_id}/token", response_model=CustomerTokenInfoResponse)
def get_customer_token_info(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Get customer token metadata (no token value). Admin only."""
    _require_admin(current_user)
    _ensure_customer_exists(db, customer_id)
    record = db.query(CustomerToken).filter(CustomerToken.customer_id == customer_id).first()
    if not record:
        return CustomerTokenInfoResponse(has_token=False)
    return CustomerTokenInfoResponse(
        has_token=True,
        last_used_at=record.last_used_at,
        expires_at=record.expires_at,
        is_active=record.is_active,
    )


@router.delete("/{customer_id}/token")
def revoke_customer_token(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Revoke the customer's API token. Admin only."""
    _require_admin(current_user)
    _ensure_customer_exists(db, customer_id)
    record = db.query(CustomerToken).filter(CustomerToken.customer_id == customer_id).first()
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No token found for this customer.")
    record.is_active = False
    db.commit()
    return {"success": True, "message": "Token revoked."}


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Get a specific customer by customer_id"""
    try:
        logger.info(f"🔍 Fetching customer: {customer_id}")

        customer = db.query(Customer).filter(
            Customer.customer_id == customer_id
        ).first()

        if not customer:
            logger.warning(f"⚠️ Customer not found: {customer_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with ID '{customer_id}' not found",
            )

        logger.info(f"✅ Found customer: {customer_id}")
        return customer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching customer: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching customer: {str(e)}",
        )


@router.get("/by-id/{db_id}", response_model=CustomerResponse)
def get_customer_by_db_id(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Get a specific customer by database ID"""
    try:
        logger.info(f"🔍 Fetching customer by database ID: {db_id}")

        customer = db.query(Customer).filter(Customer.id == db_id).first()

        if not customer:
            logger.warning(f"⚠️ Customer not found with database ID: {db_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with database ID {db_id} not found",
            )

        logger.info(f"✅ Found customer with database ID: {db_id}")
        return customer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching customer by database ID: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error fetching customer: {str(e)}",
        )


@router.put("/{customer_id}", response_model=CustomerResponse)
def update_customer(
    customer_id: str,
    customer_update: CustomerUpdate,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Update an existing customer"""
    try:
        logger.info(f"✏️ Updating customer: {customer_id}")

        customer = db.query(Customer).filter(
            Customer.customer_id == customer_id
        ).first()

        if not customer:
            logger.warning(f"⚠️ Customer not found: {customer_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with ID '{customer_id}' not found",
            )

        # Update only provided fields
        update_data = customer_update.dict(exclude_unset=True)
        
        # Check if updating customer_id to a new value that already exists
        if "customer_id" in update_data and update_data["customer_id"] != customer_id:
            existing = db.query(Customer).filter(
                Customer.customer_id == update_data["customer_id"]
            ).first()
            if existing:
                logger.warning(f"⚠️ Customer ID already exists: {update_data['customer_id']}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Customer with ID '{update_data['customer_id']}' already exists",
                )

        for field, value in update_data.items():
            setattr(customer, field, value)

        db.commit()
        db.refresh(customer)

        logger.info(f"✅ Customer updated successfully: {customer_id}")
        return customer

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error updating customer: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error updating customer: {str(e)}",
        )


@router.delete("/{customer_id}", response_model=CustomerDelete)
def delete_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Delete a customer"""
    try:
        logger.info(f"🗑️ Deleting customer: {customer_id}")

        customer = db.query(Customer).filter(
            Customer.customer_id == customer_id
        ).first()

        if not customer:
            logger.warning(f"⚠️ Customer not found: {customer_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with ID '{customer_id}' not found",
            )

        db_id = customer.id
        db.delete(customer)
        db.commit()

        logger.info(f"✅ Customer deleted successfully: {customer_id}")
        return CustomerDelete(
            success=True,
            message=f"Customer '{customer_id}' deleted successfully",
            deleted_id=db_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting customer: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting customer: {str(e)}",
        )


@router.post("/by-id/{db_id}/delete", response_model=CustomerDelete)
def delete_customer_by_db_id(
    db_id: int,
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Delete a customer by database ID"""
    try:
        logger.info(f"🗑️ Deleting customer with database ID: {db_id}")

        customer = db.query(Customer).filter(Customer.id == db_id).first()

        if not customer:
            logger.warning(f"⚠️ Customer not found with database ID: {db_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer with database ID {db_id} not found",
            )

        customer_id = customer.customer_id
        db.delete(customer)
        db.commit()

        logger.info(f"✅ Customer deleted successfully (db_id: {db_id})")
        return CustomerDelete(
            success=True,
            message=f"Customer '{customer_id}' (database ID: {db_id}) deleted successfully",
            deleted_id=db_id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting customer by database ID: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error deleting customer: {str(e)}",
        )


@router.get("/formats/list", response_model=dict)
def get_supported_formats(
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Get list of supported target formats for invoice conversion"""
    logger.info("📋 Fetching supported formats")
    return {
        "supported_formats": ["X12", "EDIFACT", "PIDX", "PDF", "XML", "UBL", "CFDI"],
        "descriptions": {
            "X12": "ASC X12 EDI format",
            "EDIFACT": "UN/EDIFACT electronic data interchange format",
            "PIDX": "Petroleum Industry Data Exchange format",
            "PDF": "Portable Document Format (human-readable invoice)",
            "XML": "XML format (UBL 2.0 standard)",
            "UBL": "Universal Business Language 2.0",
            "CFDI": "Mexican CFDI (Comprobante Fiscal Digital por Internet)",
        },
    }


@router.post("/bulk/create", response_model=dict)
def bulk_create_customers(
    customers_data: list[CustomerCreate],
    db: Session = Depends(get_db),
    current_user: ZodiacUser = Depends(get_current_user),
):
    """Create multiple customers in bulk"""
    try:
        logger.info(f"👥 Bulk creating {len(customers_data)} customers")

        created_customers = []
        failed_customers = []

        for customer_data in customers_data:
            try:
                # Check if customer already exists
                existing = db.query(Customer).filter(
                    Customer.customer_id == customer_data.customer_id
                ).first()

                if existing:
                    logger.warning(f"⚠️ Customer already exists: {customer_data.customer_id}")
                    failed_customers.append({
                        "customer_id": customer_data.customer_id,
                        "reason": "Customer already exists",
                    })
                    continue

                # Create new customer
                db_customer = Customer(
                    customer_id=customer_data.customer_id,
                    target_format=customer_data.target_format,
                    tax_value=customer_data.tax_value,
                    tax_percentage=customer_data.tax_percentage,
                    validation_fields=customer_data.validation_fields,
                )
                db.add(db_customer)
                created_customers.append(customer_data.customer_id)

            except Exception as e:
                logger.error(f"❌ Error creating customer {customer_data.customer_id}: {str(e)}")
                failed_customers.append({
                    "customer_id": customer_data.customer_id,
                    "reason": str(e),
                })

        db.commit()
        logger.info(
            f"✅ Bulk create completed: {len(created_customers)} created, {len(failed_customers)} failed"
        )

        return {
            "total": len(customers_data),
            "created": len(created_customers),
            "failed": len(failed_customers),
            "created_customer_ids": created_customers,
            "failed_customers": failed_customers,
        }

    except Exception as e:
        logger.error(f"❌ Error in bulk create: {str(e)}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error in bulk create: {str(e)}",
        )
