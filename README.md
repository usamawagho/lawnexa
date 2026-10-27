# LawNexa Legal-Tech Platform

Pakistan's smart Legal-Tech marketplace connecting citizens, corporate businesses, and verified advocates.

## Features
- **FastAPI Backend**: JWT Auth with HttpOnly cookies, Alembic migrations, Safepay HMAC signature validation.
- **Tailwind & Alpine.js Frontend**: English buttons with Roman Urdu UI guidance.
- **Admin Governance Portal**: Verification queue for pending advocate licenses.
- **Escrow Vault Engine**: Safe consultation payment holding.

## Quick Start
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python alembic_setup.py
uvicorn main:app --reload
```
App will be running at `http://localhost:8000`.
Admin portal available at `http://localhost:8000/admin`.
