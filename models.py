
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Text,
    DateTime,
    ForeignKey,
    Float,
)
from sqlalchemy.orm import relationship
from database import Base
import datetime


def utcnow_naive() -> datetime.datetime:
    """Return a UTC timestamp for legacy timezone-naive database columns."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    # Basic account information
    full_name = Column("name", String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=True)
    phone = Column(String(20), nullable=True)
    address = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="client", nullable=True)

    # Profile information: mapped to existing database columns
    profile_image = Column("avatar", Text, nullable=True)
    city = Column(String(100), nullable=True)
    residential_address = Column(String(255), nullable=True)
    area = Column(String(100), nullable=True)

    # Advocate information
    specializations = Column(Text, nullable=True)
    bar_council_no = Column("license_number", String(100), nullable=True)
    bar_association = Column(String(150), nullable=True)
    chamber_address = Column(String(255), nullable=True)
    experience_years = Column(Integer, default=0, nullable=True)
    consultation_fee = Column(Integer, nullable=True)

    # Account status and approval
    is_active = Column(Boolean, default=True, nullable=True)
    is_approved = Column(Boolean, default=False, nullable=True)

    created_at = Column(DateTime, default=utcnow_naive, nullable=True)

    # Relationships
    documents = relationship("UserDocument", back_populates="owner")


class CaseBrief(Base):
    __tablename__ = "case_briefs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=True)
    category = Column(String(100), nullable=True)
    applicable_laws = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    recommended_specialty = Column(String(100), nullable=True)


class UserDocument(Base):
    __tablename__ = "user_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doc_type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    form_data = Column(Text, nullable=False)
    generated_html = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow_naive, nullable=True)

    owner = relationship("User", back_populates="documents")


class Lawyer(Base):
    __tablename__ = "lawyers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    name = Column(String(150), nullable=False)
    specialty = Column(String(150), nullable=True)
    address = Column(String(255), nullable=True)
    chamber_address = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    area = Column(String(100), nullable=True)
    phone = Column(String(20), nullable=True)

    law_card_url = Column(String(500), nullable=True)
    is_verified = Column(Boolean, default=False, nullable=True)

    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)

    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(150), nullable=True)
    experience_years = Column(Integer, nullable=True)


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)

    client_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=True)

    booking_date = Column(String(50), nullable=False)
    time_slot = Column(String(100), nullable=False)
    case_summary = Column(Text, nullable=True)
    status = Column(String(50), default="pending", nullable=True)
    created_at = Column(DateTime, default=utcnow_naive, nullable=True)
    location = Column(String(255), nullable=True)
    meeting_type = Column(String(20), default="physical", nullable=True)
    meeting_mode = Column(String(20), default="chamber", nullable=True)
    consultation_fee = Column(Integer, nullable=True)
