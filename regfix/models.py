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
    is_ad_free_enabled = Column(Boolean, nullable=False, default=False)
    avatar = Column(Text, nullable=True)
    specialty = Column(String(160), nullable=True)
    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(200), nullable=True)
    experience_years = Column(Integer, nullable=True, default=0)
    city = Column(String(100), nullable=True, default="Karachi")
    area = Column(String(160), nullable=True, default="Saddar / City Court")
    chamber_address = Column(String(300), nullable=True)
    address = Column(Text, nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
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
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True, index=True)
    area = Column(String(160), nullable=True, index=True)
    phone = Column(String(32), nullable=True)
    law_card_url = Column(String(500), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False, index=True)
    verification_status = Column(String(20), nullable=False, default="pending", index=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(200), index=True, nullable=True)
    experience_years = Column(Integer, default=0)
    rating = Column(Float, nullable=True)
    consultation_fee = Column(Float, nullable=True, default=1000.0)
    is_virtual_available = Column(Boolean, nullable=False, default=False)
    virtual_consult_notes = Column(Text, nullable=True)
    is_featured_ad_active = Column(Boolean, nullable=False, default=False, index=True)
    featured_until = Column(DateTime, nullable=True)
    ad_expiry_date = Column(DateTime, nullable=True)
    ad_budget_spent = Column(Float, nullable=False, default=0.0)

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
    is_promoted = Column(Boolean, nullable=False, default=False, index=True)
    promoted_until = Column(DateTime, nullable=True)
    promotion_budget = Column(Float, nullable=False, default=0.0)
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


class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    balance = Column(Float, nullable=False, default=0.0)
    pending_escrow = Column(Float, nullable=False, default=0.0)
    total_withdrawn = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    user = relationship("User")


class EscrowTransaction(Base):
    __tablename__ = "escrow_transactions"
    id = Column(Integer, primary_key=True, index=True)
    booking_id = Column(Integer, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    gross_amount = Column(Float, nullable=False)
    platform_commission = Column(Float, nullable=False, default=0.15)
    net_lawyer_payout = Column(Float, nullable=False)
    payment_gateway = Column(String(40), nullable=False, default="Wallet")
    transaction_ref = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(40), nullable=False, default="HELD_IN_ESCROW", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class WalletWithdrawal(Base):
    __tablename__ = "wallet_withdrawals"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    payout_method = Column(String(40), nullable=False)
    account_details = Column(String(255), nullable=False)
    status = Column(String(30), nullable=False, default="REQUESTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class PublicQuestion(Base):
    __tablename__ = "public_questions"
    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    question_title = Column(String(250), nullable=False)
    category = Column(String(100), nullable=False, default="General Legal")
    full_details = Column(Text, nullable=False)
    is_anonymous = Column(Boolean, nullable=False, default=False)
    status = Column(String(20), nullable=False, default="OPEN", index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    answers = relationship("QuestionAnswer", back_populates="question", cascade="all, delete-orphan")


class QuestionAnswer(Base):
    __tablename__ = "question_answers"
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey("public_questions.id", ondelete="CASCADE"), nullable=False, index=True)
    lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    answer_text = Column(Text, nullable=False)
    upvotes_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    question = relationship("PublicQuestion", back_populates="answers")


class CaseTracker(Base):
    __tablename__ = "case_tracker"
    id = Column(Integer, primary_key=True, index=True)
    lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    court_name = Column(String(200), nullable=False)
    bench_no = Column(String(80), nullable=True)
    case_title = Column(String(250), nullable=False)
    case_no = Column(String(120), nullable=False)
    client_name = Column(String(160), nullable=True)
    client_phone = Column(String(32), nullable=True)
    hearing_date = Column(String(20), nullable=False, index=True)
    status = Column(String(30), nullable=False, default="SCHEDULED")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CorporateSubscription(Base):
    __tablename__ = "corporate_subscriptions"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String(200), nullable=False)
    admin_user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_type = Column(String(40), nullable=False, default="BASIC_STARTUP")
    monthly_price = Column(Float, nullable=False, default=0.0)
    status = Column(String(30), nullable=False, default="ACTIVE", index=True)
    contracts_limit = Column(Integer, nullable=False, default=5)
    contracts_used = Column(Integer, nullable=False, default=0)
    assigned_retainer_lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)


class CorporateRequest(Base):
    __tablename__ = "corporate_requests"
    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("corporate_subscriptions.id", ondelete="CASCADE"), nullable=False, index=True)
    requested_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    request_type = Column(String(50), nullable=False, default="CONTRACT_REVIEW")
    description = Column(Text, nullable=False)
    document_url = Column(String(500), nullable=True)
    status = Column(String(30), nullable=False, default="SUBMITTED")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class BarElectionCampaign(Base):
    __tablename__ = "bar_election_campaigns"
    id = Column(Integer, primary_key=True, index=True)
    candidate_lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    bar_association = Column(String(200), nullable=False, index=True)
    position_title = Column(String(120), nullable=False)
    manifesto_text = Column(Text, nullable=False)
    campaign_banner_url = Column(String(500), nullable=True)
    votes_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DisputeCase(Base):
    __tablename__ = "dispute_cases"
    id = Column(Integer, primary_key=True, index=True)
    claimant_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    respondent_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    mediator_lawyer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    dispute_type = Column(String(100), nullable=False)
    claim_amount = Column(Float, nullable=True)
    description = Column(Text, nullable=False)
    settlement_status = Column(String(40), nullable=False, default="OPEN", index=True)
    settlement_draft = Column(Text, nullable=True)
    claimant_otp_verified = Column(Boolean, nullable=False, default=False)
    respondent_otp_verified = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Invite(Base):
    __tablename__ = "invites"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(320), nullable=True, index=True)
    phone = Column(String(32), nullable=True, index=True)
    role = Column(String(30), nullable=False, default="lawyer")
    token = Column(String(100), unique=True, nullable=False, index=True)
    invited_by = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String(120), nullable=False)
    target_type = Column(String(80), nullable=True)
    target_id = Column(String(80), nullable=True)
    details = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
