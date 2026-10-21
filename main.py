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


import google.generativeai as genai

# Gemini AI Setup
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        print(f"Gemini Config Warning: {e}")


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
    doc_type = payload.get("doc_type", "Agreement").strip()
    p1 = payload.get("party1", "First Party / Applicant").strip()
    p2 = payload.get("party2", "Second Party / Respondent").strip()
    court = payload.get("court", "Karachi, Pakistan").strip()
    purpose = payload.get("purpose", "").strip()

    # -------------------------------------------------------------
    # LAYER 1: GEMINI AI REAL-TIME DRAFTING ENGINE (If Key Present)
    # -------------------------------------------------------------
    if GEMINI_API_KEY:
        try:
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
You are an expert Senior Advocate of the High Court in Pakistan with 25 years of experience in legal drafting.
Generate a COMPLETE, HIGHLY DETAILED, AND PROFESSIONALLY FORMATTED legal document in English according to the Laws of the Islamic Republic of Pakistan (Contract Act 1872, Registration Act 1908, PPC, CrPC, CPC, Transfer of Property Act 1882, etc.).

DOCUMENT DETAILS:
- Document Category / Title: {doc_type}
- First Party / Applicant / Petitioner: {p1}
- Second Party / Respondent / Opposite Party: {p2}
- Court / Jurisdiction / Location: {court}
- Additional Facts / Specific Purpose: {purpose}

DRAFTING INSTRUCTIONS:
1. Provide the complete legal document. Do NOT shorten or use ellipses (...) in main clauses.
2. For Court Petitions (Bail, Suits, Writs): Use exact Pakistan Court Headings, Memo of Parties, Facts 1 to 7, Grounds, Interim & Final Prayer, Verification clause, and Advocate signatures.
3. For Contracts / Agreements (Sale, Rent, Partnership): Include Title, Consideration/Price, Obligations, Default & Penalty Clauses, Indemnity, Dispute Resolution, Jurisdiction, Schedule of Property, and Witness signature blocks (Witness 1 & 2 with CNIC).
4. For Power of Attorney (Mukhtar Nama): Mention stamp paper reference, specific powers granted, revocation rules, and Sub-Registrar endorsement layout.
5. Strictly adhere to Pakistani court/legal terminology used in Karachi, Lahore, Islamabad, and High Courts.
"""
            response = model.generate_content(prompt)
            if response and response.text:
                return {"draft": response.text.strip()}
        except Exception as err:
            print(f"Gemini Generation Exception: {err}")

    # -------------------------------------------------------------
    # LAYER 2: COMPREHENSIVE PAKISTANI LEGAL TEMPLATE FALLBACKS
    # -------------------------------------------------------------
    doc_lower = doc_type.lower()

    # 1. BAIL PETITIONS (497 / 498 CrPC)
    if "bail" in doc_lower or "498" in doc_lower or "497" in doc_lower:
        sec = "498" if "pre" in doc_lower or "498" in doc_lower else "497"
        b_type = "PRE-ARREST BAIL" if sec == "498" else "POST-ARREST BAIL"
        draft = f"""IN THE COURT OF THE DISTRICT & SESSIONS JUDGE AT {court.upper()}

Bail Application No. _________ of 2026

{p1}
S/o ________________________, R/o ________________________________________.
... Applicant / Accused

---VERSUS---

1. {p2}
2. The State / S.H.O., Police Station ____________________.
... Respondents

APPLICATION FOR {b_type} UNDER SECTION {sec} Cr.P.C.
IN CASE FIR NO. _________ / 2026, OFFENSE U/S ________________ PPC, P.S. ____________________

Respectfully Sheweth:
1. That the Applicant is a peaceful, law-abiding citizen of Pakistan and has been falsely implicated in the aforementioned FIR with malicious intent.
2. That the police, at the instance of complainant, are attempting to illegally arrest and humiliate the Applicant.
3. That the Applicant has no nexus or role in the alleged offense and no specific active role is attributed to him.
4. That the allegations are false, baseless, fabricated, and motivated by personal rivalry and mala fide intention.
5. That the Applicant is a respectable resident, has permanent abode in Pakistan, and there is no apprehension of his absconding or tampering with evidence.
6. That the Applicant is willing to join police investigation as required and ready to furnish reliable surety bonds.

