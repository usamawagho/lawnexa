from sqlalchemy import Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="client")
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=True)
    avatar = Column(String, nullable=True)
    city = Column(String, nullable=True)
    address = Column(String, nullable=True)
    residential_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    lawyer_profile = relationship("Lawyer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    bookings = relationship("Appointment", back_populates="client")
    likes = relationship("Like", back_populates="user")
    comments = relationship("Comment", back_populates="user")


class Lawyer(Base):
    __tablename__ = "lawyers"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String, nullable=False)
    specialty = Column(String, default="General Practice")
    address = Column(String, nullable=True)
    chamber_address = Column(String, nullable=True)
    city = Column(String, nullable=True)
    area = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    law_card_url = Column(String, nullable=True)
    is_verified = Column(Boolean, default=False)
    lat = Column(Float, default=31.5204)
    lng = Column(Float, default=74.3587)
    license_number = Column(String, nullable=True)
    bar_association = Column(String, nullable=True)
    experience_years = Column(Integer, default=0)

    user = relationship("User", back_populates="lawyer_profile")
    appointments = relationship("Appointment", back_populates="lawyer")
    posts = relationship("Post", back_populates="lawyer")


class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    lawyer_id = Column(Integer, ForeignKey("lawyers.id", ondelete="CASCADE"))
    booking_date = Column(String, nullable=False)
    time_slot = Column(String, nullable=False)
    case_summary = Column(Text, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    client = relationship("User", back_populates="bookings")
    lawyer = relationship("Lawyer", back_populates="appointments")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    receiver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    message = Column(Text, nullable=False)
    quote_amount = Column(Float, nullable=True)
    quote_status = Column(String, default="none")
    is_read = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    lawyer_id = Column(Integer, ForeignKey("lawyers.id", ondelete="CASCADE"))
    bar_association = Column(String, nullable=True)
    title = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    lawyer = relationship("Lawyer", back_populates="posts")
    likes = relationship("Like", back_populates="post", cascade="all, delete-orphan")
    comments = relationship("Comment", back_populates="post", cascade="all, delete-orphan")


class Like(Base):
    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))

    post = relationship("Post", back_populates="likes")
    user = relationship("User", back_populates="likes")


class Comment(Base):
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True, index=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    post = relationship("Post", back_populates="comments")
    user = relationship("User", back_populates="comments")