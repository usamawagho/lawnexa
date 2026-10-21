import os
import re
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

# ================= CONFIGURATION & DATABASE =================
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lawnexa.db")

# Fix for Render/Heroku postgres URL scheme
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

app = FastAPI(title="LawNexa Production API", version="2.0")

# CORS Middleware
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
    is_approved = Column(Boolean, default=True)  # True for clients; lawyers wait for admin approval

    # Lawyer Specific Fields
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
    quote_status = Column(String, nullable=True)  # 'pending', 'accepted', 'rejected'
    created_at = Column(DateTime, default=datetime.utcnow)


# Tables Create Karein
Base.metadata.create_all(bind=engine)


# ================= HELPER & VALIDATION FUNCTIONS =================
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
    """Strict Rule: Exactly 8 characters with Capital letter, Small letters, and Number"""
    # 1. Exact 8 Characters Check
    if len(password) != 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password bilkul 8 characters (na kam, na zyada) ka hona zaroori hai!"
        )

    # 2. At least 1 Capital Letter (A-Z)
    if not re.search(r"[A-Z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password mein kam se kam EK capital letter (A-Z) hona zaroori hai!"
        )

    # 3. Small Letters (a-z)
    if not re.search(r"[a-z]", password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password mein small letters (a-z) hone chahiye!"
        )

    # 4. At least 1 Number (0-9)
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


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        if user_id_str is None:
            return None
        user_id = int(user_id_str)
    except (JWTError, ValueError):
        return None

    return db.query(UserDB).filter(UserDB.id == user_id).first()


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
    # 1. Strict Password Validation (Exact 8 chars, Capital, Small, Number)
    validate_password_complexity(password)

    # 2. Duplicate User Check
    existing_user = db.query(UserDB).filter(
        (UserDB.phone == phone) | (UserDB.email == email)
    ).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Yeh Phone Number ya Email pehle se registered hai!"
        )

    # 3. Save User to Database
    is_approved = True if role == "client" else False  # Lawyers wait for admin approval
    hashed_pwd = get_password_hash(password)

    new_user = UserDB(
        name=name,
        phone=phone,
        email=email,
        hashed_password=hashed_pwd,
        role=role,
        is_approved=is_approved,
        specialty=specialty,
        license_number=license,
        bar_association=bar,
        experience_years=exp,
        city=city,
        area=area,
        chamber_address=chamberAddress
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User Account Successfully Created!",
        "user_id": new_user.id,
        "role": new_user.role,
        "is_approved": new_user.is_approved
    }


@app.post("/api/v1/auth/token")
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    username = form_data.username  # Phone or Email

    # Search User by Phone or Email
    user = db.query(UserDB).filter(
        (UserDB.phone == username) | (UserDB.email == username)
    ).first()

    # Check User existence and Password Match
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Ghalat Phone/Email ya Password! Dobara koshish karein.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate JWT Token
    access_token = create_access_token(data={"sub": str(user.id), "role": user.role})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "name": user.name,
        "role": user.role
    }


# ================= LAWYER DIRECTORY =================
@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(db: Session = Depends(get_db)):
    # Fetch approved lawyers only
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


# ================= SOCIAL POSTS =================
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
    current_user: Optional[UserDB] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    author_id = current_user.id if current_user else 1
    new_post = PostDB(content=content, bar_association=bar_association, author_id=author_id)
    db.add(new_post)
    db.commit()
    db.refresh(new_post)
    return {"message": "Post published successfully!", "id": new_post.id}


@app.post("/api/v1/posts/{post_id}/like")
def like_post(post_id: int, db: Session = Depends(get_db)):
    post = db.query(PostDB).filter(PostDB.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    post.likes += 1
    db.commit()
    return {"likes": post.likes}


# ================= CONFIDENTIAL CHAT & QUOTES =================
@app.post("/api/v1/chat/send")
def send_chat_message(
    payload: dict,
    current_user: Optional[UserDB] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    sender_id = current_user.id if current_user else 1
    receiver_id = payload.get("receiver_id")
    msg_text = payload.get("message")
    quote_amt = payload.get("quote_amount")

    new_msg = MessageDB(
        sender_id=sender_id,
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
    current_user: Optional[UserDB] = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    my_id = current_user.id if current_user else 1
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
    db: Session = Depends(get_db)
):
    msg = db.query(MessageDB).filter(MessageDB.id == msg_id).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Quote message not found")
    msg.quote_status = action
    db.commit()
    return {"message": f"Quote status updated to {action}"}


# ================= AI LEGAL TOOLS =================
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
    doc_type = payload.get("doc_type", "Petition")
    p1 = payload.get("party1", "Petitioner")
    p2 = payload.get("party2", "Respondent")
    court = payload.get("court", "Sessions Court Karachi")

    draft = f"""
IN THE COURT OF {court.upper()}

In the matter of:
{p1} ... (Applicant / Petitioner)
VERSUS
{p2} ... (Respondent / State)

SUBJECT: PETITION FOR {doc_type.upper()} UNDER APPLICABLE LAW.

Respectfully Sheweth:
1. That the applicant is a respectable citizen of Pakistan and has been falsely implicated.
2. That there is no independent witness to support the prosecution story.
3. That the applicant is ready to furnish reliable surety bonds to the satisfaction of this Honorable Court.

PRAYER:
It is humbly prayed that this Application/Petition may kindly be allowed in the interest of justice.

Advocate for Applicant
    """
    return {"draft": draft.strip()}


# ================= ADMIN PANEL =================
@app.get("/api/v1/admin/lawyers/pending")
def get_pending_lawyers(db: Session = Depends(get_db)):
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
def approve_lawyer(lawyer_id: int, db: Session = Depends(get_db)):
    lawyer = db.query(UserDB).filter(UserDB.id == lawyer_id).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer not found")
    lawyer.is_approved = True
    db.commit()
    return {"message": "Lawyer approved successfully!"}
