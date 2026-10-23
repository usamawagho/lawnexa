from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="client")  # "client", "lawyer", "admin"
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=True)  # Admin approval flag
    avatar = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lawyer_profile = relationship("Lawyer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    client_appointments = relationship("Appointment", back_populates="client")
    sent_messages = relationship("ChatMessage", foreign_keys="ChatMessage.sender_id", back_populates="sender")
    received_messages = relationship("ChatMessage", foreign_keys="ChatMessage.receiver_id", back_populates="receiver")
    likes = relationship("Like", back_populates="user")
    comments = relationship("Comment", back_populates="user")


class Lawyer(Base):
    __tablename__ = "lawyers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    name = Column(String, nullable=False)
    specialty = Column(String, index=True, nullable=False)
    address = Column(String, nullable=True)
    city = Column(String, nullable=True, default="Karachi")
    area = Column(String, nullable=True, default="Saddar")
    phone = Column(String, nullable=True)
    law_card_url = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)
    lat = Column(Float, nullable=False, default=31.5204)
    lng = Column(Float, nullable=False, default=74.3587)

    license_number = Column(String, nullable=True)
    bar_association = Column(String, index=True, nullable=True)
    experience_years = Column(Integer, default=0)
    rating = Column(Float, default=5.0)

    user = relationship("User", back_populates="lawyer_profile")
    appointments = relationship("Appointment", back_populates="lawyer")
    posts = relationship("Post", back_populates="lawyer")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=False)
    booking_date = Column(String, nullable=False)
    time_slot = Column(String, nullable=False)
    case_summary = Column(String, nullable=False)
    status = Column(String, default="pending")

    client = relationship("User", back_populates="client_appointments")
    lawyer = relationship("Lawyer", back_populates="appointments")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    receiver_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message = Column(Text, nullable=False)
    quote_amount = Column(Float, nullable=True)
    quote_status = Column(String, default="none")
    timestamp = Column(DateTime, default=datetime.utcnow)

    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    receiver = relationship("User", foreign_keys=[receiver_id], back_populates="received_messages")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id"), nullable=False)
    bar_association = Column(String, index=True, nullable=False)
    content = Column(Text, nullable=False)
    media_url = Column(String, nullable=True)
    media_type = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    lawyer = relationship("Lawyer", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    post = relationship("Post", back_populates="likes")
    user = relationship("User", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    post = relationship("Post", back_populates="comments")
    user = relationship("User", back_populates="comments")