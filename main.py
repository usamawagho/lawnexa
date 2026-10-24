"""LawNexa API: shared models, safe public schemas and protected actions."""
import logging
import math
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile, File, Form, status
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
from models import User, Lawyer, Appointment, ChatMessage, Post, Like

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("lawnexa")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    if ENVIRONMENT == "production":
        raise RuntimeError("SECRET_KEY must be set in production; generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'")
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
    """Serve the actual frontend from the same origin as the API."""
    return FileResponse(BASE_DIR / "index.html")

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
# Existing users, posts and bookings are preserved.
def upgrade_schema():
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    migrations = {
        "posts": {
            "title": "VARCHAR(250) NOT NULL DEFAULT 'Legal Update'",
            "category": "VARCHAR(100) NOT NULL DEFAULT 'Legal Insight & Analysis'",
        },
        "appointments": {"location": "VARCHAR(200)"},
    }
    with engine.begin() as connection:
        for table, columns in migrations.items():
            if table not in tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in present:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))

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
    lat: Optional[float] = Field(default=None, ge=-90, le=90)
    lng: Optional[float] = Field(default=None, ge=-180, le=180)


class UserUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    phone: Optional[str] = Field(default=None, max_length=32)
    email: Optional[EmailStr] = None
    avatar: Optional[str] = Field(default=None, max_length=1000000)
    city: Optional[str] = None
    area: Optional[str] = None
    chamber_address: Optional[str] = None
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = Field(default=None, ge=0, le=80)


class DocumentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    doc_type: str = Field(default="Agreement", alias="type", min_length=2, max_length=100)
    party1: str = Field(default="First Party", max_length=200)
    party2: str = Field(default="Second Party", max_length=200)
    court: str = Field(default="Karachi, Pakistan", max_length=200)
    purpose: str = Field(default="Legal Representation", max_length=2000)


class PostCreate(BaseModel):
    title: str = Field(default="Legal Update", min_length=1, max_length=250)
    category: str = Field(default="Legal Insight & Analysis", min_length=2, max_length=100)
    content: str = Field(min_length=1, max_length=10000)
    bar_association: str = Field(min_length=2, max_length=200)
    media_url: Optional[str] = Field(default=None, max_length=500)
    media_type: Optional[str] = Field(default=None, max_length=20)


class ChatCreate(BaseModel):
    receiver_id: int = Field(gt=0)
    message: str = Field(min_length=1, max_length=10000)
    quote_amount: Optional[float] = Field(default=None, gt=0, le=100000000)


class BookingCreate(BaseModel):
    lawyer_id: int = Field(gt=0)
    booking_date: str = Field(min_length=4, max_length=30)
    time_slot: str = Field(min_length=1, max_length=40)
    location: Optional[str] = Field(default=None, max_length=200)
    case_summary: str = Field(min_length=5, max_length=5000)


class FirAnalysisRequest(BaseModel):
    text: str = Field(default="", max_length=50000)


