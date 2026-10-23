import os
import shutil
from datetime import datetime, timedelta
from typing import Optional, List, Union

from fastapi import FastAPI, Depends, HTTPException, status, Form, File, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt
import google.generativeai as genai

from database import engine, Base, get_db
from models import User, Lawyer, Appointment, ChatMessage, Post, Like, Comment
from geo_engine import calculate_distance

# Initialize DB Tables
Base.metadata.create_all(bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "lawnexa_secure_production_jwt_secret_key_2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

if GEMINI_API_KEY := os.getenv("GEMINI_API_KEY"):
    genai.configure(api_key=GEMINI_API_KEY)

app = FastAPI(title="LawNexa Full System API", version="4.5")

# Configure CORS Allowlist
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas
class UserResponse(BaseModel):
    id: int
    name: str
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    role: str
    is_active: bool
    is_approved: bool
    avatar: Optional[str] = None

    class Config:
        orm_mode = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    name: str

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

class BookingCreate(BaseModel):
    lawyer_id: int
    date: str
    time: str
    summary: str

class ChatSendRequest(BaseModel):
    receiver_id: int
    message: str
    quote_amount: Optional[float] = None

class DocumentRequest(BaseModel):
    doc_type: str = Field(alias="type", default="Agreement")
    party1: str = "First Party"
    party2: str = "Second Party"
    court: str = "Karachi, Pakistan"
    purpose: str = "Legal Representation"

# Seed Admin User on Application Startup
@app.on_event("startup")
def seed_admin_user():
    db = next(get_db())
    try:
        admin_phone = "03000000000"
        admin_user = db.query(User).filter(User.phone == admin_phone).first()
        if not admin_user:
            admin = User(
                name="System Administrator",
                phone=admin_phone,
                email="admin@lawnexa.pk",
                hashed_password=pwd_context.hash("admin123"),
                role="admin",
                is_approved=True,
                is_active=True
            )
            db.add(admin)
            db.commit()
    finally:
        db.close()

# Auth Dependencies
def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    unauthorized_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session expired or invalid token.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if user_id is None:
            raise unauthorized_exc
    except JWTError:
        raise unauthorized_exc

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None or not user.is_active:
        raise unauthorized_exc
    return user

def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required.")
    return current_user

# ================= AUTH & USER ROUTES =================

@app.get("/api/v1/auth/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@app.post("/api/v1/auth/register", status_code=201)
async def register(
    name: str = Form(...),
    password: str = Form(...),
    phone: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    role: str = Form("client"),
    specialty: Optional[str] = Form(None),
    address: Optional[str] = Form(None),
    license_number: Optional[str] = Form(None),
    bar_association: Optional[str] = Form(None),
    experience_years: Optional[int] = Form(0),
    lat: Optional[float] = Form(31.5204),
    lng: Optional[float] = Form(74.3587),
    law_card: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db)
):
    if not email and not phone:
        raise HTTPException(status_code=400, detail="Phone number or Email is required.")

    if phone and db.query(User).filter(User.phone == phone.strip()).first():
        raise HTTPException(status_code=400, detail="Phone number already registered.")
    
    if email and db.query(User).filter(User.email == email.strip().lower()).first():
        raise HTTPException(status_code=400, detail="Email address already registered.")

    assigned_role = "lawyer" if role.lower() in ["lawyer", "advocate", "vakeel"] else "client"
    # Lawyer registrations default to unapproved (is_approved=False)
    is_approved = False if assigned_role == "lawyer" else True

    new_user = User(
        name=name.strip(),
        phone=phone.strip() if phone else None,
        email=email.strip().lower() if email else None,
        hashed_password=pwd_context.hash(password.strip()),
        role=assigned_role,
        is_approved=is_approved,
        is_active=True
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    card_url = None
    if law_card and assigned_role == "lawyer":
        os.makedirs("uploads", exist_ok=True)
        card_url = f"uploads/law_card_{new_user.id}_{law_card.filename}"
        with open(card_url, "wb") as buffer:
            shutil.copyfileobj(law_card.file, buffer)

    if assigned_role == "lawyer":
        new_lawyer = Lawyer(
            user_id=new_user.id,
            name=new_user.name,
            specialty=specialty or "General Practice",
            address=address or "Chamber",
            phone=new_user.phone,
            law_card_url=card_url,
            is_verified=False,
            lat=lat or 31.5204,
            lng=lng or 74.3587,
            license_number=license_number,
            bar_association=bar_association,
            experience_years=experience_years or 0
        )
        db.add(new_lawyer)
        db.commit()

    token = jwt.encode(
        {"sub": str(new_user.id), "role": new_user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )

    return {"message": "Account created successfully!", "access_token": token, "role": new_user.role, "user_id": new_user.id}

@app.post("/api/v1/auth/token", response_model=TokenResponse)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(
        (User.email == form_data.username.lower()) | (User.phone == form_data.username)
    ).first()

    if not user or not pwd_context.verify(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    token = jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user.role,
        "user_id": user.id,
        "name": user.name
    }

@app.put("/api/v1/users/profile")
def update_profile(payload: UserUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    update_data = payload.dict(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(current_user, key):
            setattr(current_user, key, value)
    
    if current_user.role == "lawyer" and current_user.lawyer_profile:
        for key in ["specialty", "license_number", "bar_association", "experience_years"]:
            if key in update_data:
                setattr(current_user.lawyer_profile, key, update_data[key])
                
    db.commit()
    return {"message": "Profile updated!", "user_id": current_user.id}

# ================= ADMIN LAWYER APPROVAL =================

@app.get("/api/v1/admin/lawyers/pending")
def list_pending_lawyers(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    pending_users = db.query(User).filter(User.role == "lawyer", User.is_approved == False).all()
    results = []
    for u in pending_users:
        lawyer = u.lawyer_profile
        results.append({
            "id": lawyer.id if lawyer else u.id,
            "user_id": u.id,
            "name": u.name,
            "phone": u.phone,
            "email": u.email,
            "specialty": lawyer.specialty if lawyer else "General",
            "license_number": lawyer.license_number if lawyer else "",
            "bar_association": lawyer.bar_association if lawyer else "",
            "experience_years": lawyer.experience_years if lawyer else 0,
            "law_card_url": lawyer.law_card_url if lawyer else None
        })
    return results

@app.post("/api/v1/admin/lawyers/{lawyer_id}/approve")
def approve_lawyer(lawyer_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    lawyer = db.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
    if not lawyer:
        user = db.query(User).filter(User.id == lawyer_id, User.role == "lawyer").first()
        if user:
            user.is_approved = True
            if user.lawyer_profile:
                user.lawyer_profile.is_verified = True
            db.commit()
            return {"message": f"Lawyer {user.name} approved successfully."}
        raise HTTPException(status_code=44, detail="Lawyer profile not found.")
    
    lawyer.is_verified = True
    if lawyer.user:
        lawyer.user.is_approved = True
    db.commit()
    return {"message": f"Advocate {lawyer.name} approved successfully."}

@app.post("/api/v1/admin/lawyers/{lawyer_id}/reject")
def reject_lawyer(lawyer_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    lawyer = db.query(Lawyer).filter(Lawyer.id == lawyer_id).first()
    if lawyer and lawyer.user:
        db.delete(lawyer.user)
        db.commit()
        return {"message": "Lawyer application rejected and account removed."}
    raise HTTPException(status_code=404, detail="Lawyer application not found.")

# ================= DIRECTORY & HAVERSINE SEARCH =================

@app.get("/api/v1/lawyers/nearby")
def get_nearby_lawyers(
    client_lat: Optional[float] = Query(None),
    client_lng: Optional[float] = Query(None),
    radius_km: Optional[float] = Query(10.0),
    city: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(Lawyer).join(User).filter(User.is_approved == True, Lawyer.is_verified == True)
    if city:
        query = query.filter(Lawyer.city.ilike(f"%{city}%"))
    if area:
        query = query.filter(Lawyer.area.ilike(f"%{area}%"))
    
    lawyers = query.all()
    results = []

    for l in lawyers:
        lawyer_dict = {
            "id": l.id,
            "user_id": l.user_id,
            "name": l.name,
            "specialty": l.specialty,
            "address": l.address,
            "city": l.city,
            "area": l.area,
            "experience": l.experience_years,
            "bar_association": l.bar_association,
            "license_number": l.license_number,
            "lat": l.lat,
            "lng": l.lng,
            "avatar": l.user.avatar if l.user else None
        }

        if client_lat is not None and client_lng is not None:
            dist = calculate_distance(client_lat, client_lng, l.lat, l.lng)
            if dist <= radius_km:
                lawyer_dict["distance_km"] = dist
                results.append(lawyer_dict)
        else:
            results.append(lawyer_dict)

    if client_lat is not None and client_lng is not None:
        results.sort(key=lambda x: x.get("distance_km", 0))

    return results

# ================= BOOKINGS / APPOINTMENTS =================

@app.post("/api/v1/bookings", status_code=201)
def create_booking(payload: BookingCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    lawyer = db.query(Lawyer).filter(Lawyer.id == payload.lawyer_id).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Selected lawyer profile does not exist.")
    
    appointment = Appointment(
        client_id=current_user.id,
        lawyer_id=lawyer.id,
        booking_date=payload.date,
        time_slot=payload.time,
        case_summary=payload.summary,
        status="pending"
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return {"message": "Booking request submitted successfully!", "booking_id": appointment.id, "status": "pending"}

@app.get("/api/v1/bookings")
def list_bookings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.role == "lawyer" and current_user.lawyer_profile:
        bookings = db.query(Appointment).filter(Appointment.lawyer_id == current_user.lawyer_profile.id).all()
    else:
        bookings = db.query(Appointment).filter(Appointment.client_id == current_user.id).all()

    results = []
    for b in bookings:
        results.append({
            "id": b.id,
            "clientName": b.client.name if b.client else "Client",
            "lawyerName": b.lawyer.name if b.lawyer else "Advocate",
            "date": b.booking_date,
            "time": b.time_slot,
            "summary": b.case_summary,
            "status": b.status
        })
    return results

@app.post("/api/v1/bookings/{booking_id}/respond")
def respond_booking(booking_id: int, action: str = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    booking = db.query(Appointment).filter(Appointment.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking request not found.")
    
    booking.status = "Accepted" if action.lower() in ["accept", "accepted"] else "Declined"
    db.commit()
    return {"message": f"Booking {booking.status} successfully.", "booking_id": booking.id, "status": booking.status}

# ================= COMMUNITY FORUM POSTS =================

@app.post("/api/v1/posts", status_code=201)
def create_post(
    content: str = Form(...),
    bar_association: Optional[str] = Form("Lahore High Court Bar Association"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if current_user.role != "lawyer" or not current_user.lawyer_profile:
        raise HTTPException(status_code=403, detail="Only verified advocates can publish posts.")
    
    post = Post(
        lawyer_id=current_user.lawyer_profile.id,
        bar_association=bar_association or current_user.lawyer_profile.bar_association or "High Court Bar",
        content=content
    )
    db.add(post)
    db.commit()
    db.refresh(post)
    return {"message": "Post created successfully!", "id": post.id}

@app.get("/api/v1/posts")
def get_posts(bar_association: Optional[str] = Query(None), db: Session = Depends(get_db)):
    query = db.query(Post)
    if bar_association:
        query = query.filter(Post.bar_association.ilike(f"%{bar_association}%"))
    posts = query.order_by(Post.created_at.desc()).all()
    
    results = []
    for p in posts:
        results.append({
            "id": p.id,
            "author": p.lawyer.name if p.lawyer else "Advocate",
            "authorRole": p.lawyer.specialty if p.lawyer else "Advocate",
            "authorAvatar": p.lawyer.user.avatar if (p.lawyer and p.lawyer.user) else None,
            "category": p.bar_association,
            "content": p.content,
            "likes": len(p.likes),
            "timestamp": p.created_at.strftime("%Y-%m-%d %H:%M")
        })
    return results

@app.post("/api/v1/posts/{post_id}/like")
def like_post(post_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing_like = db.query(Like).filter(Like.post_id == post_id, Like.user_id == current_user.id).first()
    if existing_like:
        db.delete(existing_like)
        db.commit()
        return {"message": "Unliked post."}
    
    new_like = Like(post_id=post_id, user_id=current_user.id)
    db.add(new_like)
    db.commit()
    return {"message": "Liked post."}

# ================= CHAT & PRICE QUOTATION =================

@app.post("/api/v1/chat/send", status_code=201)
def send_chat_message(payload: ChatSendRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    msg = ChatMessage(
        sender_id=current_user.id,
        receiver_id=payload.receiver_id,
        message=payload.message,
        quote_amount=payload.quote_amount,
        quote_status="pending" if payload.quote_amount else "none"
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return {"message": "Message sent!", "chat_id": msg.id}

@app.get("/api/v1/chat/history/{user_id}")
def get_chat_history(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    messages = db.query(ChatMessage).filter(
        ((ChatMessage.sender_id == current_user.id) & (ChatMessage.receiver_id == user_id)) |
        ((ChatMessage.sender_id == user_id) & (ChatMessage.receiver_id == current_user.id))
    ).order_by(ChatMessage.timestamp.asc()).all()
    
    results = []
    for m in messages:
        results.append({
            "id": m.id,
            "sender_id": m.sender_id,
            "receiver_id": m.receiver_id,
            "message": m.message,
            "quote_amount": m.quote_amount,
            "quote_status": m.quote_status,
            "timestamp": m.timestamp.strftime("%H:%M")
        })
    return results

@app.post("/api/v1/chat/quote/{chat_id}/respond")
def respond_quote(chat_id: int, action: str = Query(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    msg = db.query(ChatMessage).filter(ChatMessage.id == chat_id).first()
    if not msg or not msg.quote_amount:
        raise HTTPException(status_code=404, detail="Quotation message not found.")
    
    msg.quote_status = "accepted" if action.lower() in ["accept", "accepted"] else "rejected"
    db.commit()
    return {"message": f"Quotation {msg.quote_status} successfully.", "chat_id": msg.id}

# ================= AI ASSISTANT & DOCUMENT DRAFTER =================

@app.post("/api/v1/ai/analyze-fir")
def analyze_fir(text: str = Form(...)):
    disclaimer = "LEGAL DISCLAIMER: This AI FIR analysis is for informational assistance only and does not replace qualified advocate advice."
    return {
        "disclaimer": disclaimer,
        "bailType": "Pre-Arrest Bail (Section 498 CrPC)",
        "strategy": f"Based on FIR text: '{text[:100]}...', recommended strategy is to move an application for interim pre-arrest bail before District & Sessions Court."
    }

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
It is respectfully prayed that this petition be granted in accordance with law.

[LEGAL DISCLAIMER: Draft generated by LawNexa AI. Must be reviewed by Advocate before court submission.]"""

    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"Draft a professional legal document in Pakistan jurisdiction for: {payload.doc_type}. Parties: {payload.party1} and {payload.party2}. Court: {payload.court}. Purpose: {payload.purpose}. Ensure formal legal tone."
            response = model.generate_content(prompt)
            if response.text:
                return {"draft": response.text.strip(), "ai_generated": True}
        except Exception:
            pass

    return {"draft": draft_template, "ai_generated": False}