PRAYER:
It is humbly prayed that this Honorable Court may graciously be pleased to:
a) Grant Interim {b_type} to the Applicant directing Respondent No. 2 not to arrest the Applicant.
b) Confirm the {b_type} after hearing both parties, in the ultimate interest of justice.

Applicant / Accused
Through: Advocate High Court / Sessions Court, Karachi Bar Association

VERIFICATION:
Verified on Oath at {court} on _____ day of ____________ 2026, that contents of paragraphs 1-6 are true to the best of my knowledge and belief.
DEPONENT ({p1})"""

    # 2. SALE AGREEMENT FOR PROPERTY / VEHICLE (Contract Act 1872)
    elif "sale" in doc_lower or "buy" in doc_lower or "property" in doc_lower:
        draft = f"""AGREEMENT TO SELL

This Agreement to Sell is executed at {court} on this _____ day of ____________ 2026, by and between:

FIRST PARTY (SELLER):
{p1}, holding CNIC No. ________________________, Resident of ________________________________________________.

SECOND PARTY (PURCHASER):
{p2}, holding CNIC No. ________________________, Resident of ________________________________________________.

WHEREAS the First Party is the absolute lawful owner in possession of the property/vehicle described as: {purpose or 'Property / Vehicle details as per title deed'}.

NOW THIS AGREEMENT WITNESSETH AS UNDER:
1. TOTAL CONSIDERATION: The total sale price is fixed at PKR _______________/- (Pakistani Rupees ________________________________________ Only).
2. EARNEST MONEY / ADVANCE: The Purchaser has paid advance amount of PKR _______________/- to the Seller, receipt whereof is hereby acknowledged by the Seller.
3. BALANCE PAYMENT: The Purchaser agrees to pay balance sum of PKR _______________/- on or before ____________ 2026, at time of final deed execution.
4. TITLE CLEARANCE: Seller guarantees that property is free from all encumbrances, claims, mortgages, litigation, or government dues.
5. DEFAULT CLAUSE: If Purchaser defaults, earnest money shall stand forfeited. If Seller defaults, Seller shall refund double advance amount to Purchaser.

IN WITNESS WHEREOF both parties have signed this Agreement before witnesses.

SELLER (First Party): ______________________  
PURCHASER (Second Party): ______________________

WITNESS 1:                                WITNESS 2:
Name: _______________________________     Name: _______________________________
CNIC: _______________________________     CNIC: _______________________________"""

    # 3. RENT / TENANCY AGREEMENT
    elif "rent" in doc_lower or "tenant" in doc_lower or "tenancy" in doc_lower:
        draft = f"""TENANCY / RENT AGREEMENT

This Tenancy Agreement is executed at {court} on this _____ day of ____________ 2026, between:

LANDLORD (OWNER):
{p1}, CNIC No. ________________________, Resident of ________________________________________________.

TENANT:
{p2}, CNIC No. ________________________, Resident of ________________________________________________.

PREMISES DETAILS:
Landlord agrees to let out premises: {purpose or 'Residential Premises / Shop / Office Address'} to the Tenant on monthly rental basis.

TERMS AND CONDITIONS:
1. TENURE: Rent period is fixed for 11 Months commencing from ____________ 2026 to ____________ 2027.
2. MONTHLY RENT: Rent is fixed at PKR _______________/- per month, payable in advance on/before 5th of each calendar month.
3. SECURITY DEPOSIT: Tenant has deposited interest-free refundable security deposit of PKR _______________/-.
4. UTILITIES: Tenant shall pay electricity, gas, water, and maintenance bills directly to authorities.
5. MAINTENANCE & SUBLETTING: Tenant shall maintain premises in good condition and shall not sublet or alter premises without written consent.
6. TERMINATION: Either party may terminate agreement by giving 1 Month prior written notice.