def _clean_optional(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _user_public(user: User, include_private: bool = False) -> dict:
    data = {
        "id": user.id, "name": user.name, "role": user.role,
        "avatar": user.avatar, "city": user.city, "area": user.area,
        "specialty": user.specialty, "experience": user.experience_years or 0,
        "experience_years": user.experience_years or 0,
        "is_approved": bool(user.is_approved),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
    if include_private:
        data.update({"email": user.email, "phone": user.phone, "license_number": user.license_number,
                     "bar_association": user.bar_association, "chamber_address": user.chamber_address,
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
        "rating": profile.rating if profile else None,
        "is_verified": bool(profile and profile.is_verified and user.is_approved),
        "verification_status": "verified" if (profile and profile.is_verified and user.is_approved) else "pending",
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
    return {"status": "ok", "service": "lawnexa-api"}


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
    try:
        payload = UserRegister(**raw)
    except Exception as exc:
        # Keep validation details useful without exposing internal exceptions.
        details = getattr(exc, "errors", lambda: [])()
        raise HTTPException(status_code=422, detail=details or "Registration details are invalid.")

    if not payload.email and not payload.phone:
        raise HTTPException(status_code=400, detail="Email ya Phone Number zaroori hai!")
    requested_role = payload.role.strip().lower()
    if requested_role in {"lawyer", "advocate", "vakeel"}:
        role = "lawyer"
    elif requested_role in {"client", "user", ""}:
        role = "client"
    else:
        raise HTTPException(status_code=400, detail="Role sirf client ya lawyer ho sakta hai.")

    email = str(payload.email).lower() if payload.email else None
    phone = _clean_optional(payload.phone)
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
    )
    if role == "lawyer":
        # No fake licence/bar identifiers are generated. Admin verification is required before listing/posting.
        user.lawyer_profile = Lawyer(
            name=user.name, specialty=user.specialty or "General Practice",
            address=user.chamber_address, phone=phone, is_verified=False,
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
    user = db.query(User).filter(or_(User.email == identity.lower(), User.phone == identity)).first()
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
    update_data = payload.model_dump(exclude_unset=True)
    for key in ("name", "phone", "city", "area", "chamber_address", "specialty", "license_number", "bar_association"):
        if key in update_data:
            update_data[key] = _clean_optional(update_data[key])
    if "email" in update_data and update_data["email"]:
        update_data["email"] = str(update_data["email"]).lower()
    # Clients cannot claim lawyer credentials through profile edits.
    if current_user.role != "lawyer":
        for restricted in ("specialty", "license_number", "bar_association", "experience_years", "chamber_address"):
            update_data.pop(restricted, None)
    for key, value in update_data.items():
        setattr(current_user, key, value)
        if current_user.role == "lawyer" and current_user.lawyer_profile and key in {"name", "specialty", "phone", "license_number", "bar_association", "experience_years", "chamber_address"}:
            profile_key = "address" if key == "chamber_address" else key
            if hasattr(current_user.lawyer_profile, profile_key):
                setattr(current_user.lawyer_profile, profile_key, value)
    _commit_or_conflict(db, "Email ya phone kisi aur account ke saath registered hai.")
    db.refresh(current_user)
    return {"message": "Profile updated!", "user": _user_public(current_user, include_private=True)}


@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(
    city: Optional[str] = None, area: Optional[str] = None,
    client_lat: Optional[float] = None, client_lng: Optional[float] = None,
    radius_km: Optional[float] = Field(default=None, gt=0, le=1000),
    skip: int = Field(default=0, ge=0), limit: int = Field(default=20, ge=1, le=100),
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
    users = query.order_by(User.name.asc()).all()
    results = []
    for user in users:
        item = _lawyer_public(user)
        if client_lat is not None and client_lng is not None and radius_km is not None:
            profile = user.lawyer_profile
            if not profile or profile.lat is None or profile.lng is None:
                continue
            lat1, lon1, lat2, lon2 = map(math.radians, [client_lat, client_lng, profile.lat, profile.lng])
            dlat, dlon = lat2 - lat1, lon2 - lon1
            a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
            distance = 6371.0 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, a))))
            if distance > radius_km:
                continue
            item["distance_km"] = round(distance, 2)
        results.append(item)
    return results[skip:skip + limit]


@app.get("/api/v1/admin/lawyers/pending")
def pending_lawyers(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    users = db.query(User).options(joinedload(User.lawyer_profile)).filter(User.role == "lawyer", User.is_approved.is_(False)).order_by(User.created_at.asc()).all()
    return [{"id": u.lawyer_profile.id if u.lawyer_profile else u.id, "user_id": u.id, **_lawyer_public(u)} for u in users]


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
            "created_at": post.created_at.isoformat() if post.created_at else None}


@app.post("/api/v1/media/upload", status_code=201)
async def upload_media(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    _require_approved_lawyer(current_user)
    allowed_types = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4", "video/webm": ".webm"}
    extension = allowed_types.get((file.content_type or "").lower())
    if not extension:
        raise HTTPException(status_code=415, detail="Sirf JPG, PNG, WEBP, MP4 ya WEBM media allowed hai.")
    raw = await file.read(10 * 1024 * 1024 + 1)
    if not raw or len(raw) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Media file 10 MB se chhoti honi chahiye.")
    # Lightweight signature checks block files disguised as allowed extensions.
    valid = ((extension == ".jpg" and raw.startswith(b"\xff\xd8\xff")) or
             (extension == ".png" and raw.startswith(b"\x89PNG\r\n\x1a\n")) or
             (extension == ".webp" and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP") or
             (extension == ".mp4" and len(raw) > 12 and raw[4:8] == b"ftyp") or
             (extension == ".webm" and raw.startswith(b"\x1aE\xdf\xa3")))
    if not valid:
        raise HTTPException(status_code=415, detail="File content MIME type se match nahi karta.")
    filename = f"{uuid4().hex}{extension}"
    destination = UPLOAD_DIR / filename
    destination.write_bytes(raw)
    return {"url": f"/uploads/{filename}", "media_type": "video" if extension in {".mp4", ".webm"} else "image"}


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
    posts = query.order_by(Post.created_at.desc()).offset(max(0, skip)).limit(min(max(1, limit), 100)).all()
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
    receiver = db.query(User).filter(User.id == payload.receiver_id, User.is_active.is_(True)).first()
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found.")
    if payload.quote_amount is not None:
        _require_approved_lawyer(current_user)
    message = ChatMessage(sender_id=current_user.id, receiver_id=receiver.id,
                          message=payload.message.strip(), quote_amount=payload.quote_amount,
                          quote_status="pending" if payload.quote_amount is not None else "none")
    db.add(message)
    db.commit()
    db.refresh(message)
    return {"chat_id": message.id, "id": message.id, "sender_id": message.sender_id,
            "receiver_id": message.receiver_id, "message": message.message,
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
             "message": m.message, "quote_amount": m.quote_amount, "quote_status": m.quote_status,
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
                      current_user: User = Depends(get_current_user)):
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Real AI analysis configured nahi hai. Server par GEMINI_API_KEY set karein; koi sample result return nahi kiya gaya.")
    text = (text or "").strip()
    file_part = None
    if file and file.filename:
        allowed = {"application/pdf", "image/jpeg", "image/png", "image/webp"}
        if file.content_type not in allowed:
            raise HTTPException(status_code=415, detail="FIR file PDF, JPG, PNG ya WEBP honi chahiye.")
        file_bytes = await file.read(12 * 1024 * 1024 + 1)
        if len(file_bytes) > 12 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="FIR file 12 MB se chhoti honi chahiye.")
        if file_bytes:
            file_part = (file_bytes, file.content_type)
    if not text and not file_part:
        raise HTTPException(status_code=400, detail="FIR ka text paste karein ya supported file upload karein.")
    prompt = ("Analyze the supplied FIR for a Pakistan legal user. Do not invent facts, legal citations, sections, "
              "or predict outcomes. Clearly separate information copied from the supplied FIR from general observations. "
              "Use Google Search grounding to research current Pakistan statutes, court rules and official decisions; prioritize Pakistan Code, "
              "official Supreme Court/high court websites and other primary sources. Distinguish actual retrieved sources from assumptions. "
              "Provide: (1) identifiable offences/sections only if explicitly stated or confidently readable, (2) relevant current law with source-backed citations, "
              "(3) key factual gaps, (4) questions a Pakistan-licensed lawyer should check, and (5) urgent procedural considerations. "
              "Never invent citations, cases or sections. State that this is preliminary information and not legal advice. "
              "If the image/text is unclear or no reliable source is found, say so.\n\n" + text)
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
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=503, detail="Real AI document generation configured nahi hai. Server par GEMINI_API_KEY set karein; koi sample draft return nahi kiya gaya.")
    prompt = (
        "Create a clearly labelled DRAFT legal document for Pakistan; do not invent facts, citations, "
        "statutes, or claim legal compliance is verified. Add a prominent notice that a Pakistan-licensed "
        "lawyer must review it before use.\n"
        f"Document type: {payload.doc_type}\nFirst party: {payload.party1}\nSecond party: {payload.party2}\n"
        f"Court/jurisdiction stated by user: {payload.court}\nPurpose: {payload.purpose}"
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
