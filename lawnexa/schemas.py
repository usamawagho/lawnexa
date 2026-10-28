from pydantic import BaseModel, EmailStr
from typing import Optional, List, Dict, Any

class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    password: str
    phone: Optional[str] = None
    address: Optional[str] = None
    role: str = "client"
    city: Optional[str] = None
    specializations: Optional[List[str]] = []
    bar_council_no: Optional[str] = None
    chamber_address: Optional[str] = None
    experience_years: Optional[int] = None
    consultation_fee: Optional[int] = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserProfileUpdate(BaseModel):
    full_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    profile_image: Optional[str] = None
    specializations: Optional[List[str]] = []
    bar_council_no: Optional[str] = None
    chamber_address: Optional[str] = None
    experience_years: Optional[int] = None
    consultation_fee: Optional[int] = None

class DocumentSaveRequest(BaseModel):
    doc_type: str
    title: str
    form_data: Dict[str, Any]
    generated_html: str
    user_email: str
