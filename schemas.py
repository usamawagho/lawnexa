"""Validated request schemas for the current LawNexa API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    email: EmailStr = Field(max_length=150)
    password: str = Field(min_length=8, max_length=72)
    phone: Optional[str] = Field(default=None, max_length=20)
    address: Optional[str] = Field(default=None, max_length=255)
    role: str = Field(default="client", max_length=20)
    city: Optional[str] = Field(default=None, max_length=100)
    specializations: Optional[List[str]] = Field(default_factory=list, max_length=3)
    bar_council_no: Optional[str] = Field(default=None, max_length=100)
    bar_association: Optional[str] = Field(default=None, max_length=150)
    chamber_address: Optional[str] = Field(default=None, max_length=255)
    experience_years: Optional[int] = Field(default=None, ge=0, le=100)
    consultation_fee: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)


class UserLogin(BaseModel):
    email: EmailStr = Field(max_length=150)
    password: str = Field(min_length=1, max_length=72)


class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    address: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    profile_image: Optional[str] = Field(default=None, max_length=2000)
    # Omitted fields must stay unchanged on a partial profile update.
    specializations: Optional[List[str]] = Field(default=None, max_length=3)
    bar_council_no: Optional[str] = Field(default=None, max_length=100)
    bar_association: Optional[str] = Field(default=None, max_length=150)
    chamber_address: Optional[str] = Field(default=None, max_length=255)
    experience_years: Optional[int] = Field(default=None, ge=0, le=100)
    consultation_fee: Optional[int] = Field(default=None, ge=0, le=1_000_000_000)


class DocumentSaveRequest(BaseModel):
    doc_type: str = Field(min_length=1, max_length=50)
    title: str = Field(min_length=1, max_length=200)
    form_data: Dict[str, Any] = Field(max_length=100)
    generated_html: str = Field(min_length=1, max_length=300_000)
    # Retained only for older clients; ownership always comes from the JWT.
    user_email: Optional[EmailStr] = None
