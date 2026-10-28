import json
import os
from datetime import datetime
from typing import Any, Optional

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

import auth
import database
import models
import schemas


# -------------------- APP SETUP --------------------

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="LawNexa API", version="2.8.0")

default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://lawnexa.vercel.app",
]

env_origins = os.getenv("FRONTEND_ORIGINS", "")
if env_origins:
    allowed_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
else:
    allowed_origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer_scheme = HTTPBearer(auto_error=False)


def parse_specializations(value: Optional[str]) -> list[str]:
    if not value:
        return []

    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        bearer_scheme
    ),
    db: Session = Depends(database.get_db),
):
    """Verify the JWT and load the active user from the database."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = auth.decode_access_token(credentials.credentials)

    if not payload or not payload.get("sub"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        db.query(models.User)
        .filter(models.User.email == payload["sub"])
        .first()
    )

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def user_response(user: models.User) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "role": user.role,
        "full_name": user.full_name,
        "phone": user.phone,
        "address": user.address,
        "city": user.city,
        "profile_image": user.profile_image,
        "bar_council_no": user.bar_council_no,
        "chamber_address": user.chamber_address,
        "experience_years": user.experience_years,
        "consultation_fee": user.consultation_fee,
        "specializations": parse_specializations(user.specializations),
    }


# -------------------- HEALTH & ROOT --------------------

@app.get("/")
def root_check():
    return {"status": "online", "service": "LawNexa API", "version": "2.8.0"}


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "LawNexa API"}


# -------------------- AUTHENTICATION --------------------

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
def register_user(
    user_data: schemas.UserCreate,
    db: Session = Depends(database.get_db),
):
    email = str(user_data.email).strip().lower()

    if db.query(models.User).filter(
        models.User.email == email
    ).first():
        raise HTTPException(
            status_code=400,
            detail="Email address pehle se registered hai.",
        )

    if user_data.role not in {"client", "advocate"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid account role.",
        )

    specializations = user_data.specializations or []

    if user_data.role == "advocate" and len(specializations) > 3:
        raise HTTPException(
            status_code=400,
            detail="Maximum 3 specializations allowed.",
        )

    if user_data.experience_years is not None and user_data.experience_years < 0:
        raise HTTPException(
            status_code=400,
            detail="Experience years cannot be negative.",
        )

    if user_data.consultation_fee is not None and user_data.consultation_fee < 0:
        raise HTTPException(
            status_code=400,
            detail="Consultation fee cannot be negative.",
        )

    try:
        hashed_password = auth.get_password_hash(user_data.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    full_name_str = (user_data.full_name or "").strip()

    user = models.User(
        full_name=full_name_str,
        email=email,
        phone=user_data.phone,
        address=user_data.address,
        hashed_password=hashed_password,
        role=user_data.role,
        city=user_data.city,
        specializations=json.dumps(specializations),
        bar_council_no=user_data.bar_council_no,
        chamber_address=user_data.chamber_address,
        experience_years=user_data.experience_years,
        consultation_fee=user_data.consultation_fee,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Email address pehle se registered hai.",
        )
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Registration failed: {str(exc)}",
        ) from exc

    token = auth.create_access_token(
        data={"sub": user.email, "role": user.role}
    )

    return {
        "status": "success",
        "token": token,
        "user": user_response(user),
    }


@app.post("/api/login")
def login_user(
    user_data: schemas.UserLogin,
    db: Session = Depends(database.get_db),
):
    email = str(user_data.email).strip().lower()

    user = (
        db.query(models.User)
        .filter(models.User.email == email)
        .first()
    )

    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Invalid email address or password.",
        )

    password_valid = auth.verify_password(
        user_data.password, user.hashed_password
    )

    if (
        not password_valid
        and isinstance(user.hashed_password, str)
        and user.hashed_password == "hashed_" + user_data.password
    ):
        try:
            user.hashed_password = auth.get_password_hash(
                user_data.password
            )
            db.commit()
            password_valid = True
        except ValueError:
            db.rollback()
            password_valid = False

    if not password_valid:
        raise HTTPException(
            status_code=401,
            detail="Invalid email address or password.",
        )

    token = auth.create_access_token(
        data={"sub": user.email, "role": user.role}
    )

    return {
        "token": token,
        "user": user_response(user),
    }


# -------------------- USER PROFILE --------------------

@app.get("/api/profile")
def get_user_profile(
    email: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
):
    if email and email.strip().lower() != current_user.email.lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot access another user's profile.",
        )

    return user_response(current_user)


@app.put("/api/profile")
def update_user_profile(
    data: schemas.UserProfileUpdate,
    email: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    if email and email.strip().lower() != current_user.email.lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot update another user's profile.",
        )

    if data.full_name is not None:
        current_user.full_name = data.full_name.strip()

    if data.address is not None:
        current_user.address = data.address

    if data.city is not None:
        current_user.city = data.city

    if data.profile_image is not None:
        current_user.profile_image = data.profile_image

    if data.specializations is not None:
        if len(data.specializations) > 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum 3 specializations allowed.",
            )
        current_user.specializations = json.dumps(data.specializations)

    if data.bar_council_no is not None:
        current_user.bar_council_no = data.bar_council_no

    if data.chamber_address is not None:
        current_user.chamber_address = data.chamber_address

    if data.experience_years is not None:
        if data.experience_years < 0:
            raise HTTPException(
                status_code=400,
                detail="Experience years cannot be negative.",
            )
        current_user.experience_years = data.experience_years

    if data.consultation_fee is not None:
        if data.consultation_fee < 0:
            raise HTTPException(
                status_code=400,
                detail="Consultation fee cannot be negative.",
            )
        current_user.consultation_fee = data.consultation_fee

    try:
        db.commit()
        db.refresh(current_user)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Profile update failed.",
        ) from exc

    return {"status": "success", "message": "Profile updated successfully", "user": user_response(current_user)}


# -------------------- DOCUMENT TEMPLATES --------------------

DOCUMENT_TEMPLATES = [
    {
        "id": "kiraya_nama",
        "name": "Rent Agreement (کرایہ نامہ)",
        "description": "Standard tenancy agreement for residential/commercial property in Pakistan.",
        "fields": [
            {"name": "landlord_name", "label": "Landlord Name (مالک مکان)", "type": "text", "placeholder": "Ahmad Raza"},
            {"name": "landlord_cnic", "label": "Landlord CNIC", "type": "text", "placeholder": "42101-1234567-1"},
            {"name": "tenant_name", "label": "Tenant Name (کرایہ دار)", "type": "text", "placeholder": "Muhammad Usama"},
            {"name": "tenant_cnic", "label": "Tenant CNIC", "type": "text", "placeholder": "42101-7654321-2"},
            {"name": "property_address", "label": "Property Address (پتہ)", "type": "text", "placeholder": "House No. 12, Block 4, Gulshan, Karachi"},
            {"name": "monthly_rent", "label": "Monthly Rent (PKR)", "type": "number", "placeholder": "35000"},
            {"name": "security_deposit", "label": "Advance/Deposit (PKR)", "type": "number", "placeholder": "70000"},
            {"name": "commencement_date", "label": "Agreement Start Date", "type": "date", "placeholder": ""},
            {"name": "duration_months", "label": "Duration (Months)", "type": "number", "placeholder": "11"},
        ],
    },
    {
        "id": "vehicle_sale",
        "name": "Vehicle Sale Agreement (معاہدہ فروخت گاڑی)",
        "description": "Agreement for selling or purchasing vehicles.",
        "fields": [
            {"name": "seller_name", "label": "Seller Name (بیچنے والا)", "type": "text", "placeholder": "Ali Hassan"},
            {"name": "seller_cnic", "label": "Seller CNIC", "type": "text", "placeholder": "42101-1111111-1"},
            {"name": "buyer_name", "label": "Buyer Name (خریدنے والا)", "type": "text", "placeholder": "Bilal Ahmed"},
            {"name": "buyer_cnic", "label": "Buyer CNIC", "type": "text", "placeholder": "42101-2222222-2"},
            {"name": "vehicle_make_model", "label": "Vehicle Model & Name", "type": "text", "placeholder": "Honda Civic 2021"},
            {"name": "reg_no", "label": "Registration No", "type": "text", "placeholder": "KBL-1234"},
            {"name": "engine_no", "label": "Engine No", "type": "text", "placeholder": "R18A-987654"},
            {"name": "chassis_no", "label": "Chassis No", "type": "text", "placeholder": "N32-456789"},
            {"name": "sale_amount", "label": "Total Price (PKR)", "type": "number", "placeholder": "3200000"},
        ],
    },
    {
        "id": "bail_application",
        "name": "Bail Application (درخواست ضمانت)",
        "description": "Criminal bail petition format under Criminal Procedure Code (CrPC).",
        "fields": [
            {"name": "court_name", "label": "Court Name", "type": "text", "placeholder": "In the Court of Judicial Magistrate, Karachi"},
            {"name": "applicant_name", "label": "Applicant/Accused Name", "type": "text", "placeholder": "Tariq Mahmood"},
            {"name": "fir_no", "label": "FIR No", "type": "text", "placeholder": "124/2026"},
            {"name": "police_station", "label": "Police Station (تھانہ)", "type": "text", "placeholder": "PS Ferozabad"},
            {"name": "offense_sections", "label": "PPC Sections", "type": "text", "placeholder": "PPC 379 / 411"},
            {"name": "bail_grounds", "label": "Grounds for Bail", "type": "textarea", "placeholder": "Applicant is innocent, falsely implicated due to rivalry, ready to furnish surety bonds."},
        ],
    },
    {
        "id": "cheque_notice",
        "name": "Cheque Bounce Legal Notice (نوٹس عدم ادائیگی چیک)",
        "description": "Legal notice template relating to a dishonoured cheque.",
        "fields": [
            {"name": "sender_name", "label": "Payee Name (نوٹس دہندہ)", "type": "text", "placeholder": "Zubair Khan"},
            {"name": "recipient_name", "label": "Drawer Name (خلاف ورزی کنندہ)", "type": "text", "placeholder": "Kamran Sheikh"},
            {"name": "cheque_no", "label": "Cheque Number", "type": "text", "placeholder": "CHK-99887766"},
            {"name": "cheque_amount", "label": "Cheque Amount (PKR)", "type": "number", "placeholder": "500000"},
            {"name": "bank_name", "label": "Bank & Branch", "type": "text", "placeholder": "Meezan Bank, Main Branch"},
            {"name": "notice_days", "label": "Demand Notice Period (Days)", "type": "number", "placeholder": "14"},
        ],
    },
    {
        "id": "vakalatnama",
        "name": "Vakalatnama (وکالت نامہ)",
        "description": "Legal power of attorney template for advocate representation.",
        "fields": [
            {"name": "court_title", "label": "Honourable Court", "type": "text", "placeholder": "High Court of Sindh at Karachi"},
            {"name": "case_title", "label": "Case Title / Suits No", "type": "text", "placeholder": "Muhammad Usama Vs State"},
            {"name": "client_name", "label": "Client Name (سائل)", "type": "text", "placeholder": "Muhammad Usama"},
            {"name": "lawyer_name", "label": "Advocate Name (وکیل)", "type": "text", "placeholder": "Adv. Sarah Khan"},
            {"name": "bar_reg", "label": "Advocate Bar Reg No", "type": "text", "placeholder": "BC-9876/SHC"},
        ],
    },
]

@app.get("/api/documents/templates")
def get_document_templates():
    return DOCUMENT_TEMPLATES


# -------------------- USER DOCUMENTS --------------------

@app.post("/api/documents/save")
def save_user_document(
    req: schemas.DocumentSaveRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    new_doc = models.UserDocument(
        user_id=current_user.id,
        doc_type=req.doc_type,
        title=req.title,
        form_data=json.dumps(req.form_data),
        generated_html=req.generated_html,
    )

    try:
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Document could not be saved.",
        ) from exc

    return {
        "status": "success",
        "message": "Document saved successfully!",
        "document_id": new_doc.id,
    }


@app.get("/api/documents/my-documents")
def get_my_documents(
    email: Optional[str] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    if email and email.strip().lower() != current_user.email.lower():
        raise HTTPException(
            status_code=403,
            detail="You cannot access another user's documents.",
        )

    docs = (
        db.query(models.UserDocument)
        .filter(models.UserDocument.user_id == current_user.id)
        .order_by(models.UserDocument.id.desc())
        .all()
    )

    result = []

    for document in docs:
        try:
            form_data = json.loads(document.form_data) if document.form_data else {}
        except (ValueError, TypeError):
            form_data = {}

        result.append({
            "id": document.id,
            "doc_type": document.doc_type,
            "title": document.title,
            "created_at": (
                document.created_at.strftime("%Y-%m-%d %H:%M")
                if document.created_at else None
            ),
            "form_data": form_data,
            "generated_html": document.generated_html,
        })

    return result


# -------------------- LEGAL RESEARCH --------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class LegalResearchRequest(BaseModel):
    history: list[ChatMessage]
    user_input: str
    language: Optional[str] = "roman_urdu"


@app.post("/api/ai-legal-research")
async def process_legal_research(req: LegalResearchRequest):
    if len(req.history) < 3:
        return {
            "status": "clarifying",
            "reply": (
                "Aapke bataye gaye facts ke mutabiq: "
                "Kya is haadse me koi physical injury aayi hai "
                "ya sirf vehicle/property damage hua hai?"
            ),
            "case_brief": None,
        }

    return {
        "status": "completed",
        "reply": "Preliminary legal research completed.",
        "case_brief": {
            "category": "Criminal & Traffic Law",
            "applicable_laws": [
                "PPC Section 279 (Rash Driving)",
                "PPC Section 427 (Mischief & Damage)",
            ],
            "summary": req.user_input,
            "recommended_specialty": "Criminal & Traffic Law Specialist",
        },
    }