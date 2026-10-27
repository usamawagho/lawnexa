from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import models, schemas, auth, database, json

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(title="LawNexa API", version="2.7.0")

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
        raise HTTPException(status_code=400, detail="Email address pehle se registered hai.")

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
    return {
        "status": "success", 
        "token": token, 
        "user": {
            "id": user.id, 
            "email": user.email, 
            "role": user.role,
            "full_name": user.full_name,
            "phone": user.phone,
            "address": user.address,
            "city": user.city,
            "profile_image": user.profile_image
        }
    }

@app.post("/api/login")
def login_user(user_data: schemas.UserLogin, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == user_data.email).first()
    if not user or not auth.verify_password(user_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email address or password.")

    token = auth.create_access_token(data={"sub": user.email, "role": user.role})
    return {
        "token": token, 
        "user": {
            "id": user.id, 
            "email": user.email, 
            "role": user.role,
            "full_name": user.full_name,
            "phone": user.phone,
            "address": user.address,
            "city": user.city,
            "profile_image": user.profile_image
        }
    }

@app.get("/api/profile")
def get_user_profile(email: str, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "address": user.address,
        "role": user.role,
        "profile_image": user.profile_image,
        "city": user.city,
        "specializations": json.loads(user.specializations) if user.specializations else [],
        "bar_council_no": user.bar_council_no,
        "chamber_address": user.chamber_address,
        "experience_years": user.experience_years,
        "consultation_fee": user.consultation_fee
    }

@app.put("/api/profile")
def update_user_profile(email: str, data: schemas.UserProfileUpdate, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.full_name is not None:
        user.full_name = data.full_name
    if data.address is not None:
        user.address = data.address
    if data.city is not None:
        user.city = data.city
    if data.profile_image is not None:
        user.profile_image = data.profile_image
    if data.specializations is not None:
        user.specializations = json.dumps(data.specializations)
    if data.bar_council_no is not None:
        user.bar_council_no = data.bar_council_no
    if data.chamber_address is not None:
        user.chamber_address = data.chamber_address
    if data.experience_years is not None:
        user.experience_years = data.experience_years
    if data.consultation_fee is not None:
        user.consultation_fee = data.consultation_fee

    db.commit()
    db.refresh(user)

    return {"status": "success", "message": "Profile updated successfully"}

# --- LEGAL DOCUMENTS API ENDPOINTS ---

@app.get("/api/documents/templates")
def get_document_templates():
    return [
        {
            "id": "kiraya_nama",
            "name": "Rent Agreement (کرایہ نامہ)",
            "description": "Standard tenancy agreement for residential/commercial property in Pakistan.",
            "fields": [
                {"name": "landlord_name", "label": "Landlord Name (مالک مکان)", "type": "text", "placeholder": "Ahmad Raza"},
                {"name": "landlord_cnic", "label": "Landlord CNIC", "type": "text", "placeholder": "42101-1234567-1"},
                {"name": "tenant_name", "label": "Tenant Name (کرایہ دار)", "type": "text", "placeholder": "Muhammad Usama"},
                {"name": "tenant_cnic", "label": "Tenant CNIC", "type": "text", "placeholder": "42101-7654321-2"},
                {"name": "property_address", "label": "Property Address (پتہ)", "type": "text", "placeholder": "House No. 12, Block 4, Gulshan, Karachi"},
                {"name": "monthly_rent", "label": "Monthly Rent (PKR)", "type": "number", "placeholder": "35000"},
                {"name": "security_deposit", "label": "Advance/Deposit (PKR)", "type": "number", "placeholder": "70000"},
                {"name": "commencement_date", "label": "Agreement Start Date", "type": "date", "placeholder": ""},
                {"name": "duration_months", "label": "Duration (Months)", "type": "number", "placeholder": "11"}
            ]
        },
        {
            "id": "vehicle_sale",
            "name": "Vehicle Sale Agreement (معاہدہ فروخت گاڑی)",
            "description": "Legally binding agreement for selling or purchasing cars, bikes, or commercial vehicles.",
            "fields": [
                {"name": "seller_name", "label": "Seller Name (بیچنے والا)", "type": "text", "placeholder": "Ali Hassan"},
                {"name": "seller_cnic", "label": "Seller CNIC", "type": "text", "placeholder": "42101-1111111-1"},
                {"name": "buyer_name", "label": "Buyer Name (خریدنے والا)", "type": "text", "placeholder": "Bilal Ahmed"},
                {"name": "buyer_cnic", "label": "Buyer CNIC", "type": "text", "placeholder": "42101-2222222-2"},
                {"name": "vehicle_make_model", "label": "Vehicle Model & Name", "type": "text", "placeholder": "Honda Civic 2021"},
                {"name": "reg_no", "label": "Registration No", "type": "text", "placeholder": "KBL-1234"},
                {"name": "engine_no", "label": "Engine No", "type": "text", "placeholder": "R18A-987654"},
                {"name": "chassis_no", "label": "Chassis No", "type": "text", "placeholder": "N32-456789"},
                {"name": "sale_amount", "label": "Total Price (PKR)", "type": "number", "placeholder": "3200000"}
            ]
        },
        {
            "id": "bail_application",
            "name": "Bail Application (درخواست ضمانت)",
            "description": "Criminal bail petition format under Criminal Procedure Code (CrPC).",
            "fields": [
                {"name": "court_name", "label": "Court Name", "type": "text", "placeholder": "In the Court of Judicial Magistrate, Karachi"},
                {"name": "applicant_name", "label": "Applicant/Accused Name", "type": "text", "placeholder": "Tariq Mahmood"},
                {"name": "fir_no", "label": "FIR No", "type": "text", "placeholder": "124/2026"},
                {"name": "police_station", "label": "Police Station (تھانہ)", "type": "text", "placeholder": "PS Ferozabad"},
                {"name": "offense_sections", "label": "PPC Sections", "type": "text", "placeholder": "PPC 379 / 411"},
                {"name": "bail_grounds", "label": "Grounds for Bail", "type": "textarea", "placeholder": "Applicant is innocent, falsely implicated due to rivalry, ready to furnish surety bonds."}
            ]
        },
        {
            "id": "cheque_notice",
            "name": "Cheque Bounce Legal Notice (نوٹس عدم ادائیگی چیک)",
            "description": "Legal notice for dishonored cheque under Section 489-F PPC & Negotiable Instruments Act.",
            "fields": [
                {"name": "sender_name", "label": "Payee Name (نوٹس دہندہ)", "type": "text", "placeholder": "Zubair Khan"},
                {"name": "recipient_name", "label": "Drawer Name (خلاف ورزی کنندہ)", "type": "text", "placeholder": "Kamran Sheikh"},
                {"name": "cheque_no", "label": "Cheque Number", "type": "text", "placeholder": "CHK-99887766"},
                {"name": "cheque_amount", "label": "Cheque Amount (PKR)", "type": "number", "placeholder": "500000"},
                {"name": "bank_name", "label": "Bank & Branch", "type": "text", "placeholder": "Meezan Bank, Main Branch"},
                {"name": "notice_days", "label": "Demand Notice Period (Days)", "type": "number", "placeholder": "14"}
            ]
        },
        {
            "id": "vakalatnama",
            "name": "Vakalatnama (وکالت نامہ)",
            "description": "Official legal power of attorney authorizing advocate to represent client in court.",
            "fields": [
                {"name": "court_title", "label": "Honourable Court", "type": "text", "placeholder": "High Court of Sindh at Karachi"},
                {"name": "case_title", "label": "Case Title / Suits No", "type": "text", "placeholder": "Muhammad Usama Vs State"},
                {"name": "client_name", "label": "Client Name (سائل)", "type": "text", "placeholder": "Muhammad Usama"},
                {"name": "lawyer_name", "label": "Advocate Name (وکیل)", "type": "text", "placeholder": "Adv. Sarah Khan"},
                {"name": "bar_reg", "label": "Advocate Bar Reg No", "type": "text", "placeholder": "BC-9876/SHC"}
            ]
        }
    ]

@app.post("/api/documents/save")
def save_user_document(req: schemas.DocumentSaveRequest, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == req.user_email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User profile not found")

    new_doc = models.UserDocument(
        user_id=user.id,
        doc_type=req.doc_type,
        title=req.title,
        form_data=json.dumps(req.form_data),
        generated_html=req.generated_html
    )
    db.add(new_doc)
    db.commit()
    db.refresh(new_doc)

    return {"status": "success", "message": "Document saved successfully!", "document_id": new_doc.id}

@app.get("/api/documents/my-documents")
def get_my_documents(email: str, db: Session = Depends(database.get_db)):
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    docs = db.query(models.UserDocument).filter(models.UserDocument.user_id == user.id).order_by(models.UserDocument.id.desc()).all()
    return [
        {
            "id": d.id,
            "doc_type": d.doc_type,
            "title": d.title,
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M"),
            "form_data": json.loads(d.form_data) if d.form_data else {},
            "generated_html": d.generated_html
        } for d in docs
    ]

@app.post("/api/ai-legal-research")
async def process_legal_research(req: LegalResearchRequest):
    turn_count = len(req.history)
    if turn_count < 3:
        return {
            "status": "clarifying",
            "reply": "Aapke bataye gaye facts ke mutabiq: Kya is haadse me koi physical injury aayi hai ya sirf vehicle/property damage hua hai?",
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
