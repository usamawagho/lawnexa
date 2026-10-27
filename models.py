"""
SQLAlchemy Relational Database Schemas for LawNexa
"""
import enum
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, Float, Text, DateTime, ForeignKey, Enum
)
from sqlalchemy.orm import relationship
from database import Base

class UserRole(str, enum.Enum):
    CLIENT = "client"
    LAWYER = "lawyer"
    BUSINESS = "business"
    ADMIN = "admin"

class RequestStatus(str, enum.Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEED_INFO = "NEED_INFO"
    PROPOSAL_SENT = "PROPOSAL_SENT"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    password_hash = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.CLIENT, nullable=False)
    city = Column(String, nullable=True, default="Lahore")
    area = Column(String, nullable=True)
    address = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Lawyer details
    license_number = Column(String, nullable=True)
    bar_association = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    jurisdiction = Column(String, nullable=True)
    specialization = Column(String, nullable=True)
    consultation_fee = Column(Float, default=0.0)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Business details
    business_type = Column(String, nullable=True)
    business_registration_no = Column(String, nullable=True)
    representative_name = Column(String, nullable=True)

class CorporateRequest(Base):
    __tablename__ = "corporate_requests"

    id = Column(Integer, primary_key=True, index=True)
    business_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    request_type = Column(String, nullable=False)
    urgency = Column(String, default="Medium")
    status = Column(Enum(RequestStatus), default=RequestStatus.SUBMITTED)
    assigned_lawyer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    business = relationship("User", foreign_keys=[business_id])
    assigned_lawyer = relationship("User", foreign_keys=[assigned_lawyer_id])
    proposals = relationship("CorporateProposal", back_populates="request")

class CorporateProposal(Base):
    __tablename__ = "corporate_proposals"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(Integer, ForeignKey("corporate_requests.id"), nullable=False)
    scope = Column(Text, nullable=False)
    amount_pkr = Column(Float, nullable=False)
    validity_days = Column(Integer, default=14)
    terms = Column(Text, nullable=True)
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.utcnow)

    request = relationship("CorporateRequest", back_populates="proposals")

class EscrowTransaction(Base):
    __tablename__ = "escrow_transactions"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    lawyer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    title = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    method = Column(String, nullable=False)
    transaction_id = Column(String, nullable=True)
    status = Column(String, default="held")
    created_at = Column(DateTime, default=datetime.utcnow)
