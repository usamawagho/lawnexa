import os
import re
import random
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import google.generativeai as genai

# ================= CONFIGURATION & DATABASE =================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lawnexa.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_lawnexa_jwt_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 Days Token Validity

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Config Warning: {e}")

app = FastAPI(title="LawNexa Production API", version="3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

otp_store = {}


# ================= DATABASE MODELS =================
class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="client")
    is_approved = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    avatar = Column(Text, nullable=True)

    specialty = Column(String, nullable=True)
    license_number = Column(String, nullable=True)
    bar_association = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    city = Column(String, nullable=True)
    area = Column(String, nullable=True)
    chamber_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class PostDB(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    author_id = Column(Integer, ForeignKey("users.id"))
    content = Column(Text, nullable=False)
    bar_association = Column(String, nullable=True)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MessageDB(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, ForeignKey("users.id"))
    receiver_id = Column(Integer, ForeignKey("users.id"))
    message = Column(Text, nullable=False)
    quote_amount = Column(Float, nullable=True)
    quote_status = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(bind=engine)


# ================= HELPER FUNCTIONS =================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password.strip(), hashed_password)

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password.strip())

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expire ho chuka hai. Dobara login karein!",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if user is None:
        raise credentials_exception
    return user


# ================= REGISTRATION & AUTH =================
@app.post("/api/v1/auth/register")
@app.post("/api/v1/auth/register-lawyer")
def register_user(
    name: Optional[str] = Form(None),
    full_name: Optional[str] = Form(None),
    email: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    role: str = Form("lawyer"),
    specialty: Optional[str] = Form(None),
    category: Optional[str] = Form(None),
    license: Optional[str] = Form(None),
    license_no: Optional[str] = Form(None),
    bar: Optional[str] = Form(None),
    jurisdiction: Optional[str] = Form(None),
    exp: Optional[str] = Form(None),
    experience: Optional[str] = Form(None),
    city: Optional[str] = Form(None),
    area: Optional[str] = Form(None),
    chamberAddress: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    display_name = (name or full_name or "").strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip()
    clean_password = password.strip()

    if not display_name:
        raise HTTPException(status_code=400, detail="Pura naam dakhil karein!")

    if len(clean_password) < 8 or len(clean_password) > 10:
        raise HTTPException(status_code=400, detail="Password 8-10 characters ka hona zaroori hai!")

    existing_user = db.query(UserDB).filter(
        (UserDB.email == clean_email) | (UserDB.phone == clean_phone)
    ).first()
    
    if existing_user:
        raise HTTPException(status_code=400, detail="Yeh Email ya Mobile Number pehle se registered hai!")

    exp_years = None
    exp_val = exp or experience
    if exp_val:
        try:
            exp_years = int(re.sub(r'\D', '', str(exp_val)))
        except ValueError:
            exp_years = 0

    new_user = UserDB(
        name=display_name,
        email=clean_email,
        phone=clean_phone,
        hashed_password=get_password_hash(clean_password),
        role=role,
        is_approved=True,
        is_active=True,
        specialty=specialty or category or "General Practice",
        license_number=license or license_no or "PBC-REG",
        bar_association=bar or jurisdiction or "High Court Bar",
        experience_years=exp_years or 1,
        city=city or "Karachi",
        area=area or "Saddar / City Court",
        chamber_address=chamberAddress or "Chamber Main Court"
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    greeting = f"Advocate {display_name}" if role == "lawyer" else f"Welcome {display_name}"
    return {
        "status": "success",
        "message": f"{greeting}, aapka account successfully create ho gaya hai! Ab direct login karein."
    }


@app.post("/api/v1/auth/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    clean_username = form_data.username.strip().lower()
    clean_password = form_data.password.strip()

    user = db.query(UserDB).filter(
        (UserDB.email == clean_username) | (UserDB.phone == form_data.username.strip())
    ).first()
    
    if not user or not verify_password(clean_password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ghalat Phone/Email ya Password!",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
        "role": user.role
    }


@app.get("/api/v1/auth/me")
def verify_token_and_get_user(current_user: UserDB = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "phone": current_user.phone,
        "role": current_user.role,
        "is_approved": current_user.is_approved,
        "avatar": current_user.avatar,
        "city": current_user.city or "Karachi",
        "area": current_user.area or "Saddar / City Court",
        "chamberAddress": current_user.chamber_address,
        "specialty": current_user.specialty,
        "license": current_user.license_number,
        "bar": current_user.bar_association,
        "exp": current_user.experience_years
    }


# ================= PROFILE UPDATE =================
@app.post("/api/v1/users/profile")
def update_profile(
    payload: dict,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    current_user.name = payload.get("name", current_user.name).strip()
    current_user.phone = payload.get("phone", current_user.phone).strip()
    current_user.email = payload.get("email", current_user.email).strip().lower()
    
    if "avatar" in payload and payload["avatar"]:
        current_user.avatar = payload["avatar"]

    if current_user.role == "lawyer":
        current_user.city = payload.get("city", current_user.city)
        current_user.area = payload.get("area", current_user.area)
        current_user.chamber_address = payload.get("chamberAddress", current_user.chamber_address)
        current_user.specialty = payload.get("specialty", current_user.specialty)
        current_user.license_number = payload.get("license", current_user.license_number)
        current_user.bar_association = payload.get("bar", current_user.bar_association)
        if payload.get("exp") is not None:
            try:
                current_user.experience_years = int(payload["exp"])
            except ValueError:
                pass

    db.commit()
    db.refresh(current_user)

    return {
        "status": "success",
        "message": "Profile & Picture updated successfully!",
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "email": current_user.email,
            "phone": current_user.phone,
            "role": current_user.role,
            "avatar": current_user.avatar,
            "city": current_user.city,
            "area": current_user.area,
            "chamberAddress": current_user.chamber_address,
            "specialty": current_user.specialty,
            "license": current_user.license_number,
            "bar": current_user.bar_association,
            "exp": current_user.experience_years
        }
    }


# ================= LAWYER DIRECTORY =================
@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(db: Session = Depends(get_db)):
    lawyers = db.query(UserDB).filter(UserDB.role == "lawyer").all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "avatar": l.avatar,
            "specialty": l.specialty or "General Practice",
            "license_number": l.license_number or "N/A",
            "bar_association": l.bar_association or "High Court Bar",
            "experience_years": l.experience_years or 1,
            "city": l.city or "Karachi",
            "area": l.area or "Saddar / City Court",
            "chamber": l.chamber_address or "District Court Chambers"
        }
        for l in lawyers
    ]


# ================= CRASH-PROOF DOC GENERATOR =================
@app.post("/api/ai/generate-doc")
def generate_doc(payload: dict):
    try:
        doc_type = payload.get("doc_type", payload.get("type", "Agreement")).strip()
        p1 = payload.get("party1", "First Party").strip()
        p2 = payload.get("party2", "Second Party").strip()
        court = payload.get("court", "Karachi, Pakistan").strip()
        purpose = payload.get("purpose", "Legal Representation").strip()

        if GEMINI_API_KEY:
            try:
                model = genai.GenerativeModel("gemini-1.5-flash")
                prompt = f"Generate a formal legal document for {doc_type} between {p1} and {p2} for court {court}. Purpose: {purpose}."
                response = model.generate_content(prompt)
                if response and response.text:
                    return {"draft": response.text.strip()}
            except Exception as e:
                print(f"Gemini API Error: {e}")

        draft = f"""IN THE COURT OF {court.upper()}

In the Matter of:
{p1} ... (First Party / Applicant)
VERSUS
{p2} ... (Second Party / Respondent)

SUBJECT: DRAFT FOR {doc_type.upper()}

1. That the applicant submits this application regarding {purpose}.
2. That all supporting legal requirements stand verified under Pakistan Law.

PRAYER:
It is respectfully prayed that this petition be granted in accordance with law.

Advocate High Court"""
        return {"draft": draft}
    except Exception as general_err:
        return {"draft": f"LEGAL DRAFT TEMPLATE\n\nDocument Category: Legal Document\nLocation: Pakistan\n\nDraft details under review."}
