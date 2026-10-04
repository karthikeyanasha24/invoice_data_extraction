"""
Customer-Receiver RFC mapping: links customer_id to receiver_rfc for inbound (SAT) documents.
"""
from sqlalchemy import Column, String, PrimaryKeyConstraint
from ..database import Base


class CustomerReceiverRfc(Base):
    __tablename__ = "customer_receiver_rfc"
    __table_args__ = (
        PrimaryKeyConstraint("customer_id", "receiver_rfc", name="pk_customer_receiver_rfc"),
    )

    customer_id = Column(String(255), nullable=False, index=True)
    receiver_rfc = Column(String(13), nullable=False, index=True)
