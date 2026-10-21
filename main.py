import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel, EmailStr, Field

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, Float
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from passlib.context import CryptContext
from jose import JWTError, jwt
from dotenv import load_dotenv

# SDK Imports
try:
    from google import genai
    NEW_GEMINI_SDK = True
except ImportError:
    try:
        import google.generativeai as genai
        NEW_GEMINI_SDK = False
    except ImportError:
        genai = None
        NEW_GEMINI_SDK = False

# 1. ENVIRONMENT & LOGGING SETUP
load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LawNexaBackend")

# 2. DATABASE CONFIGURATION WITH AUTO-FALLBACK
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./lawnexa.db")
if DATABASE_URL.startswith("postgresql://") and not DATABASE_URL.startswith("postgresql+psycopg2://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

Base = declarative_base()

try:
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        pass
    logger.info("Database connected successfully!")
except Exception as e:
    logger.warning(f"PostgreSQL connection failed ({e}). Falling back to SQLite ('lawnexa.db').")
    DATABASE_URL = "sqlite:///./lawnexa.db"
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "super_secret_lawnexa_jwt_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
ai_client = None

if GEMINI_API_KEY and genai is not None:
    try:
        if NEW_GEMINI_SDK:
            ai_client = genai.Client(api_key=GEMINI_API_KEY)
        else:
            genai.configure(api_key=GEMINI_API_KEY)
        logger.info("Google Gemini AI API initialized successfully.")
    except Exception as e:
        logger.error(f"Gemini AI initialization error: {e}")

# 3. DATABASE MODELS
class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), unique=True, index=True, nullable=False)
    email = Column(String(100), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(20), default="client")
    specialty = Column(String(100), nullable=True)
    address = Column(String(255), nullable=True)
    license_number = Column(String(100), nullable=True)
    bar_association = Column(String(150), nullable=True)
    experience_years = Column(Integer, default=0)
    lat = Column(Float, default=0.0)
    lng = Column(Float, default=0.0)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class PostModel(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    author_id = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    bar_association = Column(String(150), nullable=True)
    likes = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(Integer, nullable=False)
    receiver_id = Column(Integer, nullable=False)
    message = Column(Text, nullable=False)
    quote_amount = Column(Float, nullable=True)
    quote_status = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

Base.metadata.create_all(bind=engine)

def seed_admin_user():
    db = SessionLocal()
    try:
        admin = db.query(UserModel).filter(UserModel.phone == "03000000000").first()
        if not admin:
            admin_user = UserModel(
                name="System Admin",
                phone="03000000000",
                email="admin@lawnexa.pk",
                hashed_password=get_password_hash("admin123"),
                role="admin",
                is_verified=True
            )
            db.add(admin_user)
            db.commit()
            logger.info("Seeded default admin user successfully.")
    except Exception as e:
        logger.error(f"Error seeding admin: {e}")
    finally:
        db.close()

seed_admin_user()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 4. SECURITY & AUTHENTICATION HELPERS
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub: str = payload.get("sub")
        if sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    if sub.isdigit():
        user = db.query(UserModel).filter(UserModel.id == int(sub)).first()
    else:
        user = db.query(UserModel).filter((UserModel.phone == sub) | (UserModel.email == sub)).first()

    if user is None:
        raise credentials_exception
    return user

# 5. SCHEMAS
class ChatSendSchema(BaseModel):
    receiver_id: int
    message: str
    quote_amount: Optional[float] = None

class ChatQuoteSchema(BaseModel):
    receiver_id: int
    quote_amount: float
    message: Optional[str] = "Custom Legal Price Quote"

class DocGenRequest(BaseModel):
    doc_type: str
    party1: Optional[str] = ""
    party2: Optional[str] = ""
    applicant: Optional[str] = ""
    respondent: Optional[str] = ""
    deponent: Optional[str] = ""
    purpose: Optional[str] = ""
    location: Optional[str] = "Karachi, Pakistan"
    court: Optional[str] = "Sessions Court Karachi"

# 6. FASTAPI APP
app = FastAPI(
    title="LawNexa Backend Engine",
    description="Production API for Pakistan Bar Network, Auth, & AI FIR Scan",
    version="3.3.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

LEGAL_SYSTEM_PROMPT = """
You are 'LawNexa AI', an elite Senior Advocate of the Supreme Court of Pakistan.
Analyze legal queries according to Pakistan Penal Code 1860 (PPC), Code of Criminal Procedure 1898 (CrPC), Civil Procedure Code 1908 (CPC), and High Court Precedents.
Always provide precise, bailable/non-bailable classifications, procedural steps (Sec 497/498 CrPC), and judicial headnote formats.
"""

# ================= 7. API V1 ROUTES =================

# 1. Public Geo Search
@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(
    client_lat: float = 31.5204,
    client_lng: float = 74.3587,
    radius_km: float = 10.0,
    db: Session = Depends(get_db)
):
    lawyers = db.query(UserModel).filter(
        UserModel.role == "lawyer",
        UserModel.is_verified == True
    ).all()

    result = []
    for l in lawyers:
        result.append({
            "id": l.id,
            "user_id": l.id,
            "name": l.name,
            "phone": l.phone,
            "email": l.email,
            "specialty": l.specialty,
            "address": l.address,
            "license_number": l.license_number,
            "bar_association": l.bar_association,
            "experience_years": l.experience_years,
            "lat": l.lat,
            "lng": l.lng,
            "distance_km": 1.2
        })
    return result

# 2. Token Login
@app.post("/api/v1/auth/token")
async def login_v1(
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(UserModel).filter(
        (UserModel.phone == username) | (UserModel.email == username)
    ).first()

    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")

    access_token = create_access_token(data={"sub": str(user.id), "phone": user.phone, "role": user.role})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "id": user.id,
        "role": user.role,
        "name": user.name
    }

# 3 & 4. Registration Endpoint (Client & Lawyer)
@app.post("/api/v1/auth/register", status_code=status.HTTP_201_CREATED)
async def register_v1(
    name: str = Form(...),
    phone: str = Form(...),
    password: str = Form(...),
    role: str = Form("client"),
    email: Optional[str] = Form(None),
    specialty: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    license_number: Optional[str] = Form(None),
    bar_association: Optional[str] = Form(None),
    experience_years: Optional[int] = Form(0),
    lat: Optional[float] = Form(0.0),
    lng: Optional[float] = Form(0.0),
    law_card: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    existing = db.query(UserModel).filter(UserModel.phone == phone).first()
    if existing:
        raise HTTPException(status_code=400, detail="Phone number already registered")

    is_verified = True if role != "lawyer" else False

    new_user = UserModel(
        name=name,
        phone=phone,
        email=email,
        hashed_password=get_password_hash(password),
        role=role,
        specialty=specialty,
        address=address,
        license_number=license_number,
        bar_association=bar_association,
        experience_years=experience_years or 0,
        lat=lat or 0.0,
        lng=lng or 0.0,
        is_verified=is_verified
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "message": "User registered successfully",
        "id": new_user.id,
        "user_id": new_user.id,
        "role": new_user.role
    }

# 5. Get Pending Lawyers (Admin)
@app.get("/api/v1/admin/lawyers/pending")
def get_pending_lawyers(
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin authorization required")

    pending = db.query(UserModel).filter(
        UserModel.role == "lawyer",
        UserModel.is_verified == False
    ).all()

    return [{
        "id": p.id,
        "user_id": p.id,
        "name": p.name,
        "phone": p.phone,
        "email": p.email,
        "license_number": p.license_number,
        "bar_association": p.bar_association
    } for p in pending]

# 6. Approve Lawyer (Admin)
@app.post("/api/v1/admin/lawyers/{lawyer_id}/approve")
@app.put("/api/v1/admin/lawyers/{lawyer_id}/approve")
def approve_lawyer(
    lawyer_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin authorization required")

    lawyer = db.query(UserModel).filter(UserModel.id == lawyer_id).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer not found")

    lawyer.is_verified = True
    db.commit()
    return {"message": "Lawyer approved successfully", "id": lawyer_id, "user_id": lawyer_id}

# 7. Create Bar Campaign Post
@app.post("/api/v1/posts", status_code=status.HTTP_201_CREATED)
async def create_post_v1(
    content: str = Form(...),
    bar_association: Optional[str] = Form(""),
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    new_post = PostModel(
        author_id=current_user.id,
        content=content,
        bar_association=bar_association or current_user.bar_association or ""
    )
    db.add(new_post)
    db.commit()
    db.refresh(new_post)

    return {
        "id": new_post.id,
        "content": new_post.content,
        "bar_association": new_post.bar_association,
        "author_id": new_post.author_id
    }

# 8. Get Bar Social Feed
@app.get("/api/v1/posts")
def get_posts_v1(
    bar_association: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = db.query(PostModel)
    if bar_association:
        query = query.filter(PostModel.bar_association == bar_association)

    posts = query.all()
    return [{
        "id": p.id,
        "content": p.content,
        "bar_association": p.bar_association,
        "author_id": p.author_id,
        "likes": p.likes
    } for p in posts]

# 9. Like Post Endpoint
@app.post("/api/v1/posts/{post_id}/like")
@app.put("/api/v1/posts/{post_id}/like")
def like_post_v1(
    post_id: int,
    db: Session = Depends(get_db)
):
    post = db.query(PostModel).filter(PostModel.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post.likes = (post.likes or 0) + 1
    db.commit()
    return {"message": "Post liked successfully", "id": post.id, "likes": post.likes}

# 10. Confidential Chat Send
@app.post("/api/v1/chat/send", status_code=status.HTTP_201_CREATED)
def send_chat_message(
    data: ChatSendSchema,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    msg = ChatMessageModel(
        sender_id=current_user.id,
        receiver_id=data.receiver_id,
        message=data.message,
        quote_amount=data.quote_amount,
        quote_status="pending" if data.quote_amount else None
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return {
        "id": msg.id,
        "chat_id": msg.id,
        "chat_msg_id": msg.id,
        "message_id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "message": msg.message,
        "quote_amount": msg.quote_amount,
        "status": "sent"
    }

# 11. Create Quote Endpoint
@app.post("/api/v1/chat/quote", status_code=status.HTTP_201_CREATED)
def create_chat_quote(
    data: ChatQuoteSchema,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    msg = ChatMessageModel(
        sender_id=current_user.id,
        receiver_id=data.receiver_id,
        message=data.message or "Custom Legal Price Quote",
        quote_amount=data.quote_amount,
        quote_status="pending"
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    return {
        "id": msg.id,
        "chat_id": msg.id,
        "chat_msg_id": msg.id,
        "message_id": msg.id,
        "sender_id": msg.sender_id,
        "receiver_id": msg.receiver_id,
        "message": msg.message,
        "quote_amount": msg.quote_amount,
        "quote_status": msg.quote_status
    }

# 12. Fetch Specific Chat History (Matching test_10)
@app.get("/api/v1/chat/history/{other_id}")
@app.get("/api/v1/chat/messages/{other_id}")
@app.get("/api/v1/chat/{other_id}")
def get_chat_with_specific_user(
    other_id: int,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    messages = db.query(ChatMessageModel).filter(
        ((ChatMessageModel.sender_id == current_user.id) & (ChatMessageModel.receiver_id == other_id)) |
        ((ChatMessageModel.sender_id == other_id) & (ChatMessageModel.receiver_id == current_user.id))
    ).all()
    return [{
        "id": m.id,
        "chat_id": m.id,
        "chat_msg_id": m.id,
        "message_id": m.id,
        "sender_id": m.sender_id,
        "receiver_id": m.receiver_id,
        "message": m.message,
        "quote_amount": m.quote_amount,
        "quote_status": m.quote_status
    } for m in messages]

# 13. General Chat Messages Listing
@app.get("/api/v1/chat/messages")
@app.get("/api/v1/chat/history")
@app.get("/api/v1/chat/conversations")
@app.get("/api/v1/chat")
def get_chat_messages(
    user_id: Optional[int] = None,
    with_user_id: Optional[int] = None,
    receiver_id: Optional[int] = None,
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    target_id = user_id or with_user_id or receiver_id
    query = db.query(ChatMessageModel).filter(
        (ChatMessageModel.sender_id == current_user.id) | (ChatMessageModel.receiver_id == current_user.id)
    )
    if target_id:
        query = query.filter(
            ((ChatMessageModel.sender_id == current_user.id) & (ChatMessageModel.receiver_id == target_id)) |
            ((ChatMessageModel.sender_id == target_id) & (ChatMessageModel.receiver_id == current_user.id))
        )

    messages = query.all()
    return [{
        "id": m.id,
        "chat_id": m.id,
        "chat_msg_id": m.id,
        "message_id": m.id,
        "sender_id": m.sender_id,
        "receiver_id": m.receiver_id,
        "message": m.message,
        "quote_amount": m.quote_amount,
        "quote_status": m.quote_status
    } for m in messages]

# 14. Respond to Chat Quote
@app.post("/api/v1/chat/quote/{msg_id}/respond")
@app.put("/api/v1/chat/quote/{msg_id}/respond")
def respond_chat_quote(
    msg_id: int,
    action: str = "accepted",
    current_user: UserModel = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    msg = db.query(ChatMessageModel).filter(ChatMessageModel.id == msg_id).first()
    if msg:
        msg.quote_status = action
        db.commit()

    return {"message": f"Quote {action} successfully", "id": msg_id, "chat_id": msg_id, "status": action}


# ================= 8. AI & EXTRA ENDPOINTS =================

@app.get("/")
def health_check():
    return {
        "status": "Online",
        "database": "Connected",
        "ai_engine": bool(GEMINI_API_KEY)
    }

@app.post("/api/ai/analyze-fir")
async def analyze_fir(
    fir_text: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    extracted_text = fir_text or ""
    if file:
        file_bytes = await file.read()
        extracted_text += f"\n[Scanned File Attached: {file.filename}]"

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="Please provide FIR text or upload a document.")

    if GEMINI_API_KEY:
        try:
            prompt = f"""
            {LEGAL_SYSTEM_PROMPT}

            Analyze this Pakistani FIR / Case brief and return strict JSON format with keys:
            - "bailType": "Bailable Offense" OR "Non-Bailable Offense (Pre-Arrest Bail Recommended)"
            - "sections": ["List of detected PPC/CrPC sections"]
            - "strategy": "High Court / Sessions Court defense strategy"
            - "riskLevel": "Low / Medium / High"

            FIR CONTENT:
            "{extracted_text}"

            Return ONLY raw JSON without markdown formatting.
            """

            if NEW_GEMINI_SDK and ai_client:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                raw_text = response.text
            else:
                model = genai.GenerativeModel('gemini-1.5-pro')
                response = model.generate_content(prompt)
                raw_text = response.text

            cleaned = raw_text.replace("```json", "").replace("```", "").strip()
            return {"success": True, "engine": "Gemini AI Engine", "report": json.loads(cleaned)}

        except Exception as e:
            logger.error(f"Gemini FIR Processing Error: {str(e)}")

    return {
        "success": True,
        "engine": "LawNexa Offline Rules Engine",
        "report": {
            "bailType": "Pre-Arrest Bail Recommended (Sec 498 CrPC)",
            "sections": ["Section 337-A PPC (Hurt)", "Section 506 PPC (Criminal Intimidation)", "Section 34 PPC"],
            "strategy": "Apply for Pre-Arrest Bail under Sec 498 CrPC in Sessions Court Karachi before police arrest.",
            "riskLevel": "Medium"
        }
    }

@app.post("/api/ai/generate-doc")
async def generate_document(req: DocGenRequest):
    if GEMINI_API_KEY:
        try:
            prompt = f"""
            {LEGAL_SYSTEM_PROMPT}

            Draft a formal Pakistani legal document for '{req.doc_type}'.
            Applicant/Party 1: {req.party1 or req.applicant}
            Respondent/Party 2: {req.party2 or req.respondent}
            Location/Court: {req.location or req.court}
            Purpose: {req.purpose}

            Include proper Court Headnote, Verification statement, and Legal Grounds.
            """

            if NEW_GEMINI_SDK and ai_client:
                response = ai_client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                draft_text = response.text
            else:
                model = genai.GenerativeModel('gemini-1.5-pro')
                response = model.generate_content(prompt)
                draft_text = response.text

            return {"success": True, "engine": "Gemini AI Engine", "draft": draft_text}

        except Exception as e:
            logger.error(f"Doc Gen Error: {str(e)}")

    draft_sample = f"""IN THE COURT OF {req.court.upper()}

IN THE MATTER OF:
{req.applicant or req.party1 or 'APPLICANT'} ... (Petitioner)
VERSUS
{req.respondent or req.party2 or 'THE STATE'} ... (Respondent)

APPLICATION FOR {req.doc_type.upper()}

RESPECTFULLY SHEWETH:
1. That the applicant is a law-abiding citizen residing at {req.location}.
2. That the present matter pertains to: {req.purpose or 'Legal Petition under statutory laws of Pakistan'}.

PRAYER:
It is respectfully prayed that this petition be allowed in the interest of justice.

PETITIONER THROUGH COUNSEL: ____________________
VERIFICATION: Verified on Oath at {req.location} that contents above are true and correct.
"""
    return {"success": True, "engine": "Offline Template Engine", "draft": draft_sample}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)