"""LawNexa API: shared models, safe public schemas and protected actions."""
import logging
from dotenv import load_dotenv
load_dotenv()
import math
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy import or_, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from jose import JWTError, jwt
from passlib.context import CryptContext

from database import Base, engine, get_db, SessionLocal
from models import (User, Lawyer, Appointment, ChatMessage, Post, Like, Wallet, EscrowTransaction, WalletWithdrawal, PublicQuestion, QuestionAnswer, CaseTracker, CorporateSubscription, CorporateRequest, BarElectionCampaign, Invite, AuditLog, DisputeCase)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("lawnexa")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY or len(SECRET_KEY) < 32:
    if ENVIRONMENT == "production":
        raise RuntimeError("SECRET_KEY must be set in production and contain at least 32 characters; generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'")
    # Local-only key avoids a universal, hard-coded secret. Set SECRET_KEY for persistent local sessions.
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning("SECRET_KEY was not set; using a temporary development key. Set SECRET_KEY in .env.")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
oauth2_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)
app = FastAPI(title="LawNexa API", version="4.2.0")

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

@app.get("/", include_in_schema=False)
def app_home():
    """Serve the public application; the private admin UI has its own non-public route."""
    return FileResponse(BASE_DIR / "index.html")

@app.get("/admin", include_in_schema=False)
def admin_portal():
    return FileResponse(BASE_DIR / "admin.html")

allowed_origins = [x.strip() for x in os.getenv(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000,http://localhost:5500,http://127.0.0.1:5500"
).split(",") if x.strip()]
if ENVIRONMENT == "production" and (not allowed_origins or "*" in allowed_origins):
    raise RuntimeError("Set explicit ALLOWED_ORIGINS in production; wildcard origins are not allowed.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# All model classes register on one metadata object before tables are created.
Base.metadata.create_all(bind=engine)

# Lightweight additive migration for existing SQLite/PostgreSQL installs.
def upgrade_schema():
    migrations = {
        "chat_messages": {"media_url": "VARCHAR(1000)", "media_type": "VARCHAR(30)"},
        "users": {
            "is_approved": "BOOLEAN NOT NULL DEFAULT TRUE",
            "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
            "avatar": "TEXT",
            "specialty": "VARCHAR(160)",
            "license_number": "VARCHAR(100)",
            "bar_association": "VARCHAR(200)",
            "experience_years": "INTEGER DEFAULT 0",
            "city": "VARCHAR(100) DEFAULT 'Karachi'",
            "area": "VARCHAR(160) DEFAULT 'Saddar / City Court'",
            "chamber_address": "VARCHAR(300)",
            "address": "TEXT",
            "lat": "FLOAT",
            "lng": "FLOAT",
            "is_ad_free_enabled": "BOOLEAN NOT NULL DEFAULT FALSE",
            "created_at": "TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP",
        },
        "posts": {
            "title": "VARCHAR(250) NOT NULL DEFAULT 'Legal Update'",
            "category": "VARCHAR(100) NOT NULL DEFAULT 'Legal Insight & Analysis'",
            "is_promoted": "BOOLEAN NOT NULL DEFAULT FALSE",
            "promoted_until": "TIMESTAMP WITHOUT TIME ZONE",
            "promotion_budget": "FLOAT NOT NULL DEFAULT 0",
        },
        "lawyers": {
            "consultation_fee": "FLOAT DEFAULT 1000.0",
            "is_virtual_available": "BOOLEAN NOT NULL DEFAULT FALSE",
            "verification_status": "VARCHAR(20) NOT NULL DEFAULT 'pending'",
            "virtual_consult_notes": "TEXT",
            "is_featured_ad_active": "BOOLEAN NOT NULL DEFAULT FALSE",
            "featured_until": "TIMESTAMP WITHOUT TIME ZONE",
            "ad_expiry_date": "TIMESTAMP WITHOUT TIME ZONE",
            "ad_budget_spent": "FLOAT NOT NULL DEFAULT 0",
            "city": "VARCHAR(100)",
            "area": "VARCHAR(160)",
            "address": "VARCHAR(500)",
        },
        "appointments": {
            "location": "VARCHAR(200)",
        },
    }

    with engine.begin() as connection:
        for table, columns in migrations.items():
            inspector = inspect(connection)
            if table not in inspector.get_table_names():
                continue

            present = {
                column["name"]
                for column in inspector.get_columns(table)
            }

            for name, sql_type in columns.items():
                if name not in present:
                    connection.execute(
                        text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}')
                    )
                    logger.info("Added missing column %s.%s", table, name)


upgrade_schema()


