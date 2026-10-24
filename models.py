"""All SQLAlchemy models use the one shared Base from database.py."""
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(160), nullable=False)
    phone = Column(String(32), unique=True, index=True, nullable=True)
    email = Column(String(320), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="client", index=True)
    is_approved = Column(Boolean, nullable=False, default=True, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    avatar = Column(Text, nullable=True)
    specialty = Column(String(160), nullable=True)
    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(200), nullable=True)
    experience_years = Column(Integer, nullable=True, default=0)
    city = Column(String(100), nullable=True, default="Karachi")
    area = Column(String(160), nullable=True, default="Saddar / City Court")
    chamber_address = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lawyer_profile = relationship("Lawyer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    client_appointments = relationship("Appointment", back_populates="client", foreign_keys="Appointment.client_id")
    sent_messages = relationship("ChatMessage", foreign_keys="ChatMessage.sender_id", back_populates="sender")
    received_messages = relationship("ChatMessage", foreign_keys="ChatMessage.receiver_id", back_populates="receiver")
    likes = relationship("Like", back_populates="user", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="user", cascade="all, delete-orphan")


class Lawyer(Base):
    __tablename__ = "lawyers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    name = Column(String(160), nullable=False)
    specialty = Column(String(160), nullable=False, default="General Practice")
    address = Column(String(300), nullable=True)
    phone = Column(String(32), nullable=True)
    law_card_url = Column(String(500), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False, index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(200), index=True, nullable=True)
    experience_years = Column(Integer, default=0)
    rating = Column(Float, nullable=True)

    user = relationship("User", back_populates="lawyer_profile")
    appointments = relationship("Appointment", back_populates="lawyer")
    posts = relationship("Post", back_populates="lawyer", cascade="all, delete-orphan")


class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id", ondelete="CASCADE"), nullable=False)
    booking_date = Column(String(30), nullable=False)
    time_slot = Column(String(40), nullable=False)
    case_summary = Column(Text, nullable=False)
    location = Column(String(200), nullable=True)
    status = Column(String(20), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    client = relationship("User", back_populates="client_appointments", foreign_keys=[client_id])
    lawyer = relationship("Lawyer", back_populates="appointments")


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message = Column(Text, nullable=False)
    quote_amount = Column(Float, nullable=True)
    quote_status = Column(String(20), nullable=False, default="none")
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")


class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id", ondelete="CASCADE"), nullable=False, index=True)
    bar_association = Column(String(200), nullable=False, index=True)
    title = Column(String(250), nullable=False, default="Legal Update")
    category = Column(String(100), nullable=False, default="Legal Insight & Analysis")
    content = Column(Text, nullable=False)
    media_url = Column(String(500), nullable=True)
    media_type = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    lawyer = relationship("Lawyer", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_like_post_user"),)
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    post = relationship("Post", back_populates="likes")
    user = relationship("User", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    post = relationship("Post", back_populates="comments")
    user = relationship("User", back_populates="comments")
