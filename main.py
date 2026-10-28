
import json
import logging
import os
from datetime import datetime, date, time
from zoneinfo import ZoneInfo
from typing import Any, Optional
from pathlib import Path
from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
load_dotenv(APP_DIR / ".env", override=False)

from fastapi import (
    FastAPI,
    Depends,
    HTTPException,
    status,
)
from fastapi.responses import FileResponse
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import auth
import database
import models
import schemas
from html_sanitizer import sanitize_document_html
from admin_bootstrap import provision_admin_from_environment


# ============================================================
# APP SETUP
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lawnexa")

app = FastAPI(
    title="LawNexa API",
    version="3.0.0",
)



bearer_scheme = HTTPBearer(auto_error=False)


DEFAULT_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "https://lawnexa.vercel.app",
]

env_origins = os.getenv("FRONTEND_ORIGINS") or os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = (
    [origin.strip() for origin in env_origins.split(",") if origin.strip()]
    if env_origins
    else DEFAULT_ORIGINS
)

runtime_environment = os.getenv("ENVIRONMENT", "development").strip().lower()
is_deployed_runtime = runtime_environment in {"production", "prod", "staging"} or os.getenv("RENDER", "").strip().lower() == "true"
if is_deployed_runtime:
    if not env_origins or not allowed_origins:
        raise RuntimeError("Set FRONTEND_ORIGINS (or ALLOWED_ORIGINS) to an explicit comma-separated allowlist in deployed environments.")
    from urllib.parse import urlparse
    for configured_origin in allowed_origins:
        parsed_origin = urlparse(configured_origin)
        if parsed_origin.scheme != "https" or not parsed_origin.netloc or parsed_origin.path or parsed_origin.query or parsed_origin.fragment:
            raise RuntimeError(f"Invalid production frontend origin: {configured_origin!r}. Use exact HTTPS origins without paths or trailing slashes.")
        if parsed_origin.hostname in {"localhost", "127.0.0.1", "0.0.0.0"} or configured_origin == "*":
            raise RuntimeError(f"Unsafe production frontend origin: {configured_origin!r}.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # Avoid wildcard Vercel-preview matching when credentials are enabled.
    # Add any required preview origin explicitly through FRONTEND_ORIGINS.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Apply additive, versioned migrations before serving requests. CORS is validated first so
# a misconfigured public deployment fails before touching the database.
# Apply versioned, additive Alembic migrations before serving requests. This
# repairs older databases without requiring manual ALTER TABLE commands.
def run_database_migrations() -> None:
    config = AlembicConfig(str(APP_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(APP_DIR / "alembic"))
    # ConfigParser treats '%' as interpolation syntax; escape it for valid URLs.
    config.set_main_option("sqlalchemy.url", database.DATABASE_URL.replace("%", "%%"))
    alembic_command.upgrade(config, "head")


run_database_migrations()
models.Base.metadata.create_all(bind=database.engine)
provision_admin_from_environment()


# ============================================================
# HELPERS
# ============================================================

def parse_specializations(value: Optional[str]) -> list[str]:
    if not value:
        return []

    try:
        result = json.loads(value)

        if isinstance(result, list):
            return [str(item) for item in result]

        # Support older records containing a single specialty.
        if isinstance(result, str):
            return [result]

    except (ValueError, TypeError):
        # Legacy records may contain plain text instead of JSON.
        return [value] if value.strip() else []

    return []


def serialize_specializations(value: Optional[list[str]]) -> str:
    return json.dumps(value or [], ensure_ascii=False)


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
        "bar_association": user.bar_association,
        "chamber_address": user.chamber_address,
        "experience_years": user.experience_years,
        "consultation_fee": user.consultation_fee,
        "specializations": parse_specializations(user.specializations),
        "is_active": user.is_active,
        "is_approved": user.is_approved,
        "created_at": (
            user.created_at.isoformat()
            if user.created_at
            else None
        ),
    }


def require_role(
    user: models.User,
    *allowed_roles: str,
) -> None:
    if (user.role or "").lower() not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        bearer_scheme
    ),
    db: Session = Depends(database.get_db),
) -> models.User:
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

    email = str(payload["sub"]).strip().lower()

    user = (
        db.query(models.User)
        .filter(models.User.email == email)
        .first()
    )

    if not user or user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is unavailable.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_admin(
    current_user: models.User = Depends(get_current_user),
) -> models.User:
    require_role(current_user, "admin")
    return current_user