class UserRegister(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    role: str = "client"
    city: Optional[str] = "Karachi"
    area: Optional[str] = "Saddar / City Court"
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = Field(default=0, ge=0, le=80)
    chamber_address: Optional[str] = None
    address: Optional[str] = None
    lat: float = Field(default=0.0, ge=-90, le=90)
    lng: float = Field(default=0.0, ge=-180, le=180)


class LawyerPublic(BaseModel):
    id: int
    user_id: int
    lawyer_id: Optional[int] = None
    name: str
    avatar: Optional[str] = None
    city: str = ""
    area: str = ""
    specialty: str = "General Practice"
    experience: int = 0
    experience_years: int = 0
    bar_association: Optional[str] = None
    address: Optional[str] = None
    rating: Optional[float] = None
    is_verified: bool = False
    verification_status: str = "pending"
    consultation_fee: float = 1000.0
    is_virtual_available: bool = False
    virtual_consult_notes: Optional[str] = None
    is_featured_ad_active: bool = False


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[EmailStr] = None
    avatar: Optional[str] = Field(default=None, max_length=1000000)
    city: Optional[str] = None
    area: Optional[str] = None
    chamber_address: Optional[str] = None
    address: Optional[str] = None
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = Field(default=None, ge=0, le=80)
    consultation_fee: Optional[float] = Field(default=None, ge=0, le=10000000)
    is_virtual_available: Optional[bool] = None
    virtual_consult_notes: Optional[str] = Field(default=None, max_length=2000)
    is_featured_ad_active: Optional[bool] = None
    is_ad_free_enabled: Optional[bool] = None


class DocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    doc_type: str = Field(default="Agreement", alias="type", min_length=2, max_length=100)
    party1: str = Field(default="First Party", max_length=200)
    party2: str = Field(default="Second Party", max_length=200)
    court: str = Field(default="Karachi, Pakistan", max_length=200)
    purpose: str = Field(default="Legal Representation", max_length=2000)
    father_name: Optional[str] = Field(default=None, max_length=200)
    cnic: Optional[str] = Field(default=None, max_length=30)
    residence_address: Optional[str] = Field(default=None, max_length=500)
    fir_number: Optional[str] = Field(default=None, max_length=100)


class PostCreate(BaseModel):
    title: str = Field(default="Legal Update", min_length=1, max_length=250)
    category: str = Field(default="Legal Insight & Analysis", min_length=2, max_length=100)
    content: str = Field(min_length=1, max_length=10000)
    bar_association: str = Field(min_length=2, max_length=200)
    media_url: Optional[str] = Field(default=None, max_length=500)
    media_type: Optional[str] = Field(default=None, max_length=20)


class ChatCreate(BaseModel):
    receiver_id: int = Field(gt=0)
    message: str = Field(default="", max_length=10000)
    quote_amount: Optional[float] = Field(default=None, gt=0, le=100000000)
    media_url: Optional[str] = Field(default=None, max_length=1000)
    media_type: Optional[str] = Field(default=None, max_length=30)


class BookingCreate(BaseModel):
    lawyer_id: int = Field(gt=0)
    booking_date: str = Field(min_length=4, max_length=30)
    time_slot: str = Field(min_length=1, max_length=40)
    location: Optional[str] = Field(default=None, max_length=200)
    case_summary: str = Field(min_length=5, max_length=5000)


class FirAnalysisRequest(BaseModel):
    text: str = Field(default="", max_length=50000)


def _normalize_phone(value):
    if value is None:
        return None
    return "".join(str(value).split()).replace("-", "")

def _clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _user_public(user: User, include_private: bool = False) -> dict:
    data = {
        "id": user.id, "name": user.name, "role": user.role,
        "avatar": user.avatar, "city": user.city, "area": user.area, "address": user.address, "lat": user.lat, "lng": user.lng,
        "specialty": user.specialty, "experience": user.experience_years or 0,
        "experience_years": user.experience_years or 0,
        "is_approved": bool(user.is_approved),
        "is_ad_free_enabled": bool(user.is_ad_free_enabled),
        "consultation_fee": float(user.lawyer_profile.consultation_fee or 1000) if user.lawyer_profile else 1000,
        "is_virtual_available": bool(user.lawyer_profile and user.lawyer_profile.is_virtual_available),
        "virtual_consult_notes": user.lawyer_profile.virtual_consult_notes if user.lawyer_profile else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if include_private:
        data.update({"email": user.email, "phone": user.phone, "license_number": user.license_number,
                     "bar_association": user.bar_association, "chamber_address": user.chamber_address, "address": user.address, "lat": user.lat, "lng": user.lng,
                     "is_active": bool(user.is_active)})
    return data


def _lawyer_public(user: User) -> dict:
    profile = user.lawyer_profile
    return {
        "id": user.id,
        "user_id": user.id,
        "lawyer_id": profile.id if profile else None,
        "name": user.name,
        "avatar": user.avatar,
        "city": user.city or "",
        "area": user.area or "",
        "specialty": user.specialty or (profile.specialty if profile else "General Practice"),
        "experience": user.experience_years or 0,
        "experience_years": user.experience_years or 0,
        "bar_association": user.bar_association or (profile.bar_association if profile else None),
        "license_number": user.license_number or (profile.license_number if profile else None),
        "address": (profile.address if profile else None) or user.chamber_address,
        "lat": profile.lat if profile else user.lat, "lng": profile.lng if profile else user.lng,
        "rating": profile.rating if profile else None,
        "is_verified": bool(profile and profile.is_verified and user.is_approved),
        "verification_status": (profile.verification_status if profile and profile.verification_status in {"pending", "verified", "rejected"} else ("verified" if (profile and profile.is_verified and user.is_approved) else "pending")),
        "consultation_fee": float(profile.consultation_fee or 1000) if profile else 1000,
        "is_virtual_available": bool(profile and profile.is_virtual_available),
        "virtual_consult_notes": profile.virtual_consult_notes if profile else None,
        "is_featured_ad_active": bool(profile and profile.is_featured_ad_active and profile.featured_until and profile.featured_until > datetime.utcnow()),
        "featured_until": profile.featured_until.isoformat() if profile and profile.featured_until else None,
    }


def _issue_token(user: User) -> str:
    now = datetime.utcnow()
    payload = {"sub": str(user.id), "iat": now, "exp": now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauth = HTTPException(status_code=401, detail="Session expire ho chuka hai. Dobara login karein!", headers={"WWW-Authenticate": "Bearer"})
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isdigit():
            raise unauth
        user_id = int(subject)
    except (JWTError, ValueError, TypeError):
        raise unauth
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise unauth
    return user


def get_optional_current_user(token: Optional[str] = Depends(oauth2_optional), db: Session = Depends(get_db)) -> Optional[User]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        subject = payload.get("sub")
        if not isinstance(subject, str) or not subject.isdigit():
            return None
        user = db.query(User).filter(User.id == int(subject), User.is_active.is_(True)).first()
        return user
    except (JWTError, ValueError, TypeError):
        return None


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def _require_approved_lawyer(user: User):
    if user.role != "lawyer" or not user.is_approved or not user.lawyer_profile or not user.lawyer_profile.is_verified:
        raise HTTPException(status_code=403, detail="Lawyer account admin verification ke baad hi yeh feature use kar sakta hai.")


def _commit_or_conflict(db: Session, message: str):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)


@app.get("/health")
def health():
    return {"status": "healthy", "service": "lawnexa-api", "timestamp": datetime.utcnow().isoformat() + "Z"}


@app.post("/api/v1/auth/register", status_code=201)
async def register_user(request: Request, db: Session = Depends(get_db)):
    """Accept JSON or URL-encoded/multipart form for older frontends."""
    content_type = request.headers.get("content-type", "")
    try:
        if "application/json" in content_type:
            raw = await request.json()
        else:
            form = await request.form()
            raw = {key: value for key, value in form.items() if not hasattr(value, "filename")}
    except Exception:
        raise HTTPException(status_code=400, detail="Registration data could not be read.")

    for field in ("email", "phone", "city", "area", "specialty", "license_number", "bar_association", "chamber_address", "address"):
        if field in raw:
            raw[field] = _clean_optional(raw[field])
    if not raw.get("email"):
        raw["email"] = None
    for coordinate in ("lat", "lng"):
        if raw.get(coordinate) is None or str(raw.get(coordinate)).strip() == "":
            raw[coordinate] = 0.0
    try:
        payload = UserRegister(**raw)
    except Exception as exc:
        details = getattr(exc, "errors", lambda: [])()
        safe_details = [{"field": ".".join(str(part) for part in item.get("loc", ())), "message": str(item.get("msg", "Invalid value")), "type": str(item.get("type", "validation_error"))} for item in details if isinstance(item, dict)]
        logger.warning("Registration validation failed: %s", safe_details or type(exc).__name__)
        raise HTTPException(status_code=422, detail=safe_details or "Registration details are invalid.")

    if not _clean_optional(payload.phone):
        raise HTTPException(status_code=400, detail="Mobile number zaroori hai!")
    requested_role = payload.role.strip().lower()
    if requested_role in {"lawyer", "advocate", "vakeel"}:
        role = "lawyer"
    elif requested_role in {"client", "user", ""}:
        role = "client"
    else:
        raise HTTPException(status_code=400, detail="Role sirf client ya lawyer ho sakta hai.")

    email = str(payload.email).lower() if payload.email else None
    phone = _normalize_phone(payload.phone)
    if phone and (len(phone) != 11 or not phone.startswith("03") or not phone.isdigit()):
        raise HTTPException(status_code=422, detail="Mobile number 11 digits ka hona chahiye (03XXXXXXXXX).")
    if email and db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="Yeh Email pehle se registered hai!")
    if phone and db.query(User).filter(User.phone == phone).first():
        raise HTTPException(status_code=409, detail="Yeh Mobile Number pehle se registered hai!")

    user = User(
        name=payload.name.strip(), email=email, phone=phone,
        hashed_password=pwd_context.hash(payload.password), role=role,
        is_approved=(role == "client"), is_active=True,
        city=_clean_optional(payload.city) or "Karachi", area=_clean_optional(payload.area) or "Saddar / City Court",
        specialty=_clean_optional(payload.specialty), license_number=_clean_optional(payload.license_number),
        bar_association=_clean_optional(payload.bar_association), experience_years=payload.experience_years or 0,
        chamber_address=_clean_optional(payload.chamber_address) or _clean_optional(payload.address),
        address=_clean_optional(payload.address) or _clean_optional(payload.chamber_address), lat=payload.lat, lng=payload.lng,
    )
    if role == "lawyer":
        # No fake licence/bar identifiers are generated. Admin verification is required before listing/posting.
        user.lawyer_profile = Lawyer(
            name=user.name, specialty=user.specialty or "General Practice",
            address=user.chamber_address or user.address, city=user.city, area=user.area, phone=phone, is_verified=False, verification_status="pending",
            lat=payload.lat, lng=payload.lng, license_number=user.license_number,
            bar_association=user.bar_association, experience_years=user.experience_years or 0,
        )
    db.add(user)
    _commit_or_conflict(db, "Email ya phone pehle se registered hai.")
    db.refresh(user)
    return {
        "message": "Account create ho gaya!" if role == "client" else "Lawyer application submit ho gayi. Admin verification pending hai.",
        "access_token": _issue_token(user), "token_type": "bearer", "role": user.role,
        "user_id": user.id, "name": user.name, "is_approved": bool(user.is_approved),
    }


@app.post("/api/v1/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    identity = form_data.username.strip()
    normalized_phone = _normalize_phone(identity)
    user = db.query(User).filter(or_(User.email == identity.lower(), User.phone == normalized_phone)).first()
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Ghalat Phone/Email ya Password!", headers={"WWW-Authenticate": "Bearer"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled hai. Support se rabta karein.")
    return {"access_token": _issue_token(user), "token_type": "bearer", "role": user.role,
            "user_id": user.id, "name": user.name, "is_approved": bool(user.is_approved)}


@app.get("/api/v1/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return _user_public(current_user, include_private=True)


@app.put("/api/v1/users/profile")
def update_profile(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    data = payload.model_dump(exclude_unset=True)
    user_fields = {"name", "phone", "email", "avatar", "city", "area", "chamber_address", "address", "lat", "lng", "specialty", "license_number", "bar_association", "experience_years"}
    lawyer_fields = {"consultation_fee", "is_virtual_available", "virtual_consult_notes"}
    for key in list(data):
        if isinstance(data[key], str): data[key] = _clean_optional(data[key])
    if data.get("email"): data["email"] = str(data["email"]).lower()
    if data.get("phone") is not None:
        data["phone"] = re.sub(r"[\s()-]", "", str(data["phone"]))
    for key in user_fields:
        if key in data:
            setattr(current_user, key, data[key])
    if current_user.role == "lawyer":
        profile = current_user.lawyer_profile
        if not profile:
            profile = Lawyer(user_id=current_user.id, name=current_user.name, specialty=current_user.specialty or "General Practice")
            current_user.lawyer_profile = profile
        for key in lawyer_fields:
            if key in data: setattr(profile, key, data[key])
        mapping = {"name":"name", "phone":"phone", "specialty":"specialty", "license_number":"license_number", "bar_association":"bar_association", "experience_years":"experience_years", "chamber_address":"address", "address":"address", "city":"city", "area":"area", "lat":"lat", "lng":"lng"}
        for source, target in mapping.items():
            if source in data: setattr(profile, target, data[source])
        if profile.is_virtual_available and (profile.consultation_fee is None or profile.consultation_fee <= 0):
            raise HTTPException(status_code=422, detail="Virtual consultation ON karne ke liye valid fee enter karein.")
    # A user cannot enable ad-free or featured status by editing their own profile.
    if "is_ad_free_enabled" in data or "is_featured_ad_active" in data:
        if current_user.role != "admin": data.pop("is_ad_free_enabled", None)
    _commit_or_conflict(db, "Email ya phone kisi aur account ke saath registered hai.")
    db.refresh(current_user)
    return {"message":"Profile updated!", "user":_user_public(current_user, include_private=True), "lawyer":_lawyer_public(current_user) if current_user.role == "lawyer" else None}


@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(
    city: Optional[str] = None, area: Optional[str] = None,
    client_lat: Optional[float] = None, client_lng: Optional[float] = None,
    radius_km: Optional[float] = Query(default=None, gt=0, le=1000),
    skip: int = Query(default=0, ge=0), limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    # New lawyer profiles appear in the live directory immediately. Their
    # verification status remains explicit; unverified profiles cannot accept bookings/posts.
    query = db.query(User).options(joinedload(User.lawyer_profile)).filter(
        User.role == "lawyer", User.is_active.is_(True)
    )
    if city:
        query = query.filter(User.city.ilike(f"%{city.strip()}%"))
    if area:
        query = query.filter(User.area.ilike(f"%{area.strip()}%"))
    users = query.all()
    results = []
    for user in users:
        item = _lawyer_public(user)
        if client_lat is not None and client_lng is not None and radius_km is not None:
            profile = user.lawyer_profile
            if not profile or profile.lat is None or profile.lng is None:
                continue
            from geo_engine import calculate_distance
            distance = calculate_distance(client_lat, client_lng, profile.lat, profile.lng)
            if distance > radius_km:
                continue
            item["distance_km"] = round(distance, 2)
        results.append(item)
    results.sort(key=lambda x: (not x.get("is_featured_ad_active", False), x.get("distance_km", float("inf")), (x.get("name") or "").lower()))
    return results[skip:skip + limit]


@app.get("/api/v1/admin/lawyers/pending")
def pending_lawyers(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).options(joinedload(User.lawyer_profile)).filter(User.role == "lawyer", User.is_approved.is_(False)).order_by(User.created_at.asc()).all()
    return [{"id": u.lawyer_profile.id if u.lawyer_profile else u.id, "user_id": u.id, **_lawyer_public(u)} for u in users]


@app.post("/api/v1/admin/lawyers/{lawyer_id}/reject")
def reject_lawyer(lawyer_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    lawyer = db.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
    if not lawyer: raise HTTPException(status_code=404, detail="Lawyer application not found.")
    user = db.query(User).filter(User.id == lawyer.user_id).first()
    if not user: raise HTTPException(status_code=404, detail="Lawyer account not found.")
    user.is_approved = False; lawyer.is_verified = False; lawyer.verification_status = "rejected"
    db.commit()
    return {"message": "Lawyer application rejected.", "user_id": user.id, "lawyer_id": lawyer.id, "verification_status": "rejected"}


@app.post("/api/v1/admin/lawyers/{lawyer_id}/approve")
def approve_lawyer(lawyer_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    lawyer = db.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer application not found.")
    user = db.query(User).filter(User.id == lawyer.user_id).first()
    if not user or user.role != "lawyer":
        raise HTTPException(status_code=404, detail="Lawyer account not found.")
    user.is_approved = True
    lawyer.is_verified = True
    lawyer.verification_status = "verified"
    db.commit()
    return {"message": "Lawyer approved successfully.", "user_id": user.id, "lawyer_id": lawyer.id}


async def _parse_model(request: Request, model_type):
    ctype = request.headers.get("content-type", "")
    try:
        if "application/json" in ctype:
            data = await request.json()
        else:
            form = await request.form()
            data = dict(form)
        return model_type(**data)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=422, detail="Request data is invalid.")


def _post_json(post: Post, current_user_id: Optional[int] = None) -> dict:
    user = post.lawyer.user
    liked_by_me = False
    if current_user_id is not None:
        liked_by_me = any(like.user_id == current_user_id for like in post.likes)
    return {"id": post.id, "lawyer_id": post.lawyer_id, "user_id": user.id,
            "name": user.name, "avatar": user.avatar, "bar_association": post.bar_association,
            "title": post.title, "category": post.category, "content": post.content,
            "media_url": post.media_url, "media_type": post.media_type,
            "likes": len(post.likes), "liked": liked_by_me,
            "is_promoted": bool(post.is_promoted and post.promoted_until and post.promoted_until > datetime.utcnow()),
            "created_at": post.created_at.isoformat() if post.created_at else None}


@app.post("/api/v1/media/upload", status_code=201)
async def upload_media(request: Request, file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    """Authenticated upload for chat attachments and lawyer post media; local storage unless CDN configured."""
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
                     "video/mp4": ".mp4", "video/webm": ".webm", "application/pdf": ".pdf",
                     "application/msword": ".doc", "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                     "text/plain": ".txt", "audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mpeg": ".mp3", "audio/mp4": ".m4a"}
    content_type = (file.content_type or "application/octet-stream").lower()
    extension = allowed_types.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Unsupported media type.")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Media file 10 MB se chhoti honi chahiye.")
    if extension == ".jpg" and not raw.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="Invalid JPEG file.")
    if extension == ".png" and not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="Invalid PNG file.")
    if extension == ".webp" and not (raw.startswith(b"RIFF") and raw[8:12] == b"WEBP") and content_type == "image/webp":
        raise HTTPException(status_code=415, detail="Invalid WEBP file.")
    filename = f"{uuid4().hex}{extension}"
    (UPLOAD_DIR / filename).write_bytes(raw)
    base_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/") or str(request.base_url).rstrip("/")
    url = f"{base_url}/uploads/{filename}"
    media_type = "image" if content_type.startswith("image/") else "video" if content_type.startswith("video/") else "audio" if content_type.startswith("audio/") else "document"
    return {"url": url, "media_url": url, "media_type": media_type, "content_type": content_type, "size": len(raw), "filename": file.filename or filename}


@app.post("/api/v1/posts", status_code=201)
async def create_post(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approved_lawyer(current_user)
    payload = await _parse_model(request, PostCreate)
    if not current_user.bar_association and not payload.bar_association.strip():
        raise HTTPException(status_code=400, detail="Bar association required.")
    post = Post(lawyer_id=current_user.lawyer_profile.id,
                bar_association=(current_user.bar_association or payload.bar_association).strip(),
                title=payload.title.strip(), category=payload.category.strip(), content=payload.content.strip(),
                media_url=payload.media_url, media_type=payload.media_type)
    db.add(post)
    db.commit()
    db.refresh(post)
    return _post_json(post, current_user.id)


@app.get("/api/v1/posts")
def get_posts(bar_association: Optional[str] = None, skip: int = 0, limit: int = 30,
              current_user: Optional[User] = Depends(get_optional_current_user), db: Session = Depends(get_db)):
    # Public feed contains posts only from approved lawyers; never return raw ORM objects.
    query = db.query(Post).join(Lawyer).join(User).options(joinedload(Post.lawyer).joinedload(Lawyer.user), joinedload(Post.likes)).filter(User.is_approved.is_(True), Lawyer.is_verified.is_(True))
    if bar_association:
        query = query.filter(Post.bar_association.ilike(f"%{bar_association.strip()}%"))
    posts = query.order_by(Post.is_promoted.desc(), Post.created_at.desc()).offset(max(0, skip)).limit(min(max(1, limit), 100)).all()
    return [_post_json(post, current_user.id if current_user else None) for post in posts]


@app.post("/api/v1/posts/{post_id}/like")
def like_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    post = db.query(Post).join(Lawyer).join(User).filter(Post.id == post_id, User.is_approved.is_(True), Lawyer.is_verified.is_(True)).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found.")
    existing = db.query(Like).filter(Like.post_id == post_id, Like.user_id == current_user.id).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"message": "Like removed.", "liked": False}
    db.add(Like(post_id=post_id, user_id=current_user.id))
    _commit_or_conflict(db, "Post already liked.")
    return {"message": "Post liked.", "liked": True}


@app.post("/api/v1/chat/send", status_code=201)
def send_chat_message(payload: ChatCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.receiver_id == current_user.id:
        raise HTTPException(status_code=400, detail="Aap khud ko message nahi bhej sakte.")
    if not payload.message.strip() and not payload.media_url:
        raise HTTPException(status_code=422, detail="Message ya attachment zaroori hai.")
    receiver = db.query(User).filter(User.id == payload.receiver_id, User.is_active.is_(True)).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found.")
    if payload.quote_amount is not None:
        _require_approved_lawyer(current_user)
    message = ChatMessage(sender_id=current_user.id, receiver_id=receiver.id,
                          message=payload.message.strip(), quote_amount=payload.quote_amount,
                          media_url=payload.media_url, media_type=payload.media_type,
                          quote_status="pending" if payload.quote_amount is not None else "none")
    db.add(message)
    db.commit()
    db.refresh(message)
    return {"chat_id": message.id, "id": message.id, "sender_id": message.sender_id,
            "receiver_id": message.receiver_id, "message": message.message,
            "media_url": message.media_url, "media_type": message.media_type,
            "quote_amount": message.quote_amount, "quote_status": message.quote_status,
            "timestamp": message.timestamp.isoformat()}


@app.get("/api/v1/chat/history/{other_user_id}")
def chat_history(other_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    other = db.query(User).filter(User.id == other_user_id).first()
    if not other:
        raise HTTPException(status_code=404, detail="User not found.")
    messages = db.query(ChatMessage).filter(or_(
        (ChatMessage.sender_id == current_user.id) & (ChatMessage.receiver_id == other_user_id),
        (ChatMessage.sender_id == other_user_id) & (ChatMessage.receiver_id == current_user.id),
    )).order_by(ChatMessage.timestamp.asc(), ChatMessage.id.asc()).all()
    return [{"id": m.id, "chat_id": m.id, "sender_id": m.sender_id, "receiver_id": m.receiver_id,
             "message": m.message, "media_url": m.media_url, "media_type": m.media_type,
             "quote_amount": m.quote_amount, "quote_status": m.quote_status,
             "timestamp": m.timestamp.isoformat()} for m in messages]


@app.post("/api/v1/chat/quote/{message_id}/respond")
def respond_to_quote(message_id: int, action: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if action not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Action accepted ya rejected honi chahiye.")
    message = db.query(ChatMessage).filter(ChatMessage.id == message_id).first()
    if not message:
        raise HTTPException(status_code=404, detail="Quotation not found.")
    if message.receiver_id != current_user.id:
        raise HTTPException(status_code=403, detail="Sirf quotation receive karne wala user jawab de sakta hai.")
    if message.quote_amount is None or message.quote_status != "pending":
        raise HTTPException(status_code=409, detail="Yeh quotation ab response ke liye available nahi hai.")
    message.quote_status = action
    db.commit()
    return {"message": f"Quotation {action}.", "quote_status": action}


@app.post("/api/v1/bookings", status_code=201)
def create_booking(payload: BookingCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "client":
        raise HTTPException(status_code=403, detail="Sirf client consultation request bhej sakta hai.")
    lawyer = db.query(Lawyer).join(User).filter(Lawyer.id == payload.lawyer_id, User.role == "lawyer", User.is_approved.is_(True), Lawyer.is_verified.is_(True)).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Verified lawyer not found.")
    if (payload.location or "").lower().startswith(("virtual", "online")) and not lawyer.is_virtual_available:
        raise HTTPException(status_code=409, detail="Yeh lawyer virtual consultation offer nahi karta. Direct chat ya chamber visit karein.")
    booking = Appointment(client_id=current_user.id, lawyer_id=lawyer.id, booking_date=payload.booking_date,
                          time_slot=payload.time_slot, location=_clean_optional(payload.location),
                          case_summary=payload.case_summary.strip())
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return {"id": booking.id, "status": booking.status, "lawyer_id": lawyer.id, "booking_date": booking.booking_date,
            "time_slot": booking.time_slot, "location": booking.location, "case_summary": booking.case_summary}


@app.get("/api/v1/bookings/mine")
def my_bookings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    query = db.query(Appointment).options(joinedload(Appointment.client), joinedload(Appointment.lawyer).joinedload(Lawyer.user))
    if current_user.role == "lawyer" and current_user.lawyer_profile:
        query = query.filter(Appointment.lawyer_id == current_user.lawyer_profile.id)
    else:
        query = query.filter(Appointment.client_id == current_user.id)
    results = []
    for a in query.order_by(Appointment.id.desc()).all():
        lawyer_user = a.lawyer.user if a.lawyer else None
        results.append({"id": a.id, "client_id": a.client_id, "lawyer_id": a.lawyer_id,
            "clientName": a.client.name if a.client else "Client",
            "lawyerName": lawyer_user.name if lawyer_user else "Lawyer",
            "date": a.booking_date, "time": a.time_slot, "location": a.location or "Not specified",
            "summary": a.case_summary, "booking_date": a.booking_date, "time_slot": a.time_slot,
            "case_summary": a.case_summary, "status": a.status.title()})
    return results


@app.patch("/api/v1/bookings/{booking_id}")
def update_booking_status(booking_id: int, action: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if action not in {"accepted", "rejected", "cancelled", "completed"}:
        raise HTTPException(status_code=400, detail="Invalid booking status.")
    booking = db.query(Appointment).join(Lawyer).filter(Appointment.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    is_client = booking.client_id == current_user.id
    is_lawyer = bool(current_user.lawyer_profile and booking.lawyer_id == current_user.lawyer_profile.id)
    if not is_client and not is_lawyer:
        raise HTTPException(status_code=403, detail="Booking access denied.")
    if action in {"accepted", "rejected", "completed"} and not is_lawyer:
        raise HTTPException(status_code=403, detail="Sirf assigned lawyer yeh status set kar sakta hai.")
    if action == "cancelled" and not is_client:
        raise HTTPException(status_code=403, detail="Sirf client booking cancel kar sakta hai.")
    booking.status = action
    db.commit()
    return {"id": booking.id, "status": booking.status}


def _grounding_sources(response) -> list[dict]:
    """Extract URLs supplied by Gemini Google Search grounding metadata."""
    sources = []
    seen = set()
    try:
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            metadata = getattr(candidate, "grounding_metadata", None)
            for chunk in (getattr(metadata, "grounding_chunks", None) or []):
                web_source = getattr(chunk, "web", None)
                uri = getattr(web_source, "uri", None)
                title = getattr(web_source, "title", None) or uri
                if uri and uri.startswith(("https://", "http://")) and uri not in seen:
                    sources.append({"title": title, "url": uri})
                    seen.add(uri)
    except Exception:
        logger.warning("Could not parse grounding sources from AI response.")
    return sources[:12]


@app.post("/api/ai/analyze-fir")
async def analyze_fir(text: str = Form(default=""), file: Optional[UploadFile] = File(default=None),
                      response_language: str = Form(default="same"),
                      current_user: User = Depends(get_current_user)):
    text = (text or "").strip()
    file_part = None
    if file and file.filename:
        allowed = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
        if file.content_type not in allowed:
            raise HTTPException(status_code=415, detail="FIR file PDF, JPG, PNG ya WEBP honi chahiye.")
        unsafe_name = re.search(r"(resume|\bcv\b|invoice|profile)", file.filename or "", re.I)
        if unsafe_name:
            raise HTTPException(status_code=415, detail="Ghalt File! Barah-e-Karam Sirf FIR ki Tasveer ya PDF Upload Karein.")
        file_bytes = await file.read(10 * 1024 * 1024 + 1)
        if len(file_bytes) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="Ghalt File! Barah-e-Karam Sirf FIR ki Tasveer ya PDF Upload Karein.")
        if file_bytes:
            signature_ok = ((file.content_type == "application/pdf" and file_bytes.startswith(b"%PDF-")) or
                            (file.content_type == "image/jpeg" and file_bytes.startswith(b"\xff\xd8\xff")) or
                            (file.content_type == "image/png" and file_bytes.startswith(b"\x89PNG\r\n\x1a\n")) or
                            (file.content_type == "image/webp" and len(file_bytes) > 12 and file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"))
            if not signature_ok:
                raise HTTPException(status_code=415, detail="File ka actual format supported PDF/JPG/PNG/WEBP se match nahi karta.")
            file_part = (file_bytes, file.content_type)
    if not text and not file_part:
        raise HTTPException(status_code=400, detail="FIR ka text paste karein ya supported file upload karein.")
    if response_language not in {"same", "ur", "roman_ur", "en"}:
        raise HTTPException(status_code=400, detail="Language option invalid hai.")
    # Safe local demo fallback: detects explicit PPC section numbers, but never asserts a bail outcome.
    if not GEMINI_API_KEY:
        source_text = text
        if file_part:
            source_text += " " + (file.filename or "")
        matches = list(dict.fromkeys(re.findall(r"(?:section|sec\.?|s\.)\s*(\d{1,4})\s*(?:PPC|Pakistan Penal Code)?|\b(\d{2,4})\s*PPC\b", source_text, re.I)))
        numbers = [next((g for g in tup if g), "") for tup in matches]
        names = {144: "Unlawful assembly / public-order restriction", 302: "Qatl-i-amd (murder) allegation", 420: "Cheating and dishonestly inducing delivery of property"}
        sections = [f"PPC {n} ({names.get(int(n), 'section detected; legal meaning requires verification')})" for n in numbers]
        if not sections and not text.strip():
            raise HTTPException(status_code=400, detail="FIR ka text paste karein. Local demo mode mein image/PDF OCR available nahi hai; Gemini key configure karein.")
        return {"analysis": "Local demo mode — yeh FIR ka verified legal analysis nahi hai.\n\nSections detected: " + (", ".join(sections) if sections else "Koi explicit PPC section number detect nahi hua.") + "\n\nPlease upload/read the FIR text and have the relevant law and facts checked by a Pakistan-licensed lawyer.",
                "sections_found": sections, "bail_status": "Not determined — verify from the FIR facts and applicable law", "is_ai_generated": False, "mock_mode": True, "sources": [], "grounded_with_google_search": False,
                "disclaimer": "Automated local demo only, not formal legal advice. No bail outcome is guaranteed."}
    language_instruction = {"same": "Reply in the same language/script as the user-provided FIR text when practical.", "ur": "Respond in clear Urdu script.", "roman_ur": "Respond in simple Roman Urdu.", "en": "Respond in English."}[response_language]
    prompt = ("First determine whether the supplied file/text is actually a police First Information Report (FIR) or a clear extract of one. If it is an unrelated document (such as CV, ID card, photo, invoice, or general letter), do not analyze it as an FIR; politely ask the user to provide FIR text or an FIR image/PDF. If it is unreadable, say so. Analyze the supplied FIR for a Pakistan legal user. Do not invent facts, legal citations, sections, "
              "or predict outcomes. Clearly separate information copied from the supplied FIR from general observations. "
              "Use Google Search grounding to research current Pakistan statutes, court rules and official decisions; prioritize Pakistan Code, "
              "official Supreme Court/high court websites and other primary sources. Distinguish actual retrieved sources from assumptions. "
              "Provide: (1) identifiable offences/sections only if explicitly stated or confidently readable, (2) relevant current law with source-backed citations, "
              "(3) key factual gaps, (4) questions a Pakistan-licensed lawyer should check, and (5) urgent procedural considerations. "
              "Never invent citations, cases or sections. State that this is preliminary information and not legal advice. "
              "If the image/text is unclear or no reliable source is found, say so. " + language_instruction + "\n\n" + text)
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=GEMINI_API_KEY)
        contents = [prompt]
        if file_part:
            contents.append(types.Part.from_bytes(data=file_part[0], mime_type=file_part[1]))
        config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
        response = client.models.generate_content(model=GEMINI_MODEL, contents=contents, config=config)
        result = (getattr(response, "text", None) or "").strip()
        if not result:
            raise HTTPException(status_code=503, detail="AI provider ne readable analysis return nahi ki.")
        sources = _grounding_sources(response)
        return {"analysis": result, "is_ai_generated": True, "sources": sources,
                "grounded_with_google_search": bool(sources),
                "disclaimer": "AI analysis is preliminary; verify every source and legal proposition with a Pakistan-licensed lawyer."}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("FIR AI provider failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="AI analysis provider temporarily unavailable. Koi mock result use nahi kiya gaya.")


@app.post("/api/ai/generate-doc")
def generate_doc(payload: DocumentRequest, current_user: User = Depends(get_current_user)):
    if current_user.role != "lawyer":
        raise HTTPException(status_code=403, detail="Document Generator sirf lawyer accounts ke liye hai.")
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Real AI document generation configured nahi hai. Server par GEMINI_API_KEY set karein; koi sample draft return nahi kiya gaya.")
    if payload.doc_type.lower() == "affidavit":
        parties = f"Deponent name: {payload.party1}\nFather name: {payload.father_name}\nCNIC: {payload.cnic}\nResidence address: {payload.residence_address}\n"
    elif payload.doc_type.lower() == "bail petition":
        parties = f"Accused name: {payload.party1}\nComplainant name: {payload.party2}\nFIR number / police station: {payload.fir_number}\nCourt name: {payload.court}\n"
    else:
        parties = f"First party: {payload.party1}\nSecond party: {payload.party2}\nLocation/court: {payload.court}\n"
    prompt = (
        "Create a clearly labelled DRAFT legal document for Pakistan; do not invent facts, citations, "
        "statutes, or claim legal compliance is verified. Add a prominent notice that a Pakistan-licensed "
        "lawyer must review it before use.\n"
        f"Document type: {payload.doc_type}\n{parties}"
        f"Purpose/details: {payload.purpose}\n"
        "Do not add party fields that are not applicable to this document type. Clearly mark missing facts as [TO BE PROVIDED]."
    )
    if GEMINI_API_KEY:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=GEMINI_API_KEY)
            config = types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())])
            response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt, config=config)
            generated = (getattr(response, "text", None) or "").strip()
            if generated:
                return {"draft": generated, "is_ai_generated": True, "sources": _grounding_sources(response),
                        "disclaimer": "AI draft — a lawyer must review it. Legal validity and applicability are not verified."}
        except Exception as exc:
            logger.warning("Document AI provider failed: %s", type(exc).__name__)
            raise HTTPException(status_code=503, detail="AI document service temporarily unavailable. Please try later.")
    raise HTTPException(status_code=503, detail="AI document provider returned no draft. No mock draft was generated.")



# ------------------------- Extended LawNexa modules -------------------------
class QuestionCreate(BaseModel):
    question_title: str = Field(min_length=5, max_length=250)
    category: str = Field(default="General Legal", max_length=100)
    full_details: str = Field(min_length=10, max_length=10000)
    is_anonymous: bool = False

class AnswerCreate(BaseModel):
    answer_text: str = Field(min_length=10, max_length=10000)

class CaseCreate(BaseModel):
    court_name: str = Field(min_length=2, max_length=200)
    bench_no: Optional[str] = Field(default=None, max_length=80)
    case_title: str = Field(min_length=2, max_length=250)
    case_no: str = Field(min_length=1, max_length=120)
    client_name: Optional[str] = Field(default=None, max_length=160)
    client_phone: Optional[str] = Field(default=None, max_length=32)
    hearing_date: str = Field(min_length=8, max_length=20)
    status: str = "SCHEDULED"
    notes: Optional[str] = Field(default=None, max_length=5000)

class CorporateCreate(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    plan_type: str = "BASIC_STARTUP"

class CorporateRequestCreate(BaseModel):
    request_type: str = "CONTRACT_REVIEW"
    description: str = Field(min_length=10, max_length=10000)
    document_url: Optional[str] = Field(default=None, max_length=500)

class CampaignCreate(BaseModel):
    bar_association: str = Field(min_length=2, max_length=200)
    position_title: str = Field(min_length=2, max_length=120)
    manifesto_text: str = Field(min_length=10, max_length=10000)
    campaign_banner_url: Optional[str] = Field(default=None, max_length=500)

class CheckoutCreate(BaseModel):
    booking_id: int = Field(gt=0)
    payment_method: str = "Wallet"

class WithdrawCreate(BaseModel):
    amount: float = Field(gt=0, le=100000000)
    payout_method: str = Field(min_length=2, max_length=40)
    account_details: str = Field(min_length=5, max_length=255)

class InviteCreate(BaseModel):
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(default=None, max_length=32)
    role: str = "lawyer"


def _wallet_for(db: Session, user_id: int) -> Wallet:
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        wallet = Wallet(user_id=user_id, balance=0, pending_escrow=0, total_withdrawn=0)
        db.add(wallet); db.flush()
    return wallet

@app.get("/api/v1/admin/overview")
def admin_overview(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {"users": db.query(User).count(), "lawyers_pending": db.query(User).filter(User.role == "lawyer", User.is_approved.is_(False)).count(),
            "corporate_subscriptions": db.query(CorporateSubscription).count(), "questions_open": db.query(PublicQuestion).filter(PublicQuestion.status == "OPEN").count(),
            "withdrawals_pending": db.query(WalletWithdrawal).filter(WalletWithdrawal.status == "REQUESTED").count()}

@app.get("/api/v1/admin/users")
def admin_users(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "phone": u.phone, "role": u.role, "city": u.city,
             "is_approved": u.is_approved, "is_active": u.is_active} for u in db.query(User).order_by(User.created_at.desc()).limit(500).all()]

@app.post("/api/v1/admin/invites", status_code=201)
def create_invite(payload: InviteCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if not payload.email and not _clean_optional(payload.phone):
        raise HTTPException(status_code=400, detail="Invite ke liye email ya phone zaroori hai.")
    if payload.role not in {"lawyer", "corporate"}:
        raise HTTPException(status_code=400, detail="Invite role lawyer ya corporate hona chahiye.")
    token = secrets.token_urlsafe(32)
    invite = Invite(email=str(payload.email).lower() if payload.email else None, phone=_clean_optional(payload.phone), role=payload.role,
                    token=token, invited_by=admin.id, expires_at=datetime.utcnow()+timedelta(days=7))
    db.add(invite); db.add(AuditLog(actor_user_id=admin.id, action="invite_created", target_type="invite", details=f"role={payload.role}")); db.commit(); db.refresh(invite)
    # Sending email/SMS needs a configured provider; this endpoint returns a single-use token for admin to share securely.
    return {"id": invite.id, "role": invite.role, "expires_at": invite.expires_at.isoformat(), "invite_token": token, "delivery": "manual_share_until_email_sms_provider_configured"}

@app.get("/api/v1/qa/questions")
def list_questions(category: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(PublicQuestion)
    if category: query = query.filter(PublicQuestion.category == category)
    questions = query.order_by(PublicQuestion.created_at.desc()).limit(100).all()
    output=[]
    for q in questions:
        output.append({"id": q.id, "question_title": q.question_title, "category": q.category, "full_details": q.full_details,
          "is_anonymous": q.is_anonymous, "author": "Anonymous" if q.is_anonymous else (db.query(User.name).filter(User.id == q.client_id).scalar() or "Client"),
          "status": q.status, "created_at": q.created_at.isoformat(), "answers":[{"id": a.id, "lawyer_id": a.lawyer_id,
          "lawyer_name": db.query(User.name).filter(User.id == a.lawyer_id).scalar() or "Advocate", "answer_text": a.answer_text,
          "upvotes_count": a.upvotes_count, "created_at": a.created_at.isoformat()} for a in q.answers]})
    return output

@app.post("/api/v1/qa/questions", status_code=201)
def create_question(payload: QuestionCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "client": raise HTTPException(status_code=403, detail="Public legal question sirf client account submit kar sakta hai.")
    q=PublicQuestion(client_id=user.id, question_title=payload.question_title.strip(), category=payload.category.strip(), full_details=payload.full_details.strip(), is_anonymous=payload.is_anonymous)
    db.add(q); db.commit(); db.refresh(q); return {"id":q.id,"status":q.status}

@app.post("/api/v1/qa/questions/{question_id}/answers", status_code=201)
def answer_question(question_id: int, payload: AnswerCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approved_lawyer(user)
    q=db.query(PublicQuestion).filter(PublicQuestion.id==question_id).first()
    if not q: raise HTTPException(status_code=404, detail="Question not found.")
    a=QuestionAnswer(question_id=q.id, lawyer_id=user.id, answer_text=payload.answer_text.strip()); q.status="ANSWERED"
    db.add(a); db.commit(); db.refresh(a); return {"id":a.id,"status":q.status}

@app.get("/api/v1/cases")
def list_cases(date: Optional[str] = None, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "lawyer": raise HTTPException(status_code=403, detail="Case tracker sirf lawyers ke liye hai.")
    q=db.query(CaseTracker).filter(CaseTracker.lawyer_id==user.id)
    if date: q=q.filter(CaseTracker.hearing_date==date)
    return [{c.name:getattr(row,c.name) for c in CaseTracker.__table__.columns} for row in q.order_by(CaseTracker.hearing_date.asc()).all()]

@app.post("/api/v1/cases", status_code=201)
def create_case(payload: CaseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "lawyer": raise HTTPException(status_code=403, detail="Case tracker sirf lawyers ke liye hai.")
    if payload.status not in {"SCHEDULED","ADJOURNED","DECIDED","DISPOSED"}: raise HTTPException(status_code=400, detail="Invalid case status.")
    row=CaseTracker(lawyer_id=user.id, **payload.model_dump()); db.add(row); db.commit(); db.refresh(row); return {"id":row.id,"status":row.status}

@app.put("/api/v1/cases/{case_id}")
def update_case(case_id: int, payload: CaseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row=db.query(CaseTracker).filter(CaseTracker.id==case_id, CaseTracker.lawyer_id==user.id).first()
    if not row: raise HTTPException(status_code=404, detail="Case not found.")
    for k,v in payload.model_dump().items(): setattr(row,k,v)
    db.commit(); return {"id":row.id,"status":row.status}

@app.delete("/api/v1/cases/{case_id}")
def delete_case(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row=db.query(CaseTracker).filter(CaseTracker.id==case_id, CaseTracker.lawyer_id==user.id).first()
    if not row: raise HTTPException(status_code=404, detail="Case not found.")
    db.delete(row); db.commit(); return {"deleted":True}

@app.get("/api/v1/bar/campaigns")
def list_campaigns(bar_association: Optional[str] = None, db: Session = Depends(get_db)):
    q=db.query(BarElectionCampaign)
    if bar_association: q=q.filter(BarElectionCampaign.bar_association.ilike(f"%{bar_association.strip()}%"))
    return [{"id":c.id,"candidate_lawyer_id":c.candidate_lawyer_id,"candidate_name":db.query(User.name).filter(User.id==c.candidate_lawyer_id).scalar() or "Advocate",
      "bar_association":c.bar_association,"position_title":c.position_title,"manifesto_text":c.manifesto_text,"campaign_banner_url":c.campaign_banner_url,"votes_count":c.votes_count,"created_at":c.created_at.isoformat()} for c in q.order_by(BarElectionCampaign.created_at.desc()).limit(100).all()]

@app.post("/api/v1/bar/campaigns", status_code=201)
def create_campaign(payload: CampaignCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _require_approved_lawyer(user)
    campaign=BarElectionCampaign(candidate_lawyer_id=user.id, **payload.model_dump()); db.add(campaign); db.commit(); db.refresh(campaign); return {"id":campaign.id}

@app.get("/api/v1/lawyers/analytics")
def lawyer_analytics(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role != "lawyer": raise HTTPException(status_code=403, detail="Lawyer analytics only.")
    profile=user.lawyer_profile
    bookings=db.query(Appointment).filter(Appointment.lawyer_id==profile.id).all() if profile else []
    earnings=db.query(EscrowTransaction).filter(EscrowTransaction.lawyer_id==user.id, EscrowTransaction.status=="RELEASED_TO_LAWYER").all()
    return {"profile_views_count":0,"search_impressions":0,"total_bookings":len(bookings),"total_earnings":round(sum(x.net_lawyer_payout for x in earnings),2),"avg_rating":profile.rating if profile and profile.rating else 0,"response_time_mins":0,"note":"Views, impressions and response time require event tracking to be enabled; no invented metrics are shown."}

@app.get("/api/v1/wallet/balance")
def wallet_balance(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    w=_wallet_for(db,user.id); db.commit()
    tx=db.query(EscrowTransaction).filter(or_(EscrowTransaction.client_id==user.id,EscrowTransaction.lawyer_id==user.id)).order_by(EscrowTransaction.created_at.desc()).limit(50).all()
    return {"balance":w.balance,"pending_escrow":w.pending_escrow,"total_withdrawn":w.total_withdrawn,"transactions":[{"ref":t.transaction_ref,"amount":t.gross_amount,"status":t.status,"created_at":t.created_at.isoformat()} for t in tx]}

@app.post("/api/v1/payments/checkout", status_code=201)
def checkout(payload: CheckoutCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking=db.query(Appointment).filter(Appointment.id==payload.booking_id, Appointment.client_id==user.id).first()
    if not booking: raise HTTPException(status_code=404, detail="Client booking not found.")
    lawyer=db.query(Lawyer).filter(Lawyer.id==booking.lawyer_id).first()
    if not lawyer or not lawyer.is_virtual_available: raise HTTPException(status_code=409, detail="Virtual consultation available nahi hai.")
    fee=float(lawyer.consultation_fee or 1000); method=payload.payment_method
    if method != "Wallet":
        raise HTTPException(status_code=503, detail=f"{method} gateway abhi configured nahi hai. Real JazzCash/EasyPaisa/card checkout ke liye merchant credentials aur webhook verification zaroori hain.")
    wallet=_wallet_for(db,user.id)
    if wallet.balance < fee: raise HTTPException(status_code=402, detail="Wallet balance kam hai. Payment gateway setup hone tak external checkout available nahi.")
    lawyer_user_id=lawyer.user_id; commission=round(fee*0.15,2); net=round(fee-commission,2)
    wallet.balance-=fee; wallet.pending_escrow+=fee
    ref="LNX-"+secrets.token_hex(12).upper()
    tx=EscrowTransaction(booking_id=booking.id,client_id=user.id,lawyer_id=lawyer_user_id,gross_amount=fee,platform_commission=0.15,net_lawyer_payout=net,payment_gateway="Wallet",transaction_ref=ref,status="HELD_IN_ESCROW")
    booking.status="confirmed_and_paid"; db.add(tx); db.commit(); return {"transaction_ref":ref,"status":tx.status,"gross_amount":fee,"platform_commission":commission,"net_lawyer_payout":net}

@app.post("/api/v1/payments/release/{booking_id}")
def release_payment(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tx=db.query(EscrowTransaction).filter(EscrowTransaction.booking_id==booking_id,EscrowTransaction.status=="HELD_IN_ESCROW").first()
    if not tx: raise HTTPException(status_code=404, detail="Held escrow not found.")
    booking=db.query(Appointment).filter(Appointment.id==booking_id).first()
    if user.role!="admin" and not (user.id==tx.client_id and booking and booking.status == "completed"):
        raise HTTPException(status_code=403, detail="Consultation ko assigned lawyer completed mark kare, phir client/admin escrow release kar sakta hai.")
    client_wallet=_wallet_for(db,tx.client_id); client_wallet.pending_escrow=max(0,client_wallet.pending_escrow-tx.gross_amount)
    lawyer_wallet=_wallet_for(db,tx.lawyer_id); lawyer_wallet.balance+=tx.net_lawyer_payout
    tx.status="RELEASED_TO_LAWYER"
    if booking: booking.status="completed"
    db.commit(); return {"status":tx.status,"net_lawyer_payout":tx.net_lawyer_payout}

@app.post("/api/v1/payments/refund/{booking_id}")
def refund_payment(booking_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tx=db.query(EscrowTransaction).filter(EscrowTransaction.booking_id==booking_id,EscrowTransaction.status=="HELD_IN_ESCROW").first()
    if not tx: raise HTTPException(status_code=404, detail="Held escrow not found.")
    booking=db.query(Appointment).filter(Appointment.id==booking_id).first()
    if user.role!="admin" and not (user.id==tx.lawyer_id and booking and booking.status in {"cancelled","rejected"}): raise HTTPException(status_code=403, detail="Refund approval required.")
    w=_wallet_for(db,tx.client_id); w.pending_escrow=max(0,w.pending_escrow-tx.gross_amount); w.balance+=tx.gross_amount
    tx.status="REFUNDED_TO_CLIENT"; db.commit(); return {"status":tx.status}

@app.post("/api/v1/wallet/withdraw", status_code=201)
def request_withdrawal(payload: WithdrawCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role!="lawyer": raise HTTPException(status_code=403, detail="Withdrawals sirf lawyer wallets ke liye hain.")
    w=_wallet_for(db,user.id)
    if w.balance < payload.amount: raise HTTPException(status_code=400, detail="Available balance kam hai.")
    w.balance-=payload.amount
    row=WalletWithdrawal(user_id=user.id,amount=payload.amount,payout_method=payload.payout_method,account_details=payload.account_details,status="REQUESTED")
    db.add(row); db.commit(); db.refresh(row); return {"id":row.id,"status":row.status,"message":"Withdrawal request submit ho gayi; admin payout review karega."}

@app.post("/api/v1/subscriptions/subscribe", status_code=201)
def create_subscription(payload: CorporateCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.plan_type not in {"BASIC_STARTUP","BUSINESS_PRO","ENTERPRISE_CUSTOM"}: raise HTTPException(status_code=400, detail="Invalid corporate plan.")
    plans={"BASIC_STARTUP":(15000,5),"BUSINESS_PRO":(45000,20),"ENTERPRISE_CUSTOM":(0,100)}
    price,limit=plans[payload.plan_type]
    row=CorporateSubscription(company_name=payload.company_name.strip(),admin_user_id=user.id,plan_type=payload.plan_type,monthly_price=price,contracts_limit=limit,expires_at=datetime.utcnow()+timedelta(days=30))
    db.add(row); db.commit(); db.refresh(row); return {"id":row.id,"company_name":row.company_name,"plan_type":row.plan_type,"monthly_price":price,"contracts_limit":limit,"billing_note":"Payment collection must be completed through a configured gateway before treating this as paid."}

@app.get("/api/v1/subscriptions/my-plan")
def my_plan(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows=db.query(CorporateSubscription).filter(CorporateSubscription.admin_user_id==user.id,CorporateSubscription.status=="ACTIVE").order_by(CorporateSubscription.created_at.desc()).all()
    return [{"id":r.id,"company_name":r.company_name,"plan_type":r.plan_type,"monthly_price":r.monthly_price,"contracts_limit":r.contracts_limit,"contracts_used":r.contracts_used,"remaining":max(0,r.contracts_limit-r.contracts_used),"expires_at":r.expires_at.isoformat() if r.expires_at else None,"assigned_retainer_lawyer_id":r.assigned_retainer_lawyer_id} for r in rows]

@app.post("/api/v1/subscriptions/request-review", status_code=201)
def request_contract_review(payload: CorporateRequestCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub=db.query(CorporateSubscription).filter(CorporateSubscription.admin_user_id==user.id,CorporateSubscription.status=="ACTIVE").order_by(CorporateSubscription.created_at.desc()).first()
    if not sub: raise HTTPException(status_code=404, detail="Active corporate subscription not found.")
    if sub.contracts_used>=sub.contracts_limit: raise HTTPException(status_code=409, detail="Contract review quota khatam ho gaya.")
    sub.contracts_used+=1; row=CorporateRequest(subscription_id=sub.id,requested_by=user.id,assigned_lawyer_id=sub.assigned_retainer_lawyer_id,request_type=payload.request_type,description=payload.description,document_url=payload.document_url)
    db.add(row); db.commit(); db.refresh(row); return {"id":row.id,"status":row.status,"assigned_lawyer_id":row.assigned_lawyer_id}

@app.get("/api/v1/admin/corporate")
def admin_corporate(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [{"id":r.id,"company_name":r.company_name,"plan_type":r.plan_type,"status":r.status,"contracts_used":r.contracts_used,"contracts_limit":r.contracts_limit,"assigned_retainer_lawyer_id":r.assigned_retainer_lawyer_id} for r in db.query(CorporateSubscription).order_by(CorporateSubscription.created_at.desc()).all()]

@app.patch("/api/v1/admin/corporate/{subscription_id}/assign/{lawyer_user_id}")
def assign_corporate_lawyer(subscription_id: int, lawyer_user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    sub=db.query(CorporateSubscription).filter(CorporateSubscription.id==subscription_id).first(); lawyer=db.query(User).filter(User.id==lawyer_user_id,User.role=="lawyer",User.is_approved.is_(True)).first()
    if not sub or not lawyer: raise HTTPException(status_code=404, detail="Subscription or approved lawyer not found.")
    sub.assigned_retainer_lawyer_id=lawyer.id; db.add(AuditLog(actor_user_id=admin.id,action="corporate_lawyer_assigned",target_type="subscription",target_id=str(sub.id),details=f"lawyer_user_id={lawyer.id}")); db.commit(); return {"subscription_id":sub.id,"assigned_retainer_lawyer_id":lawyer.id}


class ODRCaseCreate(BaseModel):
    respondent_id: Optional[int] = Field(default=None, gt=0)
    mediator_lawyer_id: Optional[int] = Field(default=None, gt=0)
    dispute_type: str = Field(min_length=2, max_length=100)
    claim_amount: Optional[float] = Field(default=None, ge=0, le=1000000000)
    description: str = Field(min_length=10, max_length=10000)

@app.get("/api/v1/odr/cases")
def list_odr_cases(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = db.query(DisputeCase)
    if user.role != "admin":
        q = q.filter(or_(DisputeCase.claimant_id == user.id, DisputeCase.respondent_id == user.id, DisputeCase.mediator_lawyer_id == user.id))
    return [{"id": c.id, "claimant_id": c.claimant_id, "respondent_id": c.respondent_id, "mediator_lawyer_id": c.mediator_lawyer_id, "dispute_type": c.dispute_type, "claim_amount": c.claim_amount, "description": c.description, "settlement_status": c.settlement_status, "created_at": c.created_at.isoformat()} for c in q.order_by(DisputeCase.created_at.desc()).limit(100).all()]

@app.post("/api/v1/odr/cases", status_code=201)
def create_odr_case(payload: ODRCaseCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.respondent_id == user.id:
        raise HTTPException(status_code=422, detail="Claimant and respondent cannot be the same account.")
    if payload.respondent_id and not db.query(User).filter(User.id == payload.respondent_id).first():
        raise HTTPException(status_code=404, detail="Respondent account not found.")
    mediator = None
    if payload.mediator_lawyer_id:
        mediator = db.query(User).filter(User.id == payload.mediator_lawyer_id, User.role == "lawyer", User.is_approved.is_(True)).first()
        if not mediator or not mediator.lawyer_profile or not mediator.lawyer_profile.is_verified:
            raise HTTPException(status_code=400, detail="Mediator must be an approved, verified lawyer.")
    row = DisputeCase(claimant_id=user.id, **payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return {"id": row.id, "settlement_status": row.settlement_status, "message": "Dispute case created. This portal does not itself determine legal validity or enforceability."}

@app.post("/api/v1/odr/cases/{case_id}/settlement-draft")
def draft_odr_settlement(case_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(DisputeCase).filter(DisputeCase.id == case_id).first()
    if not row: raise HTTPException(status_code=404, detail="Dispute case not found.")
    if user.role != "admin" and user.id not in {row.claimant_id, row.respondent_id, row.mediator_lawyer_id}:
        raise HTTPException(status_code=403, detail="You are not a party or mediator in this dispute.")
    if not row.respondent_id or not row.mediator_lawyer_id:
        raise HTTPException(status_code=409, detail="Respondent aur verified mediator assign hone ke baad draft ban sakta hai.")
    draft = ("MEDIATED SETTLEMENT AGREEMENT — DRAFT ONLY\n\n"
             f"Dispute type: {row.dispute_type}\nClaimant user ID: {row.claimant_id}\nRespondent user ID: {row.respondent_id}\n"
             f"Mediator lawyer user ID: {row.mediator_lawyer_id}\nClaim amount (if any): {row.claim_amount or 'Not stated'}\n"
             f"Dispute summary: {row.description}\n\nTerms agreed by the parties: [Must be completed and reviewed by qualified Pakistani counsel.]\n"
             "NOTICE: This is not a signed or legally validated agreement. No OTP/SMS identity verification is configured in this build. Do not treat it as binding until parties' identities, consent, applicable law and signatures are independently verified by a qualified lawyer.")
    row.settlement_draft = draft; row.settlement_status = "DRAFT_PREPARED"; db.commit()
    return {"id": row.id, "draft": draft, "legally_binding": False, "otp_verification": "not_configured"}


# Optional bootstrap admin. No default credentials are ever created.
@app.on_event("startup")
def bootstrap_admin_from_env():
    admin_password = os.getenv("ADMIN_PASSWORD")
    admin_email = os.getenv("ADMIN_EMAIL")
    admin_phone = os.getenv("ADMIN_PHONE")
    if not admin_password or (not admin_email and not admin_phone):
        return
    db = SessionLocal()
    try:
        identity_filter = []
        if admin_email:
            identity_filter.append(User.email == admin_email.strip().lower())
        if admin_phone:
            identity_filter.append(User.phone == admin_phone.strip())
        admin = db.query(User).filter(or_(*identity_filter)).first()
        if admin:
            # Do not silently change an existing account's role/password on every restart.
            if admin.role != "admin":
                logger.error("ADMIN_EMAIL/ADMIN_PHONE matches a non-admin account; refusing auto-promotion.")
            return
        db.add(User(name=os.getenv("ADMIN_NAME", "LawNexa Administrator"), email=admin_email.strip().lower() if admin_email else None,
                    phone=admin_phone.strip() if admin_phone else None, hashed_password=pwd_context.hash(admin_password),
                    role="admin", is_approved=True, is_active=True))
        db.commit()
        logger.warning("Admin account created from ADMIN_* environment settings. Rotate credentials after setup.")
    except Exception:
        db.rollback()
        logger.exception("Admin bootstrap failed.")
    finally:
        db.close()


