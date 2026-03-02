"""
User-Customer assignment: links customer users to customer_ids they can see documents for.
"""
from sqlalchemy import Column, Integer, String, ForeignKey, PrimaryKeyConstraint
from ..database import Base


class UserCustomer(Base):
    __tablename__ = "user_customers"
    __table_args__ = (
        PrimaryKeyConstraint("user_id", "customer_id", name="pk_user_customers"),
    )

    user_id = Column(Integer, ForeignKey("zodiac_users.id", ondelete="CASCADE"), nullable=False)
    customer_id = Column(String(255), nullable=False, index=True)
