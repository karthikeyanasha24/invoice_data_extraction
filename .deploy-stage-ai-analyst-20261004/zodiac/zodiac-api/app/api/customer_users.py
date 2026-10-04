"""
Customer users API - create customer users and assign customer IDs. Admin only.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import List
import re

from ..database import get_db
from ..models.user import ZodiacUser, get_password_hash
from ..models.user_customer import UserCustomer
from ..models.customer import Customer
from ..api.auth import get_current_user

router = APIRouter(prefix="/customer-users", tags=["customer-users"])
logger = logging.getLogger(__name__)


def require_admin(current_user: ZodiacUser) -> None:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


class CustomerUserCreate(BaseModel):
    email: str
    username: str
    password: str
    customer_ids: List[str] = []

    @field_validator("email")
    @classmethod
    def email_not_empty_and_format(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if not v:
            raise ValueError("Email is required")
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("Username is required")
        if len(v) < 2:
            raise ValueError("Username must be at least 2 characters")
        if len(v) > 64:
            raise ValueError("Username must be at most 64 characters")
        if not re.match(r"^[a-zA-Z0-9_.-]+$", v):
            raise ValueError("Username may only contain letters, numbers, dots, hyphens and underscores")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        if not v:
            raise ValueError("Password is required")
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class CustomerUserResponse(BaseModel):
    id: int
    email: str
    username: str
    is_customer_user: bool
    customer_ids: List[str] = []

    class Config:
        from_attributes = True


class AssignCustomersRequest(BaseModel):
    customer_ids: List[str]


@router.post("", response_model=CustomerUserResponse, status_code=status.HTTP_201_CREATED)
def create_customer_user(
    body: CustomerUserCreate,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a customer user (is_customer_user=True). Admin only.

    Optional ``customer_ids`` assigns portal access in the same request.
    """
    require_admin(current_user)
    existing_by_email = db.query(ZodiacUser).filter(ZodiacUser.email == body.email).first()
    if existing_by_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this email already exists",
        )
    existing_by_username = db.query(ZodiacUser).filter(ZodiacUser.username == body.username).first()
    if existing_by_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this username already exists",
        )

    customer_ids = list(
        dict.fromkeys([c.strip() for c in (body.customer_ids or []) if c and c.strip()])
    )
    for cid in customer_ids:
        if not db.query(Customer).filter(Customer.customer_id == cid).first():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Customer '{cid}' not found",
            )

    hashed = get_password_hash(body.password)
    user = ZodiacUser(
        email=body.email,
        username=body.username,
        password_hash=hashed,
        is_customer_user=True,
    )
    db.add(user)
    db.flush()
    for cid in customer_ids:
        db.add(UserCustomer(user_id=user.id, customer_id=cid))
    db.commit()
    db.refresh(user)
    logger.info(
        f"Customer user created: {user.email} by admin {current_user.id} "
        f"(assigned={len(customer_ids)})"
    )
    return CustomerUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        is_customer_user=True,
        customer_ids=customer_ids,
    )


@router.get("", response_model=List[CustomerUserResponse])
def list_customer_users(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all customer users with their assigned customer IDs. Admin only."""
    require_admin(current_user)
    users = db.query(ZodiacUser).filter(
        ZodiacUser.is_customer_user == True
    ).order_by(ZodiacUser.email).all()
    result = []
    for u in users:
        assignments = db.query(UserCustomer.customer_id).filter(UserCustomer.user_id == u.id).all()
        customer_ids = [r[0] for r in assignments]
        result.append(CustomerUserResponse(
            id=u.id,
            email=u.email,
            username=u.username,
            is_customer_user=getattr(u, "is_customer_user", False),
            customer_ids=customer_ids,
        ))
    return result


@router.get("/me/customers", response_model=List[str])
def get_my_customers(
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's assigned customer IDs (for customer users)."""
    if not getattr(current_user, "is_customer_user", False):
        return []
    assignments = db.query(UserCustomer.customer_id).filter(UserCustomer.user_id == current_user.id).all()
    return [r[0] for r in assignments]


@router.get("/{user_id}/customers", response_model=List[str])
def get_user_customers(
    user_id: int,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get assigned customer IDs for a customer user. Admin only."""
    require_admin(current_user)
    user = db.query(ZodiacUser).filter(ZodiacUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    assignments = db.query(UserCustomer.customer_id).filter(UserCustomer.user_id == user_id).all()
    return [r[0] for r in assignments]


@router.put("/{user_id}/customers", response_model=CustomerUserResponse)
def assign_customers(
    user_id: int,
    body: AssignCustomersRequest,
    current_user: ZodiacUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Replace assigned customer IDs for a customer user. Admin only."""
    require_admin(current_user)
    user = db.query(ZodiacUser).filter(ZodiacUser.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not getattr(user, "is_customer_user", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is not a customer user",
        )
    customer_ids = list(dict.fromkeys([c.strip() for c in (body.customer_ids or []) if c and c.strip()]))
    db.query(UserCustomer).filter(UserCustomer.user_id == user_id).delete()
    for cid in customer_ids:
        db.add(UserCustomer(user_id=user_id, customer_id=cid))
    db.commit()
    db.refresh(user)
    logger.info(f"Assigned {len(customer_ids)} customers to user {user_id} by admin {current_user.id}")
    return CustomerUserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        is_customer_user=getattr(user, "is_customer_user", False),
        customer_ids=customer_ids,
    )
