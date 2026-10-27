"""
LawNexa Core FastAPI Backend Application
"""
import os
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, Depends, HTTPException, status, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from jose import JWTError, jwt

from database import get_db, engine, Base
import models
from geo_engine import calculate_distance

# Create tables if not exists
Base.metadata.create_all(bind=engine)

SECRET_KEY = os.getenv("SECRET_KEY", "LAWNEXA_SUPER_SECRET_KEY_32_CHARS_LONG_PROD")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

app = FastAPI(title="LawNexa Backend API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(request: Request, token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    auth_token = token or request.cookies.get("lawnexa_token")
    if not auth_token:
        raise HTTPException(status_code=401, detail="Authentication token missing")
    try:
        payload = jwt.decode(auth_token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = int(payload.get("sub"))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid auth token")
    
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="User not active")
    return user

class RegisterSchema(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: models.UserRole
    phone: Optional[str] = None
    city: Optional[str] = "Lahore"
    area: Optional[str] = None
    address: Optional[str] = None
    license_number: Optional[str] = None
    bar_association: Optional[str] = None
    experience_years: Optional[int] = None
    jurisdiction: Optional[str] = None
    specialization: Optional[str] = None

@app.get("/health")
def health_check():
    return {"status": "online", "platform": "LawNexa Pakistan"}

@app.get("/")
def read_index():
    if os.path.exists("index.html"):
        return FileResponse("index.html")
    return {"message": "LawNexa API Online"}

@app.get("/admin")
def read_admin():
    if os.path.exists("admin.html"):
        return FileResponse("admin.html")
    return {"message": "Admin Portal UI"}

@app.post("/api/v1/auth/register")
def register(data: RegisterSchema, response: Response, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    is_approved = True if data.role in [models.UserRole.CLIENT, models.UserRole.ADMIN] else False
    user = models.User(
        name=data.name,
        email=data.email,
        phone=data.phone,
        password_hash=get_password_hash(data.password),
        role=data.role,
        city=data.city,
        area=data.area,
        address=data.address,
        is_approved=is_approved,
        license_number=data.license_number,
        bar_association=data.bar_association,
        experience_years=data.experience_years,
        jurisdiction=data.jurisdiction,
        specialization=data.specialization
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    response.set_cookie(key="lawnexa_token", value=token, httponly=True, samesite="lax")
    return {"message": "Registered successfully", "access_token": token, "user_id": user.id}

@app.post("/api/v1/auth/token")
def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect email or password")
    
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    response.set_cookie(key="lawnexa_token", value=token, httponly=True, samesite="lax")
    return {"access_token": token, "token_type": "bearer"}

@app.get("/api/v1/auth/me")
def get_me(user: models.User = Depends(get_current_user)):
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "is_approved": user.is_approved
    }

@app.get("/api/v1/admin/overview")
def admin_overview(admin: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if admin.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin authorization required")
    
    clients = db.query(models.User).filter(models.User.role == models.UserRole.CLIENT).count()
    lawyers = db.query(models.User).filter(models.User.role == models.UserRole.LAWYER).count()
    pending = db.query(models.User).filter(models.User.role == models.UserRole.LAWYER, models.User.is_approved == False).count()
    escrow_held = db.query(models.EscrowTransaction).filter(models.EscrowTransaction.status == "held").all()
    total_escrow = sum(t.amount for t in escrow_held)
    
    return {
        "total_clients": clients,
        "total_lawyers": lawyers,
        "pending_lawyers": pending,
        "escrow_balance": f"PKR {total_escrow:,.2f}"
    }

@app.get("/api/v1/admin/lawyers/pending")
def pending_lawyers(admin: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if admin.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin authorization required")
    return db.query(models.User).filter(models.User.role == models.UserRole.LAWYER, models.User.is_approved == False).all()

@app.post("/api/v1/admin/lawyers/{lawyer_id}/{action}")
def review_lawyer(lawyer_id: int, action: str, admin: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if admin.role != models.UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Admin authorization required")
    lawyer = db.query(models.User).filter(models.User.id == lawyer_id, models.User.role == models.UserRole.LAWYER).first()
    if not lawyer:
        raise HTTPException(status_code=404, detail="Lawyer not found")
    
    if action == "approve":
        lawyer.is_approved = True
    elif action == "reject":
        lawyer.is_active = False
    db.commit()
    return {"status": "success", "action": action}

@app.post("/api/v1/payments/safepay/webhook")
async def safepay_webhook(request: Request, db: Session = Depends(get_db)):
    secret = os.getenv("SAFEPAY_WEBHOOK_SECRET", "sandbox_secret")
    signature = request.headers.get("x-safepay-signature")
    body = await request.body()
    
    computed_sig = hmac.new(secret.encode(), body, hashlib.sha512).hexdigest()
    if signature != computed_sig:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    
    data = await request.json()
    if data.get("type") == "payment.succeeded":
        tracker = data.get("data", {}).get("tracker")
        txn = db.query(models.EscrowTransaction).filter(models.EscrowTransaction.transaction_id == tracker).first()
        if txn:
            txn.status = "held"
            db.commit()
    return {"status": "processed"}