LANDLORD: ___________________________    TENANT: ___________________________

WITNESS 1: ___________________________    WITNESS 2: ___________________________"""

    # 4. GENERAL / SPECIAL POWER OF ATTORNEY (Mukhtar Nama)
    elif "power" in doc_lower or "attorney" in doc_lower or "mukhtar" in doc_lower:
        draft = f"""GENERAL POWER OF ATTORNEY (MUKHTAR NAMA AAM)

KNOW ALL MEN BY THESE PRESENTS that I,
EXECUTANT: {p1}, CNIC No. ________________________, Resident of ________________________________________________.

DO HEREBY CONSTITUTE, APPOINT AND ORDAIN:
ATTORNEY: {p2}, CNIC No. ________________________, Resident of ________________________________________________.

To be my lawful Attorney in my name and on my behalf to perform following acts, deeds, and things regarding: {purpose or 'All property and legal matters at Karachi'}.

POWERS CONFERRED:
1. To manage, look after, supervise, lease, or sell the property mentioned hereinabove.
2. To appear, plead, and represent me before all Courts, Sub-Registrar, KDA, KMC, Excise, FBR, and Utility Departments.
3. To engage Advocates, sign plaints, written statements, affidavits, petitions, and record evidence.
4. To receive sale consideration, issue valid receipts, and execute registered sale deeds before Sub-Registrar.

I hereby ratify and confirm all acts done by my lawful Attorney as if done by me personally.

EXECUTANT ({p1}): ______________________

WITNESS 1: ___________________________    WITNESS 2: ___________________________"""

    # 5. LEGAL NOTICE (Notice Before Suit)
    elif "notice" in doc_lower:
        draft = f"""LEGAL NOTICE BEFORE SUIT

BY REGISTERED A.D. / COURIER

TO:
{p2},
Resident of ________________________________________________.

FROM:
Advocate High Court, on behalf of Client:
{p1}, Resident of ________________________________________________.

SUBJECT: LEGAL NOTICE FOR {doc_type.upper()} / {purpose.upper()}

Sir/Madam,
Under instructions from my Client above-named, I hereby serve upon you this Legal Notice as under:

1. That my Client is a law-abiding citizen and entered into legal business relationship with you regarding {purpose or 'contractual transaction'}.
2. That you failed to fulfill your legal obligation and breached the terms despite multiple requests.
3. That your deliberate non-compliance has caused severe pecuniary loss, distress, and mental agony to my Client.

DEMAND:
I hereby call upon you to comply with demands / pay outstanding dues of PKR _______________/- within 14 DAYS of receipt of this notice, failing which my Client has issued clear instructions to file Civil/Criminal proceedings against you in Court of competent jurisdiction at {court} at your risk and cost.

Advocate High Court
Karachi Bar Association"""

    # 6. DEFAULT / CIVIL SUIT / OTHER LEGAL DOCUMENTS
    else:
        draft = f"""IN THE COURT OF SENIOR CIVIL JUDGE AT {court.upper()}

Civil Suit No. _________ of 2026

{p1}
... Plaintiff / Petitioner

---VERSUS---

{p2}
... Defendant / Respondent

SUIT FOR DECLARATION, PERMANENT INJUNCTION AND RELIEF REGARDING {doc_type.upper()}

Respectfully Sheweth:
1. That the Plaintiff is lawful citizen residing within territorial jurisdiction of this Honorable Court.
2. Cause of action arose on ____________ 2026 when Defendant unlawfully interfered with Plaintiff's legal rights regarding: {purpose or 'subject matter'}.
3. Court fee has been properly affixed and this Court has pecuniary and territorial jurisdiction to try this suit.

PRAYER:
It is humbly prayed that Decree for Declaration and Permanent Injunction be passed in favor of Plaintiff against Defendant with costs.

Plaintiff
Through Advocate High Court

VERIFICATION:
Verified at {court} on _____ day of ____________ 2026 that contents of Paras 1 to 3 are true.
DEPONENT ({p1})"""

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
