import os
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from passlib.context import CryptContext
from jose import JWTError, jwt
import google.generativeai as genai

from database import engine, get_db
from models import Base, User, Lawyer, Appointment, ChatMessage, Post, Like, Comment
from geo_engine import calculate_distance

# Relational tables create karein
Base.metadata.create_all(bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "lawnexa_enterprise_production_jwt_secret_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 Days

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

if GEMINI_API_KEY := os.getenv("GEMINI_API_KEY"):
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="LawNexa Production API", version="4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= PYDANTIC SCHEMAS =================
class UserMe(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: Optional[EmailStr] = None
    phone: str
    role: str
    is_active: bool
    is_approved: bool
    avatar: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None


class LawyerPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    name: str
    specialty: str
    phone: Optional[str] = None
    address: Optional[str] = None
    is_verified: bool
    lat: float
    lng: float
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: int
    rating: float
    distance_km: Optional[float] = None


class UserRegister(BaseModel):
    name: str = Field(..., min_length=2)
    phone: str
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=8)
    role: str = "client"
    specialty: Optional[str] = "General Practice"
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = 0
    city: Optional[str] = "Karachi"
    area: Optional[str] = "Saddar"
    lat: Optional[float] = 31.5204
    lng: Optional[float] = 74.3587


class UserUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    avatar: Optional[str] = None
    city: Optional[str] = None
    area: Optional[str] = None
    chamberAddress: Optional[str] = None
    chamber_address: Optional[str] = None
    specialty: Optional[str] = None
    license: Optional[str] = None
    license_number: Optional[str] = None
    bar: Optional[str] = None
    bar_association: Optional[str] = None
    exp: Optional[int] = None
    experience_years: Optional[int] = None


class ChatMessageCreate(BaseModel):
    receiver_id: int
    message: str
    quote_amount: Optional[float] = None


class ChatMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sender_id: int
    receiver_id: int
    message: str
    quote_amount: Optional[float] = None
    quote_status: str
    timestamp: datetime


class PostCreate(BaseModel):
    content: str
    bar_association: str
    media_url: Optional[str] = None
    media_type: Optional[str] = None


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lawyer_id: int
    bar_association: str
    content: str
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    created_at: datetime


class DocumentRequest(BaseModel):
    type: str = "Agreement"
    party1: str = "First Party"
    party2: str = "Second Party"
    court: str = "Karachi Court"
    purpose: str = "Legal Draft"


# ================= AUTH DEPENDENCIES =================
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session invalid ya expire ho chuka hai. Dobara login karein!",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub or not str(sub).isdecimal():
            raise exc
        user_id = int(sub)
    except (JWTError, ValueError):
        raise exc

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise exc
    return user


# ================= API ENDPOINTS =================

@app.post("/api/v1/auth/register", status_code=201)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    if db.query(User).filter(User.phone == payload.phone.strip()).first():
        raise HTTPException(status_code=400, detail="Yeh Mobile Number pehle se registered hai!")

    role = "lawyer" if payload.role.lower() in ["lawyer", "advocate"] else "client"
    is_approved = True if role == "client" else False

    new_user = User(
        name=payload.name.strip(),
        phone=payload.phone.strip(),
        email=payload.email.lower().strip() if payload.email else None,
        hashed_password=pwd_context.hash(payload.password),
        role=role,
        is_approved=is_approved,
        city=payload.city,
        area=payload.area
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        if role == "lawyer":
            new_lawyer = Lawyer(
                user_id=new_user.id,
                name=payload.name.strip(),
                specialty=payload.specialty or "General Practice",
                phone=payload.phone.strip(),
                is_verified=False,
                lat=payload.lat or 31.5204,
                lng=payload.lng or 74.3587,
                license_number=payload.license_number,
                bar_association=payload.bar_association,
                experience_years=payload.experience_years or 0
            )
            db.add(new_lawyer)
            db.commit()

    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Account creation error! Email/Phone pehle se maujood hai.")

    token = jwt.encode(
        {"sub": str(new_user.id), "role": new_user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {"message": "Account created successfully!", "access_token": token, "role": new_user.role}


@app.post("/api/v1/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    username = form_data.username.strip()
    user = db.query(User).filter((User.phone == username) | (User.email == username.lower())).first()
    
    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Ghalat Phone/Email ya Password!")

    token = jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {"access_token": token, "token_type": "bearer", "role": user.role, "user_id": user.id, "name": user.name}


@app.get("/api/v1/auth/me", response_model=UserMe)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.put("/api/v1/users/profile")
def update_profile(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.name: current_user.name = payload.name.strip()
    if payload.phone: current_user.phone = payload.phone.strip()
    if payload.email: current_user.email = payload.email.strip().lower()
    if payload.avatar: current_user.avatar = payload.avatar
    if payload.city: current_user.city = payload.city
    if payload.area: current_user.area = payload.area

    if current_user.role == "lawyer" and current_user.lawyer_profile:
        lp = current_user.lawyer_profile
        if payload.specialty: lp.specialty = payload.specialty
        if payload.license or payload.license_number: lp.license_number = payload.license or payload.license_number
        if payload.bar or payload.bar_association: lp.bar_association = payload.bar or payload.bar_association
        if payload.exp is not None or payload.experience_years is not None: 
            lp.experience_years = payload.exp if payload.exp is not None else payload.experience_years
        if payload.chamberAddress or payload.chamber_address: 
            lp.address = payload.chamberAddress or payload.chamber_address

    db.commit()
    return {"message": "Profile updated successfully!"}


@app.get("/api/v1/lawyers/nearby", response_model=List[LawyerPublic])
def get_nearby_lawyers(
    client_lat: float = 31.5204,
    client_lng: float = 74.3587,
    radius_km: float = 50.0,
    city: Optional[str] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(Lawyer)
    if city and city != "All":
        query = query.filter(Lawyer.address.ilike(f"%{city}%") | Lawyer.bar_association.ilike(f"%{city}%"))
    
    lawyers = query.offset(skip).limit(limit).all()
    results = []
    
    for l in lawyers:
        dist = calculate_distance(client_lat, client_lng, l.lat, l.lng)
        if dist <= radius_km:
            lp = LawyerPublic.model_validate(l)
            lp.distance_km = dist
            results.append(lp)
            
    return sorted(results, key=lambda x: x.distance_km or 0)


@app.post("/api/v1/chat/send", response_model=ChatMessageOut, status_code=201)
def send_chat(payload: ChatMessageCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat = ChatMessage(
        sender_id=current_user.id,
        receiver_id=payload.receiver_id,
        message=payload.message,
        quote_amount=payload.quote_amount,
        quote_status="pending" if payload.quote_amount else "none"
    )
    db.add(chat)
    db.commit()
    db.refresh(chat)
    return chat


@app.get("/api/v1/chat/history/{receiver_id}", response_model=List[ChatMessageOut])
def chat_history(receiver_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(ChatMessage).filter(
        ((ChatMessage.sender_id == current_user.id) & (ChatMessage.receiver_id == receiver_id)) |
        ((ChatMessage.sender_id == receiver_id) & (ChatMessage.receiver_id == current_user.id))
    ).order_by(ChatMessage.timestamp.asc()).all()


@app.post("/api/v1/chat/quote/{chat_id}/respond")
def respond_quote(chat_id: int, action: str = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    chat = db.query(ChatMessage).filter(ChatMessage.id == chat_id, ChatMessage.receiver_id == current_user.id).first()
    if not chat:
        raise HTTPException(status_code=404, detail="Quotation not found!")
    
    chat.quote_status = "accepted" if action.lower() == "accepted" else "rejected"
    db.commit()
    return {"message": f"Quotation {chat.quote_status} successfully!"}


@app.post("/api/v1/posts", response_model=PostOut, status_code=201)
def create_post(payload: PostCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "lawyer" or not current_user.lawyer_profile:
        raise HTTPException(status_code=403, detail="Only advocates can publish posts!")

    post = Post(
        lawyer_id=current_user.lawyer_profile.id,
        bar_association=payload.bar_association,
        content=payload.content,
        media_url=payload.media_url,
        media_type=payload.media_type
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


@app.get("/api/v1/posts", response_model=List[PostOut])
def get_posts(bar_association: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Post)
    if bar_association:
        query = query.filter(Post.bar_association == bar_association)
    return query.order_by(Post.created_at.desc()).all()


@app.get("/api/v1/admin/lawyers/pending")
def pending_lawyers(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required!")
    return db.query(User).filter(User.role == "lawyer", User.is_approved == False).all()


@app.post("/api/v1/admin/lawyers/{user_id}/approve")
def approve_lawyer(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required!")
    
    user = db.query(User).filter(User.id == user_id).first()
    if user:
        user.is_approved = True
        if user.lawyer_profile:
            user.lawyer_profile.is_verified = True
        db.commit()
        return {"message": "Lawyer approved successfully!"}
    raise HTTPException(status_code=404, detail="User not found!")


@app.post("/api/ai/generate-doc")
def generate_doc(payload: DocumentRequest):
    draft_template = f"""IN THE COURT OF {payload.court.upper()}

In the Matter of:
{payload.party1} ... (First Party)
VERSUS
{payload.party2} ... (Second Party)

SUBJECT: PRELIMINARY DRAFT FOR {payload.type.upper()}

1. This preliminary draft concerns: {payload.purpose}.
2. DISCLAIMER: Legal facts and statutory provisions have NOT been independently verified.
3. This draft requires review and adaptation by a licensed advocate before filing.

PRAYER:
It is respectfully prayed that this petition be granted in accordance with law."""

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"Draft a formal legal document in Pakistan jurisdiction for {payload.type} between {payload.party1} and {payload.party2} for court {payload.court}. Purpose: {payload.purpose}."
            res = model.generate_content(prompt)
            if res.text:
                return {"draft": res.text.strip(), "review_required": True}
        except Exception:
            pass

    return {"draft": draft_template, "review_required": True}