from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..models.customer import Customer
from ..models.user import ZodiacUser
from ..schemas.customer import (
    CustomerCreate,
    CustomerUpdate,
    CustomerResponse,
    CustomerListResponse,
    CustomerDelete,
)
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
            format=customer.format,
            api_address=customer.api_address,
            validation_rules=customer.validation_rules,
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
    """Get list of supported file formats"""
    logger.info("📋 Fetching supported formats")
    return {
        "supported_formats": ["XML", "X12", "EDIFACT", "XML_EMBED_PDF", "XML_EMBED_X12", "XML_EMBED_EDIFACT"],
        "descriptions": {
            "XML": "XML format with validation (pass-through)",
            "X12": "ASC X12 EDI format with EDINation validation",
            "EDIFACT": "UN/EDIFACT electronic data interchange format",
            "XML_EMBED_PDF": "Generate PDF from XML and embed in XML for third-party API",
            "XML_EMBED_X12": "Generate X12 from XML and embed in XML for third-party API",
            "XML_EMBED_EDIFACT": "Generate EDIFACT from XML and embed in XML for third-party API",
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
                    format=customer_data.format,
                    api_address=customer_data.api_address,
                    validation_rules=customer_data.validation_rules,
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