def get_lawyer_profile_for_user(
    db: Session,
    user: models.User,
) -> Optional[models.Lawyer]:
    return (
        db.query(models.Lawyer)
        .filter(models.Lawyer.user_id == user.id)
        .first()
    )


def lawyer_response(
    lawyer: models.Lawyer,
    db: Session,
) -> dict[str, Any]:
    user = (
        db.query(models.User)
        .filter(models.User.id == lawyer.user_id)
        .first()
    )

    return {
        "id": lawyer.id,
        "user_id": lawyer.user_id,
        "name": lawyer.name,
        "email": user.email if user else None,
        "specialty": lawyer.specialty,
        "address": lawyer.address,
        "chamber_address": lawyer.chamber_address,
        "city": lawyer.city,
        "area": lawyer.area,
        "phone": lawyer.phone,
        "law_card_url": lawyer.law_card_url,
        "is_verified": lawyer.is_verified,
        "license_number": lawyer.license_number,
        "bar_association": lawyer.bar_association,
        "experience_years": lawyer.experience_years,
        "lat": lawyer.lat,
        "lng": lawyer.lng,
        "consultation_fee": user.consultation_fee if user else None,
        "specializations": (
            parse_specializations(user.specializations)
            if user
            else []
        ),
    }


def appointment_response(
    appointment: models.Appointment,
    db: Session,
) -> dict[str, Any]:
    client = (
        db.query(models.User)
        .filter(models.User.id == appointment.client_id)
        .first()
        if appointment.client_id is not None
        else None
    )

    lawyer = (
        db.query(models.Lawyer)
        .filter(models.Lawyer.id == appointment.lawyer_id)
        .first()
        if appointment.lawyer_id is not None
        else None
    )

    return {
        "id": appointment.id,
        "client_id": appointment.client_id,
        "client_name": client.full_name if client else None,
        "client_email": client.email if client else None,
        "lawyer_id": appointment.lawyer_id,
        "lawyer_name": lawyer.name if lawyer else None,
        "booking_date": appointment.booking_date,
        "time_slot": appointment.time_slot,
        "case_summary": appointment.case_summary,
        "status": appointment.status,
        "meeting_type": appointment.meeting_type or "physical",
        "meeting_mode": appointment.meeting_mode or "chamber",
        "consultation_fee": appointment.consultation_fee,
        "created_at": (
            appointment.created_at.isoformat()
            if appointment.created_at
            else None
        ),
        "location": appointment.location,
    }


def ensure_appointment_access(
    appointment: models.Appointment,
    current_user: models.User,
    db: Session,
) -> None:
    role = (current_user.role or "").lower()

    if role == "admin":
        return

    if role == "client" and appointment.client_id == current_user.id:
        return

    if role == "advocate":
        lawyer = get_lawyer_profile_for_user(db, current_user)

        if lawyer and appointment.lawyer_id == lawyer.id:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You cannot access this appointment.",
    )


# ============================================================
# ROOT AND HEALTH
# ============================================================

@app.get("/")
def root_check():
    return {
        "status": "online",
        "service": "LawNexa API",
        "version": "3.0.0",
    }


@app.get("/admin", include_in_schema=False)
def admin_portal():
    """Serve the separately protected admin UI shell; APIs still enforce roles."""
    admin_file = Path(__file__).resolve().parent / "admin.html"
    if not admin_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Admin portal asset is not installed.",
        )
    return FileResponse(admin_file, media_type="text/html")


@app.get("/health")
def health_check():
    try:
        from sqlalchemy import text

        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "ok",
            "database": "connected",
            "service": "LawNexa API",
        }

    except SQLAlchemyError:
        logger.exception("Health check database failure")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection unavailable.",
        )


