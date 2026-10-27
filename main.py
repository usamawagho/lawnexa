from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import models, schemas, auth, database, json

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="LawNexa API", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatMessage(BaseModel):
    role: str
    content: str

class LegalResearchRequest(BaseModel):
    history: List[ChatMessage]
    user_input: str
    language: Optional[str] = "roman_urdu"

@app.post("/api/register", status_code=status.HTTP_201_CREATED)
def register_user(user_data: schemas.UserCreate, db: Session = Depends(database.get_db)):
    existing = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    if user_data.role == "advocate" and len(user_data.specializations) > 3:
        raise HTTPException(status_code=400, detail="Maximum 3 specializations allowed.")

    hashed = auth.get_password_hash(user_data.password)
    user = models.User(
        full_name=user_data.full_name,
        email=user_data.email,
        phone=user_data.phone,
        address=user_data.address,
        hashed_password=hashed,
        role=user_data.role,
        city=user_data.city,
        specializations=json.dumps(user_data.specializations) if user_data.specializations else "[]",
        bar_council_no=user_data.bar_council_no,
        chamber_address=user_data.chamber_address,
        experience_years=user_data.experience_years,
        consultation_fee=user_data.consultation_fee
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = auth.create_access_token(data={"sub": user.email, "role": user.role})
    return {"status": "success", "token": token, "user": {"id": user.id, "email": user.email, "role": user.role}}

@app.post("/api/login")
def login_user(user_data: schemas.UserLogin, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = auth.create_access_token(data={"sub": user.email, "role": user.role})
    return {"token": token, "user": {"id": user.id, "email": user.email, "role": user.role}}

@app.post("/api/ai-legal-research")
async def process_legal_research(req: LegalResearchRequest):
    turn_count = len(req.history)
    if turn_count < 3:
        return {
            "status": "clarifying",
            "reply": "Aapke incident facts ke mutabiq: Kya is haadse me koi physical injury aayi hai ya sirf vehicle/property damage hua hai?",
            "case_brief": None
        }
    else:
        return {
            "status": "completed",
            "reply": "Preliminary legal research completed.",
            "case_brief": {
                "category": "Criminal & Traffic Law",
                "applicable_laws": ["PPC Section 279 (Rash Driving)", "PPC Section 427 (Mischief & Damage)"],
                "summary": req.user_input,
                "recommended_specialty": "Criminal & Traffic Law Specialist"
            }
        }
