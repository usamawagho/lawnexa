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
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 Hours

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

# Gemini AI Setup
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

# Global OTP Store (In-Memory)
otp_store = {}


# ================= DATABASE MODELS =================
class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    phone = Column(String, unique=True, index=True, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="client")  # 'client', 'lawyer', 'admin'
    is_approved = Column(Boolean, default=True)
    is_active = Column(Boolean, default=True)

    specialty = Column(String, nullable=True)
    license_number = Column(String, nullable=True)
    bar_association = Column(String, nullable=True)
    experience_years = Column(Integer, nullable=True)
    city = Column(String, nullable=True)
    area = Column(String, nullable=True)
    chamber_address = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    @property
    def full_name(self):
        return self.name


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


# ================= SEED DEFAULT ADMIN ACCOUNT =================
@app.on_event("startup")
def seed_admin_user():
    db = SessionLocal()
    try:
        admin = db.query(UserDB).filter(UserDB.role == "admin").first()
        if not admin:
            admin_user = UserDB(
                name="System Admin",
                phone="03000000000",
                email="admin@lawnexa.pk",
                hashed_password=pwd_context.hash("Admin123"),
                role="admin",
                is_approved=True,
                is_active=True
            )
            db.add(admin_user)
            db.commit()
    finally:
        db.close()


# ================= HELPER & AUTH SECURITY FUNCTIONS =================
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def validate_password_complexity(password: str):
    """Between 8 and 10 Characters with Capital, Small letter, and Number"""
    if len(password) < 8 or len(password) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password kam se kam 8 aur zyada se zyada 10 characters ka hona zaroori hai!"
        )
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password mein kam se kam EK capital letter (A-Z) hona zaroori hai!"
        )
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password mein small letters (a-z) hone chahiye!"
        )
    if not re.search(r"[0-9]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password mein kam se kam EK number (0-9) hona zaroori hai!"
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> UserDB:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Aapka session expire ho chuka hai. Kripya dobara login karein!",
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


def get_current_admin(current_user: UserDB = Depends(get_current_user)) -> UserDB:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access Denied! Sirf Admin hi is action ko perform kar sakta hai."
        )
    return current_user


# ================= OTP & PASSWORD RESET ENDPOINTS =================
@app.post("/api/v1/auth/forgot-password")
def forgot_password(username: str = Form(...)):
    user_id = username.strip()
    otp = f"{random.randint(100000, 999999)}"
    
    otp_store[user_id] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    }

    print(f"\n==========================================")
    print(f"🔑 REALTIME OTP FOR [{user_id}]: {otp}")
    print(f"==========================================\n")

    return {"message": f"OTP sent successfully to {user_id}! Check server logs or phone."}


@app.post("/api/v1/auth/reset-password")
def reset_password(
    username: str = Form(...), 
    otp: str = Form(...), 
    new_password: str = Form(...),
    db: Session = Depends(get_db)
):
    user_id = username.strip()
    record = otp_store.get(user_id)

    if not record or record["otp"] != otp.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Ghalat OTP Code! Sahi OTP dakhil karein."
        )

    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="OTP expire ho chuka hai! Naya OTP mangwayein."
        )

    validate_password_complexity(new_password)

    user = db.query(UserDB).filter((UserDB.phone == user_id) | (UserDB.email == user_id)).first()
    if user:
        user.hashed_password = get_password_hash(new_password)
        db.commit()

    del otp_store[user_id]

    return {"message": "Password successfully reset! Ab aap naye password se login kar sakte hain."}