# ============================================================
# AUTHENTICATION
# ============================================================

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
def register_user(
    user_data: schemas.UserCreate,
    db: Session = Depends(database.get_db),
):
    email = str(user_data.email).strip().lower()
    full_name = (user_data.full_name or "").strip()
    role = (user_data.role or "client").strip().lower()

    if not full_name:
        raise HTTPException(
            status_code=400,
            detail="Full name is required.",
        )

    if role not in {"client", "advocate"}:
        raise HTTPException(
            status_code=400,
            detail="Invalid account role.",
        )

    if db.query(models.User).filter(
        models.User.email == email
    ).first():
        raise HTTPException(
            status_code=409,
            detail="Email address pehle se registered hai.",
        )

    specializations = [item.strip() for item in (user_data.specializations or []) if item.strip()]

    if any(len(item) > 100 for item in specializations):
        raise HTTPException(status_code=400, detail="Each specialization must be 100 characters or fewer.")

    if role == "advocate" and len(specializations) > 3:
        raise HTTPException(
            status_code=400,
            detail="Maximum 3 specializations allowed.",
        )

    if (
        user_data.experience_years is not None
        and user_data.experience_years < 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Experience years cannot be negative.",
        )

    if (
        user_data.consultation_fee is not None
        and user_data.consultation_fee < 0
    ):
        raise HTTPException(
            status_code=400,
            detail="Consultation fee cannot be negative.",
        )

    try:
        hashed_password = auth.get_password_hash(user_data.password)

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    user = models.User(
        full_name=full_name,
        email=email,
        phone=user_data.phone,
        address=user_data.address,
        hashed_password=hashed_password,
        role=role,
        city=user_data.city,
        specializations=serialize_specializations(specializations),
        bar_council_no=user_data.bar_council_no,
        bar_association=user_data.bar_association,
        chamber_address=user_data.chamber_address,
        experience_years=user_data.experience_years,
        consultation_fee=user_data.consultation_fee,
        is_active=True,
        is_approved=(role == "client"),
    )

    try:
        db.add(user)
        # Get the database-generated user ID before creating the related
        # directory profile, but keep both records in one transaction.
        db.flush()
        if role == "advocate":
            db.add(
                models.Lawyer(
                    user_id=user.id,
                    name=full_name,
                    specialty=(specializations[0].strip() if specializations and specializations[0].strip() else "General Practice"),
                    # Do not copy the user's private residential address into
                    # the public directory. Chamber address is the public one.
                    address=None,
                    chamber_address=user_data.chamber_address,
                    city=user_data.city,
                    phone=user_data.phone,
                    is_verified=False,
                    license_number=user_data.bar_council_no,
                    bar_association=user_data.bar_association,
                    experience_years=user_data.experience_years,
                )
            )
        db.commit()
        db.refresh(user)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Email address pehle se registered hai.",
        )

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Registration database failure")

        raise HTTPException(
            status_code=500,
            detail="Registration failed. Please try again.",
        )

    try:
        token = auth.create_access_token(
            data={"sub": user.email, "role": user.role}
        )
    except Exception:
        logger.exception("Token creation failed after registration")
        raise HTTPException(
            status_code=500,
            detail="Account created, but login token could not be issued.",
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

    if not user or user.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
        )

    if not auth.verify_password(
        user_data.password,
        user.hashed_password,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email address or password.",
        )

    token = auth.create_access_token(
        data={"sub": user.email, "role": user.role}
    )

    return {
        "status": "success",
        "token": token,
        "user": user_response(user),
    }


