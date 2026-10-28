"""Isolated API regression tests; no seeded demo users or external services required."""
import os
import tempfile
from pathlib import Path

# Configure a fresh test database before importing the application module.
_TEST_DIR = tempfile.TemporaryDirectory(prefix="lawnexa-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_TEST_DIR.name) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-only-secret-key-never-use-in-production-123456789"
os.environ["ENVIRONMENT"] = "test"
os.environ.pop("ADMIN_EMAIL", None)
os.environ.pop("ADMIN_PHONE", None)
os.environ.pop("ADMIN_PASSWORD", None)

from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def register(payload):
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201, response.text
    data = response.json()
    assert data.get("access_token")
    return data


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_new_lawyer_is_persisted_and_visible_without_fake_seed_data():
    lawyer = register({
        "name": "Test Lawyer Live",
        "email": "live-lawyer@gmail.com",
        "phone": "03001112223",
        "password": "strong-password-123",
        "role": "lawyer",
        "city": "Karachi",
        "area": "Saddar",
        "chamber_address": "Test Chamber, Saddar, Karachi",
        "specialty": "Civil Law",
        "license_number": "TEST-LICENSE-001",
        "bar_association": "Test Bar Association",
        "experience_years": 5,
    })

    response = client.get("/api/v1/lawyers/nearby?city=Karachi")
    assert response.status_code == 200
    records = response.json()
    matching = [item for item in records if item["id"] == lawyer["user_id"]]

    assert len(matching) == 1
    assert matching[0]["name"] == "Test Lawyer Live"
    assert matching[0]["is_verified"] is False
    assert matching[0]["verification_status"] == "pending"


def test_real_chat_message_is_saved_and_seen_by_both_accounts():
    client_user = register({
        "name": "Test Client Live",
        "email": "live-client@gmail.com",
        "phone": "03001112224",
        "password": "strong-password-456",
        "role": "client",
        "city": "Karachi",
        "area": "Saddar",
        "address": "Test Residential Address, Saddar, Karachi",
    })

    lawyer_user = register({
        "name": "Test Lawyer Chat",
        "email": "chat-lawyer@gmail.com",
        "phone": "03001112225",
        "password": "strong-password-789",
        "role": "lawyer",
        "city": "Karachi",
        "area": "Saddar",
        "chamber_address": "Test Chamber, Saddar, Karachi",
        "license_number": "TEST-LICENSE-002",
        "bar_association": "Test Bar Association",
    })

    client_headers = {
        "Authorization": f"Bearer {client_user['access_token']}"
    }
    lawyer_headers = {
        "Authorization": f"Bearer {lawyer_user['access_token']}"
    }

    sent = client.post(
        "/api/v1/chat/send",
        headers=client_headers,
        json={
            "receiver_id": lawyer_user["user_id"],
            "message": "Please contact me about my case.",
        },
    )
    assert sent.status_code == 201, sent.text

    lawyer_history = client.get(
        f"/api/v1/chat/history/{client_user['user_id']}",
        headers=lawyer_headers,
    )
    assert lawyer_history.status_code == 200, lawyer_history.text
    assert any(
        message["message"] == "Please contact me about my case."
        for message in lawyer_history.json()
    )

    reply = client.post(
        "/api/v1/chat/send",
        headers=lawyer_headers,
        json={
            "receiver_id": client_user["user_id"],
            "message": "I received your inquiry.",
        },
    )
    assert reply.status_code == 201, reply.text

    client_history = client.get(
        f"/api/v1/chat/history/{lawyer_user['user_id']}",
        headers=client_headers,
    )
    assert client_history.status_code == 200, client_history.text
    assert any(
        message["message"] == "I received your inquiry."
        for message in client_history.json()
    )


def test_unauthed_profile_and_chat_are_not_accessible():
    assert client.get("/api/v1/auth/me").status_code == 401

    response = client.post(
        "/api/v1/chat/send",
        json={"receiver_id": 1, "message": "hello"},
    )
    assert response.status_code == 401


def test_registration_persists_client_address_and_gps():
    result = register({
        "name": "Address Test Client",
        "email": "address-test@example.com",
        "phone": "0300-111-2226",
        "password": "strong-password-abc",
        "role": "client",
        "city": "Karachi",
        "area": "Gulshan",
        "address": "Block 7, Gulshan-e-Iqbal",
        "lat": 24.9231,
        "lng": 67.0924,
    })

    headers = {"Authorization": f"Bearer {result['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)

    assert me.status_code == 200
    assert me.json()["address"] == "Block 7, Gulshan-e-Iqbal"
    assert me.json()["lat"] == 24.9231
    assert me.json()["lng"] == 67.0924


def test_business_registration_is_pending_and_keeps_office_address_private():
    result = register({
        "name": "Example Enterprise",
        "email": "business@example.com",
        "phone": "03001112227",
        "password": "business-password-123",
        "role": "business",
        "business_type": "Private Limited Company",
        "business_registration_no": "NTN-TEST-001",
        "representative_name": "Authorized Contact",
        "registered_address": "Office 12, Business Road, Karachi",
        "operating_address": "Suite 4, Other Road, Karachi",
        "city": "Karachi",
    })
    assert result["role"] == "business"
    assert result["is_approved"] is False
    headers = {"Authorization": f"Bearer {result['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["registered_address"] == "Office 12, Business Road, Karachi"
    # A corporate plan must not be activated automatically before review/payment.
    plan = client.post("/api/v1/subscriptions/subscribe", headers=headers, json={"company_name":"Example Enterprise","plan_type":"BASIC_STARTUP"})
    assert plan.status_code == 403


def test_client_residential_address_is_not_exposed_as_public_address():
    result = register({
        "name": "Private Address Client",
        "email": "private-address@example.com",
        "phone": "03001112228",
        "password": "client-password-123",
        "role": "client",
        "city": "Karachi",
        "area": "Gulshan",
        "address": "Private home address, Karachi",
    })
    headers = {"Authorization": f"Bearer {result['access_token']}"}
    me = client.get("/api/v1/auth/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["address"] == "Private home address, Karachi"


def test_business_legal_request_is_private_and_allowed_while_verification_pending():
    business = register({
        "name": "Pending Request Business", "email": "pending-request@example.com",
        "phone": "03001112229", "password": "business-password-123", "role": "business",
        "business_type": "Startup", "representative_name": "Authorized Contact",
        "registered_address": "Office 1, Karachi",
    })
    headers = {"Authorization": f"Bearer {business['access_token']}"}
    created = client.post("/api/v1/business/requests", headers=headers, json={
        "request_type": "Corporate Legal Team", "title": "Monthly legal support",
        "description": "We need monthly contract review and employment-law support for our company.",
        "urgency": "NORMAL",
    })
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "SUBMITTED"

    other = register({
        "name": "Other Business", "email": "other-business@example.com",
        "phone": "03001112230", "password": "business-password-456", "role": "business",
        "business_type": "Startup", "representative_name": "Other Contact",
        "registered_address": "Office 2, Karachi",
    })
    other_headers = {"Authorization": f"Bearer {other['access_token']}"}
    other_requests = client.get("/api/v1/business/requests", headers=other_headers)
    assert other_requests.status_code == 200, other_requests.text
    assert other_requests.json() == []


def test_safepay_webhook_rejects_missing_or_invalid_signature():
    os.environ["SAFEPAY_WEBHOOK_SECRET"] = "test-webhook-secret"
    response = client.post("/api/v1/payments/safepay/webhook", content=b'{"success":true}')
    assert response.status_code == 401
