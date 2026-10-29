"""Regression tests for the current top-level LawNexa FastAPI application.

These tests intentionally target the current /api/* contract. Older /api/v1/*
checks belonged to a different source snapshot and were misleading for this app.
"""

import os
import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_TEST_DIR = tempfile.TemporaryDirectory(prefix="lawnexa-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_DIR.name) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-only-secret-key-never-use-in-production-123456789"
os.environ["ENVIRONMENT"] = "test"
os.environ["ACCESS_TOKEN_EXPIRE_MINUTES"] = "60"
os.environ["FRONTEND_ORIGINS"] = "http://testserver"
for _key in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "ADMIN_PHONE"):
    os.environ.pop(_key, None)

from fastapi.testclient import TestClient
from sqlalchemy import inspect

import auth
import database
import models
from main import app

client = TestClient(app)


def register(payload: dict) -> dict:
    response = client.post("/api/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data.get("token")
    return data


def token_headers(result: dict) -> dict[str, str]:
    return {"Authorization": f"Bearer {result['token']}"}


def client_payload(email: str = "client@example.com") -> dict:
    return {
        "full_name": "Test Client",
        "email": email,
        "password": "a-strong-test-password-123",
        "role": "client",
        "phone": "03001234567",
        "city": "Karachi",
        "address": "Test address",
    }


def test_health_and_admin_asset_are_available():
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["database"] == "connected"

    admin_page = client.get("/admin")
    assert admin_page.status_code == 200
    assert "LAWNEXA" in admin_page.text
    assert "/api/admin/dashboard" in admin_page.text
    assert "/api/v1/" not in admin_page.text


def test_register_login_profile_and_no_password_hash_exposure():
    payload = client_payload()
    created = register(payload)
    user = created["user"]
    assert user["email"] == payload["email"]
    assert user["role"] == "client"
    assert "hashed_password" not in user

    login = client.post(
        "/api/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 200, login.text
    assert login.json()["token"]

    profile = client.get("/api/profile", headers=token_headers(created))
    assert profile.status_code == 200, profile.text
    assert profile.json()["email"] == payload["email"]
    assert "hashed_password" not in profile.json()


def test_registration_rejects_weak_password_and_database_overflow_fields():
    weak_password = client.post(
        "/api/register",
        json=client_payload("weak-password@example.com") | {"password": "short"},
    )
    assert weak_password.status_code == 422

    too_long_name = client.post(
        "/api/register",
        json=client_payload("long-name@example.com") | {"full_name": "N" * 101},
    )
    assert too_long_name.status_code == 422

    too_many_specialties = client.post(
        "/api/register",
        json=client_payload("too-many-specialties@example.com") | {
            "role": "advocate",
            "bar_council_no": "BC-TEST-100",
            "specializations": ["Civil", "Criminal", "Family", "Tax"],
        },
    )
    assert too_many_specialties.status_code == 422


def test_duplicate_email_returns_conflict_without_duplicate_records():
    payload = client_payload("duplicate@example.com")
    register(payload)
    duplicate = client.post("/api/register", json=payload)
    assert duplicate.status_code == 409

    with database.SessionLocal() as db:
        count = db.query(models.User).filter_by(email=payload["email"]).count()
    assert count == 1


def test_profile_requires_auth_and_cannot_read_another_users_profile():
    owner = register(client_payload("owner@example.com"))
    other = register(client_payload("other@example.com"))

    assert client.get("/api/profile").status_code == 401
    forbidden = client.get(
        "/api/profile",
        params={"email": other["user"]["email"]},
        headers=token_headers(owner),
    )
    assert forbidden.status_code == 403


def test_admin_endpoints_reject_an_unprivileged_user():
    user = register(client_payload("not-admin@example.com"))
    response = client.get("/api/admin/dashboard", headers=token_headers(user))
    assert response.status_code == 403

    unauthenticated = client.get("/api/admin/dashboard")
    assert unauthenticated.status_code == 401


def test_document_save_is_authenticated_private_and_sanitizes_html():
    owner = register(client_payload("document-owner@example.com"))
    other = register(client_payload("document-other@example.com"))
    payload = {
        "doc_type": "police_complaint",
        "title": "Police complaint draft",
        "form_data": {"applicant_name": "Test Client"},
        "generated_html": (
            '<div onclick="alert(1)"><p>Safe draft</p>'
            '<script>alert(2)</script><img src="x" onerror="alert(3)"></div>'
        ),
    }
    assert client.post("/api/documents/save", json=payload).status_code == 401
    saved = client.post(
        "/api/documents/save", headers=token_headers(owner), json=payload
    )
    assert saved.status_code == 200, saved.text

    own_docs = client.get(
        "/api/documents/my-documents", headers=token_headers(owner)
    )
    assert own_docs.status_code == 200, own_docs.text
    assert len(own_docs.json()) == 1
    generated_html = own_docs.json()[0]["generated_html"].lower()
    assert "safe draft" in generated_html
    assert "<script" not in generated_html and "<img" not in generated_html
    assert "onclick=" not in generated_html and "onerror=" not in generated_html

    other_docs = client.get(
        "/api/documents/my-documents", headers=token_headers(other)
    )
    assert other_docs.status_code == 200
    assert other_docs.json() == []


def test_current_database_contains_columns_expected_by_orm():
    inspector = inspect(database.engine)
    users = {column["name"] for column in inspector.get_columns("users")}
    lawyers = {column["name"] for column in inspector.get_columns("lawyers")}
    appointments = {column["name"] for column in inspector.get_columns("appointments")}

    assert "residential_address" in users
    assert "chamber_address" in lawyers
    assert {"created_at", "meeting_type", "meeting_mode", "consultation_fee"}.issubset(appointments)


def test_appointment_routes_require_authentication():
    assert client.get("/api/appointments").status_code == 401
    response = client.post(
        "/api/appointments",
        json={"lawyer_id": 1, "booking_date": "2026-11-01", "time_slot": "10:00"},
    )
    assert response.status_code == 401



def create_admin_headers() -> dict[str, str]:
    email = "phase3-admin@example.com"
    with database.SessionLocal() as db:
        admin = db.query(models.User).filter_by(email=email).first()
        if admin is None:
            admin = models.User(
                full_name="Phase 3 Test Admin",
                email=email,
                hashed_password=auth.get_password_hash("admin-test-password-long-123"),
                role="admin",
                is_active=True,
                is_approved=True,
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        token = auth.create_access_token({"sub": email, "role": "admin"})
    return {"Authorization": f"Bearer {token}"}


def test_advocate_registration_approval_and_verification_lifecycle():
    payload = {
        "full_name": "Phase Three Advocate",
        "email": "phase3-advocate@example.com",
        "password": "advocate-test-password-123",
        "role": "advocate",
        "phone": "03001234567",
        "city": "Karachi",
        "specializations": ["Family Law", "Civil Law"],
        "bar_council_no": "BC-PHASE3-001",
        "bar_association": "Karachi Bar Association",
        "chamber_address": "Chamber 101, Karachi",
        "experience_years": 7,
        "consultation_fee": 2500,
    }
    created = register(payload)
    advocate = created["user"]
    assert advocate["is_approved"] is False
    assert advocate["bar_association"] == "Karachi Bar Association"

    with database.SessionLocal() as db:
        lawyer = db.query(models.Lawyer).filter_by(user_id=advocate["id"]).one()
        lawyer_id = lawyer.id
        assert lawyer.specialty == "Family Law"
        assert lawyer.chamber_address == "Chamber 101, Karachi"
        assert lawyer.is_verified is False
        assert lawyer.address is None  # private residential address is not copied publicly

    # The public directory cannot be bypassed with a query parameter.
    assert all(item["id"] != lawyer_id for item in client.get("/api/lawyers").json())
    assert all(item["id"] != lawyer_id for item in client.get("/api/lawyers?verified_only=false").json())

    user_headers = token_headers(created)
    assert client.get(
        "/api/admin/advocates/unverified", headers=user_headers
    ).status_code == 403
    assert client.patch(
        f"/api/admin/advocates/{advocate['id']}/verify", headers=user_headers
    ).status_code == 403

    admin_headers = create_admin_headers()
    approve = client.patch(
        f"/api/admin/advocates/{advocate['id']}/approve", headers=admin_headers
    )
    assert approve.status_code == 200, approve.text

    unverified = client.get("/api/admin/advocates/unverified", headers=admin_headers)
    assert unverified.status_code == 200, unverified.text
    assert any(row["id"] == advocate["id"] for row in unverified.json())

    verified = client.patch(
        f"/api/admin/advocates/{advocate['id']}/verify", headers=admin_headers
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["lawyer"]["is_verified"] is True

    public_rows = client.get("/api/lawyers").json()
    assert any(row["id"] == lawyer_id for row in public_rows)
    assert client.get(f"/api/lawyers/{lawyer_id}").status_code == 200

    # Revoking approval immediately removes the profile from public access.
    rejected = client.patch(
        f"/api/admin/advocates/{advocate['id']}/reject", headers=admin_headers
    )
    assert rejected.status_code == 200, rejected.text
    assert all(item["id"] != lawyer_id for item in client.get("/api/lawyers").json())
    assert client.get(f"/api/lawyers/{lawyer_id}").status_code == 404


def test_profile_update_syncs_advocate_public_directory_fields():
    payload = {
        "full_name": "Profile Sync Advocate",
        "email": "profile-sync-advocate@example.com",
        "password": "advocate-test-password-456",
        "role": "advocate",
        "city": "Karachi",
        "bar_council_no": "BC-SYNC-001",
        "bar_association": "Original Bar",
        "chamber_address": "Old Chamber",
        "specializations": ["Civil Law"],
    }
    created = register(payload)
    with database.SessionLocal() as db:
        lawyer = db.query(models.Lawyer).filter_by(user_id=created["user"]["id"]).one()
        lawyer.is_verified = True
        db.commit()
    update = client.put(
        "/api/profile",
        headers=token_headers(created),
        json={
            "full_name": "Updated Advocate Name",
            "city": "Hyderabad",
            "bar_association": "Updated Bar Association",
            "chamber_address": "New Chamber",
            "specializations": ["Criminal Law"],
        },
    )
    assert update.status_code == 200, update.text
    with database.SessionLocal() as db:
        lawyer = db.query(models.Lawyer).filter_by(user_id=created["user"]["id"]).one()
        assert lawyer.name == "Updated Advocate Name"
        assert lawyer.city == "Hyderabad"
        assert lawyer.bar_association == "Updated Bar Association"
        assert lawyer.chamber_address == "New Chamber"
        assert lawyer.specialty == "Criminal Law"
        assert lawyer.is_verified is False  # name changed; admin must re-verify identity

    # Omitting specializations in a partial update must not clear them.
    partial_update = client.put(
        "/api/profile",
        headers=token_headers(created),
        json={"address": "Private residential address update only"},
    )
    assert partial_update.status_code == 200, partial_update.text
    with database.SessionLocal() as db:
        refreshed = db.query(models.User).filter_by(id=created["user"]["id"]).one()
        lawyer = db.query(models.Lawyer).filter_by(user_id=created["user"]["id"]).one()
        assert "Criminal Law" in (refreshed.specializations or "")
        assert lawyer.specialty == "Criminal Law"


def test_appointment_booking_conflicts_and_state_transitions():
    client_account = register(client_payload("appointment-client@example.com"))
    advocate_payload = {
        "full_name": "Appointment Test Advocate",
        "email": "appointment-advocate@example.com",
        "password": "appointment-advocate-password-123",
        "role": "advocate",
        "phone": "03001234567",
        "city": "Karachi",
        "specializations": ["Civil Law"],
        "bar_council_no": "BC-APPOINTMENT-001",
        "chamber_address": "Test Chamber, Karachi",
        "consultation_fee": 2400,
    }
    advocate_account = register(advocate_payload)
    admin_headers = create_admin_headers()
    user_id = advocate_account["user"]["id"]
    assert client.patch(f"/api/admin/advocates/{user_id}/approve", headers=admin_headers).status_code == 200
    verified = client.patch(f"/api/admin/advocates/{user_id}/verify", headers=admin_headers)
    assert verified.status_code == 200, verified.text
    lawyer_id = verified.json()["lawyer"]["id"]

    appointment_date = (datetime.now(ZoneInfo("Asia/Karachi")).date() + timedelta(days=3)).isoformat()
    payload = {
        "lawyer_id": lawyer_id,
        "booking_date": appointment_date,
        "time_slot": "11:00",
        "meeting_type": "virtual",
        "meeting_mode": "video_call",
        "case_summary": "Regression test appointment",
    }
    client_headers = token_headers(client_account)
    advocate_headers = token_headers(advocate_account)
    created = client.post("/api/appointments", headers=client_headers, json=payload)
    assert created.status_code == 201, created.text
    appointment = created.json()["appointment"]
    assert appointment["status"] == "pending"
    assert appointment["consultation_fee"] == 2400  # server-side fee, not client input

    # An active slot cannot be booked twice, even if the browser changes its state.
    duplicate = client.post("/api/appointments", headers=client_headers, json=payload)
    assert duplicate.status_code == 409, duplicate.text

    appointment_id = appointment["id"]
    forbidden = client.patch(
        f"/api/appointments/{appointment_id}/status",
        headers=client_headers,
        json={"status": "confirmed"},
    )
    assert forbidden.status_code == 403

    confirmed = client.patch(
        f"/api/appointments/{appointment_id}/status",
        headers=advocate_headers,
        json={"status": "confirmed"},
    )
    assert confirmed.status_code == 200, confirmed.text
    duplicate_confirmed = client.post("/api/appointments", headers=client_headers, json=payload)
    assert duplicate_confirmed.status_code == 409

    completed = client.patch(
        f"/api/appointments/{appointment_id}/status",
        headers=advocate_headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200, completed.text
    invalid_reopen = client.patch(
        f"/api/appointments/{appointment_id}/status",
        headers=advocate_headers,
        json={"status": "confirmed"},
    )
    assert invalid_reopen.status_code == 409
    invalid_cancel = client.patch(
        f"/api/appointments/{appointment_id}/status",
        headers=client_headers,
        json={"status": "cancelled"},
    )
    assert invalid_cancel.status_code == 409
import atexit


def _cleanup_test_database():
    client.close()
    database.engine.dispose(close=True)
    _TEST_DIR.cleanup()


atexit.register(_cleanup_test_database)

def test_legal_research_requires_authentication():
    response = client.post(
        "/api/ai-legal-research",
        json={"user_input": "What are my legal options?"},
    )

    assert response.status_code == 401


def test_legal_research_does_not_invent_legal_authorities():
    payload = client_payload("legal-research@example.com")
    registered = register(payload)

    response = client.post(
        "/api/ai-legal-research",
        headers=token_headers(registered),
        json={
            "user_input": "What are my legal options?",
            "language": "roman_urdu",
        },
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "unavailable"
    assert result["case_brief"] is None
    assert "not connected" in result["reply"].lower()