# ============================================================
# USER PROFILE
# ============================================================

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

    identity_changed = False
    if data.full_name is not None:
        full_name = data.full_name.strip()

        if not full_name:
            raise HTTPException(
                status_code=400,
                detail="Full name cannot be empty.",
            )
        identity_changed = full_name != current_user.full_name
        current_user.full_name = full_name

    if data.address is not None:
        current_user.address = data.address

    if data.city is not None:
        current_user.city = data.city

    if data.profile_image is not None:
        current_user.profile_image = data.profile_image

    if data.specializations is not None:
        normalized_specializations = [item.strip() for item in data.specializations if item.strip()]
        if len(normalized_specializations) > 3:
            raise HTTPException(
                status_code=400,
                detail="Maximum 3 specializations allowed.",
            )
        if any(len(item) > 100 for item in normalized_specializations):
            raise HTTPException(status_code=400, detail="Each specialization must be 100 characters or fewer.")

        current_user.specializations = serialize_specializations(
            normalized_specializations
        )

    if data.bar_council_no is not None:
        if data.bar_council_no.strip() != (current_user.bar_council_no or "").strip():
            identity_changed = True
        current_user.bar_council_no = data.bar_council_no.strip() or None

    if data.chamber_address is not None:
        current_user.chamber_address = data.chamber_address

    if data.experience_years is not None:
        if data.experience_years < 0:
            raise HTTPException(
                status_code=400,
                detail="Experience years cannot be negative.",
            )

        current_user.experience_years = data.experience_years

    if data.bar_association is not None:
        current_user.bar_association = data.bar_association.strip() or None

    if data.consultation_fee is not None:
        if data.consultation_fee < 0:
            raise HTTPException(
                status_code=400,
                detail="Consultation fee cannot be negative.",
            )

        current_user.consultation_fee = data.consultation_fee

    # Keep the advocate's public directory profile in sync with their account.
    # Private residential address is intentionally never copied to Lawyer.address.
    if (current_user.role or "").lower() == "advocate":
        lawyer_profile = get_lawyer_profile_for_user(db, current_user)
        if lawyer_profile:
            lawyer_profile.name = current_user.full_name
            lawyer_profile.phone = current_user.phone
            lawyer_profile.city = current_user.city
            lawyer_profile.chamber_address = current_user.chamber_address
            lawyer_profile.license_number = current_user.bar_council_no
            lawyer_profile.bar_association = current_user.bar_association
            lawyer_profile.experience_years = current_user.experience_years
            specialties = parse_specializations(current_user.specializations)
            lawyer_profile.specialty = specialties[0] if specialties else "General Practice"
            if identity_changed:
                # Any name/license change requires an administrator to re-check
                # the identity against the bar record before public listing.
                lawyer_profile.is_verified = False

    try:
        db.commit()
        db.refresh(current_user)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Profile update database failure")

        raise HTTPException(
            status_code=500,
            detail="Profile update failed.",
        )

    return {
        "status": "success",
        "message": "Profile updated successfully.",
        "user": user_response(current_user),
    }


# ============================================================
# LAWYER DIRECTORY
# ============================================================