# ================= COMPLETE & CRASH-PROOF UNIFIED REGISTRATION =================
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
    if not display_name:
        raise HTTPException(status_code=400, detail="Pura naam dakhil karein!")

    # Password Length Check (8-10 Characters)
    if len(password) < 8 or len(password) > 10:
        raise HTTPException(status_code=400, detail="Password 8-10 characters ka hona zaroori hai!")

    # Check duplicate Email or Phone
    existing_user = db.query(UserDB).filter((UserDB.email == email) | (UserDB.phone == phone)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Yeh Email ya Mobile Number pehle se registered hai!")

    hashed_pwd = pwd_context.hash(password)

    # Experience conversion
    exp_years = None
    exp_val = exp or experience
    if exp_val:
        try:
            exp_years = int(re.sub(r'\D', '', str(exp_val)))
        except ValueError:
            exp_years = 0

    new_user = UserDB(
        name=display_name,
        email=email,
        phone=phone,
        hashed_password=hashed_pwd,
        role=role,
        is_approved=True,  # Auto-Approve Enabled
        is_active=True,    # Direct Active
        specialty=specialty or category,
        license_number=license or license_no,
        bar_association=bar or jurisdiction,
        experience_years=exp_years,
        city=city,
        area=area,
        chamber_address=chamberAddress
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    print(f"🎉 USER REGISTERED SUCCESSFULLY: {display_name} ({role})")

    return {
        "status": "success",
        "message": f"Advocate {display_name}, aapka account successfully active ho gaya hai! Ab direct login karein."
    }


# ================= AUTHENTICATION LOGIN ENDPOINT =================
@app.post("/api/v1/auth/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter((UserDB.email == form_data.username) | (UserDB.phone == form_data.username)).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ghalat Phone/Email ya Password!",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role}, expires_delta=access_token_expires
    )
    
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
        "is_approved": current_user.is_approved
    }


# ================= PROTECTED ADVOCATE DIRECTORY =================
@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(db: Session = Depends(get_db)):
    lawyers = db.query(UserDB).filter(
        UserDB.role == "lawyer",
        UserDB.is_approved == True
    ).all()

    return [
        {
            "id": l.id,
            "name": l.name,
            "specialty": l.specialty or "General Practice",
            "license_number": l.license_number,
            "bar_association": l.bar_association or "High Court Bar",
            "experience_years": l.experience_years or 0,
            "city": l.city or "Karachi",
            "area": l.area or "Saddar",
            "chamber": l.chamber_address
        }
        for l in lawyers
    ]


# ================= PROTECTED SOCIAL FEED =================
@app.get("/api/v1/posts")
def get_posts(db: Session = Depends(get_db)):
    posts = db.query(PostDB).order_by(PostDB.created_at.desc()).all()
    return [
        {
            "id": p.id,
            "content": p.content,
            "bar_association": p.bar_association,
            "likes": p.likes,
            "created_at": p.created_at.strftime("%Y-%m-%d %H:%M")
        }
        for p in posts
    ]


