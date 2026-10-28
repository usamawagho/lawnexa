from sqlalchemy import Column, Integer, String, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from database import Base
import datetime

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    phone = Column(String(20), nullable=True)
    address = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="client") # 'client' or 'advocate'
    
    # Profile Picture
    profile_image = Column(Text, nullable=True)

    # Advocate Dynamic Fields
    city = Column(String(100), nullable=True)
    specializations = Column(Text, nullable=True)
    bar_council_no = Column(String(100), nullable=True)
    chamber_address = Column(String(255), nullable=True)
    experience_years = Column(Integer, nullable=True)
    consultation_fee = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True)

    documents = relationship("UserDocument", back_populates="owner")

class CaseBrief(Base):
    __tablename__ = "case_briefs"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, nullable=True)
    category = Column(String(100))
    applicable_laws = Column(Text)
    summary = Column(Text)
    recommended_specialty = Column(String(100))

class UserDocument(Base):
    __tablename__ = "user_documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    doc_type = Column(String(50), nullable=False) # 'kiraya_nama', 'vehicle_sale', 'bail_app', 'cheque_notice', 'vakalatnama'
    title = Column(String(200), nullable=False)
    form_data = Column(Text, nullable=False) # Stored JSON
    generated_html = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    owner = relationship("User", back_populates="documents")
