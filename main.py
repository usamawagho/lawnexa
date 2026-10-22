import os
import re
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, validator
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text
from sqlalchemy.orm import sessionmaker, Session, declarative_base
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
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30  # 30 Days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

if GEMINI_API_KEY := os.getenv("GEMINI_API_KEY"):
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="LawNexa Production API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","), # Configurable CORS
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= DATABASE MODELS =================
class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="client")  # "client" or "lawyer"
    is_approved = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)
    avatar = Column(Text, nullable=True)
    
    # Lawyer Specific
    specialty = Column(String, nullable=True)
    license_number = Column(String, nullable=True)
    bar_association = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    city = Column(String, nullable=True)
    area = Column(String, nullable=True)
    chamber_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

# ================= PYDANTIC SCHEMAS =================
class UserRegister(BaseModel):
    name: str = Field(..., min_length=2)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=8) # Removed max_length=10 for security
    role: str = "client"
    city: Optional[str] = "Karachi"
    area: Optional[str] = "Saddar / City Court"
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = 0
    chamber_address: Optional[str] = None

class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    chamber_address: Optional[str] = None
    specialty: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = None

class DocumentRequest(BaseModel):
    doc_type: str = Field(alias="type", default="Agreement")
    party1: str = "First Party"
    party2: str = "Second Party"
    court: str = "Karachi, Pakistan"
    purpose: str = "Legal Representation"

# ================= DEPENDENCIES =================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserDB:
    exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expire ho chuka hai. Dobara login karein!",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise exception
    except JWTError:
        raise exception

    user = db.query(UserDB).filter(UserDB.id == int(user_id)).first()
    if user is None:
        raise exception
    return user

# ================= ROUTES =================

@app.post("/api/v1/auth/register")
def register_user(user: UserRegister, db: Session = Depends(get_db)):
    if not user.email and not user.phone:
        raise HTTPException(status_code=400, detail="Email ya Phone Number zaroori hai!")

    if user.email and db.query(UserDB).filter(UserDB.email == user.email).first():
        raise HTTPException(status_code=400, detail="Yeh Email pehle se registered hai!")
    
    if user.phone and db.query(UserDB).filter(UserDB.phone == user.phone).first():
        raise HTTPException(status_code=400, detail="Yeh Mobile Number pehle se registered hai!")

    role = "lawyer" if user.role.lower() in ["lawyer", "advocate", "vakeel"] else "client"

    new_user = UserDB(
        name=user.name.strip(),
        email=user.email.lower() if user.email else None,
        phone=user.phone.strip() if user.phone else None,
        hashed_password=pwd_context.hash(user.password.strip()),
        role=role,
        specialty=user.specialty or ("General Practice" if role == "lawyer" else None),
        license_number=user.license_number or ("PBC-REG" if role == "lawyer" else None),
        bar_association=user.bar_association or ("High Court Bar" if role == "lawyer" else None),
        experience_years=user.experience_years,
        city=user.city,
        area=user.area,
        chamber_address=user.chamber_address
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = jwt.encode(
        {"sub": str(new_user.id), "role": new_user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )

    return {"message": "Account create ho gaya!", "access_token": token, "role": new_user.role}


@app.post("/api/v1/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(
        (UserDB.email == form_data.username.lower()) | (UserDB.phone == form_data.username)
    ).first()
    
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Ghalat Phone/Email ya Password!")

    token = jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role}

# --- IS KE BAAD DALEIN (Yeh pehle se likha hoga) ---
@app.post("/api/v1/auth/token")
def login(...):
    # ... login logic ...

@app.get("/api/v1/auth/me")
def verify_token_and_get_user(current_user: UserDB = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "phone": current_user.phone,
        "role": current_user.role,
        "avatar": current_user.avatar,
        "city": current_user.city,
        "area": current_user.area,
        "chamberAddress": current_user.chamber_address,
        "specialty": current_user.specialty
    }


# --- IS SE PEHLE (Yeh aapki file mein pehle se hoga) ---
@app.put("/api/v1/users/profile")
def update_profile(...):
    # ... update logic ...


@app.put("/api/v1/users/profile")
def update_profile(payload: UserUpdate, current_user: UserDB = Depends(get_current_user), db: Session = Depends(get_db)):
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)
    
    db.commit()
    return {"message": "Profile updated!", "user_id": current_user.id}


@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(
    city: Optional[str] = None, 
    area: Optional[str] = None, 
    skip: int = 0, 
    limit: int = 20, 
    db: Session = Depends(get_db)
):
    query = db.query(UserDB).filter(UserDB.role == "lawyer")
    if city:
        query = query.filter(UserDB.city.ilike(f"%{city}%"))
    if area:
        query = query.filter(UserDB.area.ilike(f"%{area}%"))
        
    return query.offset(skip).limit(limit).all()


@app.post("/api/ai/generate-doc")
def generate_doc(payload: DocumentRequest):
    draft_template = f"""IN THE COURT OF {payload.court.upper()}

In the Matter of:
{payload.party1} ... (First Party)
VERSUS
{payload.party2} ... (Second Party)

SUBJECT: DRAFT FOR {payload.doc_type.upper()}

1. That the applicant submits this application regarding {payload.purpose}.
2. That all supporting legal requirements stand verified under Pakistan Law.

PRAYER:
It is respectfully prayed that this petition be granted in accordance with law."""

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"Draft a professional legal document in Pakistan jurisdiction for: {payload.doc_type}. Parties: {payload.party1} and {payload.party2}. Court: {payload.court}. Purpose: {payload.purpose}. Ensure formal legal tone."
            response = model.generate_content(prompt)
            if response.text:
                return {"draft": response.text.strip()}
        except Exception:
            pass # Silently fallback to template

    return {"draft": draft_template}