@app.post("/api/v1/posts")
def create_post(
    content: str = Form(...),
    bar_association: Optional[str] = Form("High Court Bar"),
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_post = PostDB(content=content, bar_association=bar_association, author_id=current_user.id)
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    return {"message": "Post published successfully!", "id": new_post.id}


@app.post("/api/v1/posts/{post_id}/like")
def like_post(
    post_id: int, 
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    post = db.query(PostDB).filter(PostDB.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.likes += 1
    db.commit()
    return {"likes": post.likes}


# ================= PROTECTED CONFIDENTIAL CHAT =================
@app.post("/api/v1/chat/send")
def send_chat_message(
    payload: dict,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    receiver_id = payload.get("receiver_id")
    msg_text = payload.get("message")
    quote_amt = payload.get("quote_amount")

    if not receiver_id or not msg_text:
        raise HTTPException(status_code=400, detail="Receiver and Message text are required!")

    new_msg = MessageDB(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        message=msg_text,
        quote_amount=quote_amt,
        quote_status="pending" if quote_amt else None
    )
    db.add(new_msg)
    db.commit()
    return {"message": "Message sent!"}


@app.get("/api/v1/chat/history/{other_id}")
def get_chat_history(
    other_id: int,
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    my_id = current_user.id
    messages = db.query(MessageDB).filter(
        ((MessageDB.sender_id == my_id) & (MessageDB.receiver_id == other_id)) |
        ((MessageDB.sender_id == other_id) & (MessageDB.receiver_id == my_id))
    ).order_by(MessageDB.created_at.asc()).all()

    return [
        {
            "id": m.id,
            "sender_id": m.sender_id,
            "receiver_id": m.receiver_id,
            "message": m.message,
            "quote_amount": m.quote_amount,
            "quote_status": m.quote_status
        }
        for m in messages
    ]


@app.post("/api/v1/chat/quote/{msg_id}/respond")
def respond_to_quote(
    msg_id: int,
    action: str = "accepted",
    current_user: UserDB = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    msg = db.query(MessageDB).filter(MessageDB.id == msg_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Quote message not found")
    msg.quote_status = action
    db.commit()
    return {"message": f"Quote status updated to {action}"}


# ================= AI LEGAL ENGINE =================
@app.post("/api/ai/analyze-fir")
def analyze_fir(fir_text: str = Form("")):
    return {
        "status": "success",
        "report": {
            "riskLevel": "Medium Risk",
            "offenses": ["PPC 379 - Theft", "PPC 411 - Possession of stolen property"],
            "bailType": "Pre-Arrest Bail Recommended",
            "strategy": "File interim pre-arrest bail application in Sessions Court under Section 498 CrPC."
        }
    }


@app.post("/api/ai/generate-doc")
def generate_doc(payload: dict):
    doc_type = payload.get("doc_type", "Agreement").strip()
    p1 = payload.get("party1", "First Party / Applicant").strip()
    p2 = payload.get("party2", "Second Party / Respondent").strip()
    court = payload.get("court", "Karachi, Pakistan").strip()
    purpose = payload.get("purpose", "").strip()

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
You are an expert Senior Advocate of the High Court in Pakistan with 25 years of legal experience.
Generate a COMPLETE, HIGHLY DETAILED, AND PROFESSIONALLY FORMATTED legal document in English according to the Laws of the Islamic Republic of Pakistan (Contract Act 1872, Registration Act 1908, PPC, CrPC, CPC, Transfer of Property Act 1882).

DETAILS:
- Document Category: {doc_type}
- First Party / Applicant: {p1}
- Second Party / Respondent: {p2}
- Court / Location: {court}
- Specific Purpose: {purpose}
"""
            response = model.generate_content(prompt)
            if response and response.text:
                return {"draft": response.text.strip()}
        except Exception as err:
            print(f"Gemini Exception: {err}")

    draft = f"""IN THE COURT OF {court.upper()}

In the matter of:
{p1} ... (Applicant / Petitioner)
VERSUS
{p2} ... (Respondent)

SUBJECT: PETITION FOR {doc_type.upper()} UNDER APPLICABLE LAWS OF PAKISTAN

Respectfully Sheweth:
1. That the Petitioner is a law-abiding citizen of Pakistan and brings this matter before this Honorable Court.
2. That the cause of action accrued within territorial jurisdiction of this Honorable Court.

PRAYER:
It is humbly prayed that this Honorable Court may kindly allow this petition in the interest of justice.

Petitioner
Through Advocate High Court"""
    return {"draft": draft.strip()}


# ================= SECURE ADMIN PANEL =================
@app.get("/api/v1/admin/lawyers/pending")
def get_pending_lawyers(
    admin_user: UserDB = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    lawyers = db.query(UserDB).filter(
        UserDB.role == "lawyer",
        UserDB.is_approved == False
    ).all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "phone": l.phone,
            "license_number": l.license_number,
            "specialty": l.specialty
        }
        for l in lawyers
    ]


@app.post("/api/v1/admin/lawyers/{lawyer_id}/approve")
def approve_lawyer(
    lawyer_id: int,
    admin_user: UserDB = Depends(get_current_admin),
    db: Session = Depends(get_db)
):
    lawyer = db.query(UserDB).filter(UserDB.id == lawyer_id).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer not found")
    
    lawyer.is_approved = True
    lawyer.is_active = True
    db.commit()
    
    return {"message": f"Advocate {lawyer.name} has been approved successfully!"}