@app.get("/api/lawyers")
def list_lawyers(
    city: Optional[str] = None,
    specialty: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    query = (
        db.query(models.Lawyer)
        .join(
            models.User,
            models.User.id == models.Lawyer.user_id,
        )
        .filter(models.User.is_active.is_(True))
        .filter(models.User.is_approved.is_(True))
        .filter(models.User.role == "advocate")
        .filter(models.Lawyer.is_verified.is_(True))
    )

    if city and city.strip():
        query = query.filter(
            models.Lawyer.city.ilike(f"%{city.strip()}%")
        )

    if specialty and specialty.strip():
        term = f"%{specialty.strip()}%"
        query = query.filter(
            models.Lawyer.specialty.ilike(term)
        )

    lawyers = query.order_by(models.Lawyer.name.asc()).all()

    return [
        lawyer_response(lawyer, db)
        for lawyer in lawyers
    ]


@app.get("/api/lawyers/{lawyer_id}")
def get_lawyer(
    lawyer_id: int,
    db: Session = Depends(database.get_db),
):
    lawyer = (
        db.query(models.Lawyer)
        .join(
            models.User,
            models.User.id == models.Lawyer.user_id,
        )
        .filter(models.Lawyer.id == lawyer_id)
        .filter(models.User.is_active.is_(True))
        .filter(models.User.is_approved.is_(True))
        .filter(models.User.role == "advocate")
        .filter(models.Lawyer.is_verified.is_(True))
        .first()
    )

    if not lawyer:
        raise HTTPException(
            status_code=404,
            detail="Lawyer not found.",
        )

    return lawyer_response(lawyer, db)


# ============================================================
# APPOINTMENTS
# ============================================================

class AppointmentCreate(BaseModel):
    lawyer_id: int
    booking_date: str = Field(min_length=10, max_length=10)
    time_slot: str = Field(min_length=5, max_length=5)
    meeting_type: str = Field(default="physical", min_length=1, max_length=20)
    meeting_mode: str = Field(default="chamber", min_length=1, max_length=20)
    case_summary: Optional[str] = Field(default=None, max_length=4000)
    location: Optional[str] = Field(default=None, max_length=255)


class AppointmentStatusUpdate(BaseModel):
    status: str = Field(min_length=1, max_length=20)


@app.post("/api/appointments", status_code=status.HTTP_201_CREATED)
def create_appointment(
    data: AppointmentCreate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    require_role(current_user, "client")

    booking_date = data.booking_date.strip()
    time_slot = data.time_slot.strip()
    meeting_type = data.meeting_type.strip().lower()
    meeting_mode = data.meeting_mode.strip().lower()

    if meeting_type not in {"physical", "virtual"}:
        raise HTTPException(status_code=400, detail="Invalid meeting type.")
    allowed_modes = {"chamber"} if meeting_type == "physical" else {"voice_call", "video_call"}
    if meeting_mode not in allowed_modes:
        raise HTTPException(status_code=400, detail="Invalid meeting mode for this appointment.")
    try:
        selected_date = date.fromisoformat(booking_date)
        selected_time = datetime.strptime(time_slot, "%H:%M").time()
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Choose a valid date and time.",
        ) from exc
    local_zone = ZoneInfo("Asia/Karachi")
    selected_datetime = datetime.combine(selected_date, selected_time, tzinfo=local_zone)
    if selected_datetime <= datetime.now(local_zone):
        raise HTTPException(status_code=400, detail="Appointment must be scheduled in the future.")

    lawyer = (
        db.query(models.Lawyer)
        .join(
            models.User,
            models.User.id == models.Lawyer.user_id,
        )
        .filter(models.Lawyer.id == data.lawyer_id)
        .filter(models.User.is_active.is_(True))
        .filter(models.User.is_approved.is_(True))
        .filter(models.User.role == "advocate")
        .filter(models.Lawyer.is_verified.is_(True))
        .first()
    )

    if not lawyer:
        raise HTTPException(
            status_code=404,
            detail="Verified lawyer not found.",
        )

    lawyer_user = db.query(models.User).filter(models.User.id == lawyer.user_id).first()
    if not lawyer_user:
        raise HTTPException(status_code=404, detail="Verified lawyer not found.")

    # Serialize appointment creation for this advocate on databases that support
    # row locks, then reject an already pending/confirmed slot.
    try:
        db.query(models.Lawyer).filter(models.Lawyer.id == lawyer.id).with_for_update().first()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not lock advocate profile while booking")
        raise HTTPException(status_code=500, detail="Appointment slot could not be checked.")
    conflict = (
        db.query(models.Appointment)
        .filter(models.Appointment.lawyer_id == lawyer.id)
        .filter(models.Appointment.booking_date == booking_date)
        .filter(models.Appointment.time_slot == time_slot)
        .filter(models.Appointment.status.in_(["pending", "confirmed", "Pending Confirmation", "Confirmed", "In Escrow Hold"]))
        .first()
    )
    if conflict:
        raise HTTPException(status_code=409, detail="This advocate already has an active appointment for that date and time. Choose another slot.")

    # Fee is read from the verified lawyer's server-side profile; never accept
    # a browser-supplied amount as the source of truth.
    appointment = models.Appointment(
        client_id=current_user.id,
        lawyer_id=lawyer.id,
        booking_date=booking_date,
        time_slot=time_slot,
        case_summary=(data.case_summary or "").strip() or None,
        location=(lawyer.chamber_address or lawyer.address) if meeting_type == "physical" else None,
        meeting_type=meeting_type,
        meeting_mode=meeting_mode,
        consultation_fee=lawyer_user.consultation_fee,
        status="pending",
    )

    try:
        db.add(appointment)
        db.commit()
        db.refresh(appointment)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Appointment creation failed")

        raise HTTPException(
            status_code=500,
            detail="Appointment could not be created.",
        )

    return {
        "status": "success",
        "appointment": appointment_response(appointment, db),
    }


@app.get("/api/appointments")
def list_appointments(
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    role = (current_user.role or "").lower()

    query = db.query(models.Appointment)

    if role == "client":
        query = query.filter(
            models.Appointment.client_id == current_user.id
        )

    elif role == "advocate":
        lawyer = get_lawyer_profile_for_user(db, current_user)

        if not lawyer:
            return []

        query = query.filter(
            models.Appointment.lawyer_id == lawyer.id
        )

    elif role != "admin":
        raise HTTPException(
            status_code=403,
            detail="You cannot access appointments.",
        )

    appointments = query.order_by(
        models.Appointment.id.desc()
    ).all()

    return [
        appointment_response(appointment, db)
        for appointment in appointments
    ]


@app.get("/api/appointments/{appointment_id}")
def get_appointment(
    appointment_id: int,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found.",
        )

    ensure_appointment_access(appointment, current_user, db)

    return appointment_response(appointment, db)


@app.patch("/api/appointments/{appointment_id}/status")
def update_appointment_status(
    appointment_id: int,
    data: AppointmentStatusUpdate,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    new_status = data.status.strip().lower()

    allowed_statuses = {
        "pending",
        "confirmed",
        "completed",
        "cancelled",
        "rejected",
    }

    if new_status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail="Invalid appointment status.",
        )

    appointment = (
        db.query(models.Appointment)
        .filter(models.Appointment.id == appointment_id)
        .first()
    )

    if not appointment:
        raise HTTPException(
            status_code=404,
            detail="Appointment not found.",
        )

    ensure_appointment_access(appointment, current_user, db)

    role = (current_user.role or "").lower()
    previous_status = (appointment.status or "pending").strip().lower()
    legacy_statuses = {
        "pending confirmation": "pending",
        "in escrow hold": "pending",
        "completed & escrow released": "completed",
        "cancelled & refunded": "cancelled",
        "cancelled & refunded by lawyer": "cancelled",
    }
    previous_status = legacy_statuses.get(previous_status, previous_status)

    if role == "client":
        if new_status != "cancelled":
            raise HTTPException(status_code=403, detail="Clients can only cancel their own appointments.")
        if previous_status not in {"pending", "confirmed"}:
            raise HTTPException(status_code=409, detail="This appointment can no longer be cancelled.")
    elif role == "advocate":
        transitions = {
            "pending": {"confirmed", "rejected", "cancelled"},
            "confirmed": {"completed", "cancelled"},
        }
        if new_status not in transitions.get(previous_status, set()):
            raise HTTPException(status_code=409, detail=f"Invalid appointment transition: {previous_status} → {new_status}.")
    elif role != "admin":
        raise HTTPException(status_code=403, detail="You cannot change appointment status.")

    appointment.status = new_status

    try:
        db.commit()
        db.refresh(appointment)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Appointment status update failed")

        raise HTTPException(
            status_code=500,
            detail="Appointment status could not be updated.",
        )

    return {
        "status": "success",
        "appointment": appointment_response(appointment, db),
    }


# ============================================================
# ADMIN
# ============================================================

@app.get("/api/admin/dashboard")
def admin_dashboard(
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    total_users = db.query(models.User).count()

    total_clients = (
        db.query(models.User)
        .filter(models.User.role == "client")
        .count()
    )

    total_advocates = (
        db.query(models.User)
        .filter(models.User.role == "advocate")
        .count()
    )

    pending_advocates = (
        db.query(models.User)
        .filter(models.User.role == "advocate")
        .filter(models.User.is_approved.is_not(True))
        .count()
    )

    total_appointments = db.query(models.Appointment).count()

    pending_appointments = (
        db.query(models.Appointment)
        .filter(models.Appointment.status == "pending")
        .count()
    )

    return {
        "total_users": total_users,
        "total_clients": total_clients,
        "total_advocates": total_advocates,
        "pending_advocates": pending_advocates,
        "total_appointments": total_appointments,
        "pending_appointments": pending_appointments,
    }


@app.get("/api/admin/users")
def admin_list_users(
    role: Optional[str] = None,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    query = db.query(models.User)

    if role:
        normalized_role = role.strip().lower()

        if normalized_role not in {"client", "advocate", "admin"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid role filter.",
            )

        query = query.filter(models.User.role == normalized_role)

    users = query.order_by(models.User.id.desc()).all()

    return [user_response(user) for user in users]


@app.get("/api/admin/advocates/pending")
def admin_pending_advocates(
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    advocates = (
        db.query(models.User)
        .filter(models.User.role == "advocate")
        .filter(models.User.is_approved.is_not(True))
        .order_by(models.User.id.desc())
        .all()
    )

    return [user_response(user) for user in advocates]


@app.patch("/api/admin/advocates/{user_id}/approve")
def admin_approve_advocate(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    advocate = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .filter(models.User.role == "advocate")
        .first()
    )

    if not advocate:
        raise HTTPException(
            status_code=404,
            detail="Advocate account not found.",
        )

    advocate.is_approved = True

    try:
        db.commit()
        db.refresh(advocate)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Advocate approval failed")

        raise HTTPException(
            status_code=500,
            detail="Advocate approval failed.",
        )

    return {
        "status": "success",
        "message": "Advocate account approved.",
        "user": user_response(advocate),
    }


@app.patch("/api/admin/advocates/{user_id}/reject")
def admin_reject_advocate(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    advocate = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .filter(models.User.role == "advocate")
        .first()
    )

    if not advocate:
        raise HTTPException(
            status_code=404,
            detail="Advocate account not found.",
        )

    advocate.is_approved = False
    lawyer_profile = get_lawyer_profile_for_user(db, advocate)
    if lawyer_profile:
        lawyer_profile.is_verified = False

    try:
        db.commit()
        db.refresh(advocate)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Advocate rejection failed")

        raise HTTPException(
            status_code=500,
            detail="Advocate status could not be updated.",
        )

    return {
        "status": "success",
        "message": "Advocate approval revoked.",
        "user": user_response(advocate),
    }


@app.get("/api/admin/advocates/unverified")
def admin_unverified_advocates(
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    """Approved advocate accounts awaiting explicit license verification."""
    advocates = (
        db.query(models.User)
        .filter(models.User.role == "advocate")
        .filter(models.User.is_active.is_(True))
        .filter(models.User.is_approved.is_(True))
        .order_by(models.User.id.desc())
        .all()
    )
    pending = []
    for advocate in advocates:
        lawyer = get_lawyer_profile_for_user(db, advocate)
        if not lawyer or lawyer.is_verified is not True:
            item = user_response(advocate)
            item["lawyer_id"] = lawyer.id if lawyer else None
            item["is_verified"] = lawyer.is_verified if lawyer else False
            pending.append(item)
    return pending


@app.patch("/api/admin/advocates/{user_id}/verify")
def admin_verify_lawyer(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    advocate = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .filter(models.User.role == "advocate")
        .first()
    )

    if not advocate:
        raise HTTPException(
            status_code=404,
            detail="Advocate account not found.",
        )

    if advocate.is_approved is not True:
        raise HTTPException(
            status_code=400,
            detail="Approve the advocate account before verification.",
        )

    if not (advocate.bar_council_no or "").strip():
        raise HTTPException(
            status_code=400,
            detail="A Bar Council license number is required before verification.",
        )

    lawyer = get_lawyer_profile_for_user(db, advocate)
    if not lawyer:
        # Defensive recovery for accounts created by an older app version.
        # This route is admin-only and the profile remains hidden until verified.
        specialties = parse_specializations(advocate.specializations)
        lawyer = models.Lawyer(
            user_id=advocate.id,
            name=advocate.full_name,
            specialty=specialties[0] if specialties else "General Practice",
            address=None,
            chamber_address=advocate.chamber_address,
            city=advocate.city,
            phone=advocate.phone,
            is_verified=False,
            license_number=advocate.bar_council_no,
            bar_association=advocate.bar_association,
            experience_years=advocate.experience_years,
        )
        db.add(lawyer)
        db.flush()

    lawyer.is_verified = True

    try:
        db.commit()
        db.refresh(lawyer)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Lawyer verification failed")

        raise HTTPException(
            status_code=500,
            detail="Lawyer verification failed.",
        )

    return {
        "status": "success",
        "message": "Lawyer profile verified.",
        "lawyer": lawyer_response(lawyer, db),
    }


@app.patch("/api/admin/users/{user_id}/deactivate")
def admin_deactivate_user(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    if user.id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own admin account.",
        )

    user.is_active = False

    try:
        db.commit()
        db.refresh(user)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("User deactivation failed")

        raise HTTPException(
            status_code=500,
            detail="User could not be deactivated.",
        )

    return {
        "status": "success",
        "message": "User account deactivated.",
        "user": user_response(user),
    }


@app.patch("/api/admin/users/{user_id}/activate")
def admin_activate_user(
    user_id: int,
    db: Session = Depends(database.get_db),
    admin: models.User = Depends(get_admin),
):
    user = (
        db.query(models.User)
        .filter(models.User.id == user_id)
        .first()
    )

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    user.is_active = True

    try:
        db.commit()
        db.refresh(user)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("User activation failed")

        raise HTTPException(
            status_code=500,
            detail="User could not be activated.",
        )

    return {
        "status": "success",
        "message": "User account activated.",
        "user": user_response(user),
    }


# ============================================================
# DOCUMENT TEMPLATES
# ============================================================

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


# ============================================================
# USER DOCUMENTS
# ============================================================

@app.post("/api/documents/save")
def save_user_document(
    req: schemas.DocumentSaveRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(database.get_db),
):
    doc_type = req.doc_type.strip()
    title = req.title.strip()
    if not doc_type or not title:
        raise HTTPException(
            status_code=400,
            detail="Document type and title are required.",
        )

    # The record is always owned by the authenticated account; never trust
    # the legacy user_email field sent by the browser.
    new_doc = models.UserDocument(
        user_id=current_user.id,
        doc_type=doc_type,
        title=title,
        form_data=json.dumps(req.form_data, ensure_ascii=False),
        generated_html=sanitize_document_html(req.generated_html),
    )

    try:
        db.add(new_doc)
        db.commit()
        db.refresh(new_doc)

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Document save failed")

        raise HTTPException(
            status_code=500,
            detail="Document could not be saved.",
        )

    return {
        "status": "success",
        "message": "Document saved successfully.",
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
            form_data = (
                json.loads(document.form_data)
                if document.form_data
                else {}
            )
        except (ValueError, TypeError):
            form_data = {}

        result.append({
            "id": document.id,
            "doc_type": document.doc_type,
            "title": document.title,
            "created_at": (
                document.created_at.strftime("%Y-%m-%d %H:%M")
                if document.created_at
                else None
            ),
            "form_data": form_data,
            "generated_html": document.generated_html,
        })

    return result


# ============================================================
# LEGAL RESEARCH
# ============================================================

class ChatMessage(BaseModel):
    role: str = Field(min_length=1, max_length=20)
    content: str = Field(min_length=1, max_length=4000)


class LegalResearchRequest(BaseModel):
    history: list[ChatMessage] = Field(default_factory=list, max_length=20)
    user_input: str = Field(min_length=1, max_length=4000)
    language: Optional[str] = "roman_urdu"


@app.post("/api/ai-legal-research")
async def process_legal_research(req: LegalResearchRequest):
    if not req.user_input.strip():
        raise HTTPException(
            status_code=400,
            detail="Please enter your legal question or case facts.",
        )

    if len(req.history) < 3:
        return {
            "status": "clarifying",
            "reply": (
                "Aapke case ko behtar samajhne ke liye batayein: "
                "kya is waqye mein kisi ko physical injury hui hai, "
                "ya sirf vehicle/property damage hua hai?"
            ),
            "case_brief": None,
        }

    # This is a placeholder, not a live legal research engine.
    return {
        "status": "completed",
        "reply": (
            "Initial case summary tayyar hai. Final legal advice ya "
            "applicable laws confirm karne ke liye relevant facts, "
            "jurisdiction aur original legal sources verify karein."
        ),
        "case_brief": {
            "category": "Preliminary review",
            "applicable_laws": [],
            "summary": req.user_input,
            "recommended_specialty": None,
        },
    }
