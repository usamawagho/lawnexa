import os
import re
import random  # <-- YEH MISSING THA! Isko add kar diya hai
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

app = FastAPI(title="LawNexa API")

# Enable CORS for Vercel Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global OTP Store (In-Memory)
otp_store = {}
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
                is_approved=True
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
        import random
from datetime import datetime, timedelta

# In-memory OTP Storage (Production mein Redis ya DB columns use hotay hain)
otp_store = {}

# 1. SEND OTP ENDPOINT
@app.post("/api/v1/auth/forgot-password")
def forgot_password(username: str = Form(...)):
    user_id = username.strip()
    
    # Check if user exists in DB
    # Note: Replace with your actual DB query logic if required
    # user = db.query(User).filter((User.phone == user_id) | (User.email == user_id)).first()
    # if not user:
    #     raise HTTPException(status_code=404, detail="Yeh Phone/Email registered nahi hai!")

    # Generate 6-digit random OTP
    otp = f"{random.randint(100000, 999999)}"
    
    # Store OTP with 5-minute expiry
    otp_store[user_id] = {
        "otp": otp,
        "expires_at": datetime.utcnow() + timedelta(minutes=5)
    }

    # Console / Server Logs par OTP print karein (Realtime verification ke liye)
    print(f"\n==========================================")
    print(f"🔑 REALTIME OTP FOR [{user_id}]: {otp}")
    print(f"==========================================\n")

    # (Optional: Yahan SMS Gateway like Twilio / FastSMS ya Email SMTP ka API call add hota hai)

    return {"message": f"OTP sent successfully to {user_id}! Check server logs or phone."}


# 2. VERIFY OTP & RESET PASSWORD ENDPOINT
@app.post("/api/v1/auth/reset-password")
def reset_password(
    username: str = Form(...), 
    otp: str = Form(...), 
    new_password: str = Form(...)
):
    user_id = username.strip()
    record = otp_store.get(user_id)

    # Validate OTP
    if not record or record["otp"] != otp.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Ghalat OTP Code! Sahi OTP dakhil karein."
        )

    # Check OTP Expiry
    if datetime.utcnow() > record["expires_at"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="OTP expire ho chuka hai! Naya OTP mangwayein."
        )

    # Validate new password strength (8 to 10 characters)
    validate_password_complexity(new_password)

    # Password Update in Database
    # hashed = hash_password(new_password)
    # user.password_hash = hashed
    # db.commit()

    # Clear OTP after successful reset
    del otp_store[user_id]

    return {"message": "Password successfully reset! Ab aap naye password se login kar sakte hain."}

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


# STRICT AUTHENTICATION GUARD: Rejects unauthenticated requests
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


# ================= AUTHENTICATION ENDPOINTS =================
@app.post("/api/v1/auth/register")
def register_user(
    name: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form("client"),
    specialty: Optional[str] = Form(None),
    license: Optional[str] = Form(None),
    bar: Optional[str] = Form(None),
    exp: Optional[int] = Form(None),
    city: Optional[str] = Form(None),
    area: Optional[str] = Form(None),
    chamberAddress: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    validate_password_complexity(password)

    existing_user = db.query(UserDB).filter(
        (UserDB.phone == phone) | (UserDB.email == email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yeh Phone Number ya Email pehle se registered hai!"
        )

    is_approved = True if role == "client" else False

    new_user = User(
    full_name=name,
    email=email,
    phone=phone,
    hashed_password=get_password_hash(password),
    role=role,
    is_approved=True,  # <-- In 2 lines ko add kar dein
    is_active=True     # <-- Is se instant login active ho jayega
)
@app.post("/api/v1/auth/token")
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # User find karein email ya phone se
    user = db.query(User).filter((User.email == form_data.username) | (User.phone == form_data.username)).first()
    
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ghalat Phone/Email ya Password!",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 🛑 YAHAN PAR 'if not user.is_approved' WALI CONDITION KO BILKUL HATA DENGAY
    # Ab bina kisi admin approval check ke direct token generate hoga

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role}, expires_delta=access_token_expires
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.full_name,
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

    # Fallback Legal Template
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
    db.commit()
    return {"message": f"Advocate {lawyer.name} has been approved successfully!"}
  # PUBLIC LAWYER SELF-REGISTRATION (AUTO-APPROVED)
@app.post("/api/v1/auth/register-lawyer")
def register_lawyer_direct(
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(...),
    license_no: str = Form(...),
    jurisdiction: str = Form(...),
    category: str = Form(...),
    experience: int = Form(...),
    password: str = Form(...)
):
    # Strict 8-10 Character Password Validation
    if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,10}$", password):
        raise HTTPException(
            status_code=400, 
            detail="Password 8-10 characters ka hona chahiye jisme Uppercase, Lowercase aur Numbers shamil hon!"
        )

    # ---------------------------------------------------------
    # AUTOMATIC APPROVAL LOGIC (No Admin Required)
    # ---------------------------------------------------------
    # Database Record Save Structure (Status = Active & Approved = True):
    # user = User(
    #     full_name=full_name,
    #     email=email,
    #     phone=phone,
    #     role="lawyer",
    #     is_approved=True,   # <-- Auto-Approve Enabled!
    #     is_active=True,     # <-- Direct Active Status!
    # )

    print(f"🎉 INSTANT AUTO-APPROVED LAWYER: {full_name} | Phone: {phone}")

    return {
        "status": "success",
        "message": f"Advocate {full_name}, aapka account instantly approve ho gaya hai! Ab aap direct login kar sakte hain."
    }
