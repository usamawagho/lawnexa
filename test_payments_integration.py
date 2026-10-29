"""Safepay route tests use a mocked provider; no real payment is sent."""
import hashlib
import hmac
import json

import main
import models
import database
from test_main import client, register, token_headers, client_payload


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_safepay_checkout_is_idempotent_and_webhook_confirms_payment(monkeypatch):
    monkeypatch.setenv("SAFEPAY_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("SAFEPAY_API_KEY", "sandbox-test-key")
    monkeypatch.setenv("SAFEPAY_WEBHOOK_SECRET", "sandbox-webhook-secret")
    monkeypatch.setenv("SAFEPAY_REDIRECT_URL", "https://lawnexa.vercel.app/?payment=return")
    monkeypatch.setenv("SAFEPAY_CANCEL_URL", "https://lawnexa.vercel.app/?payment=cancelled")
    def fake_provider_post(url, *args, **kwargs):
        if url.endswith("/user/v1/guest/"):
            return _FakeResponse({"data": {"token": "guest_test_phase5", "session": "guest-session-test"}})
        return _FakeResponse({"tracker": {"token": "track_test_phase5"}})
    monkeypatch.setattr(main.httpx, "post", fake_provider_post)

    created = register(client_payload("phase5-payment@example.com"))
    user_id = created["user"]["id"]
    db = database.SessionLocal()
    try:
        appointment = models.Appointment(
            client_id=user_id, lawyer_id=None, booking_date="2026-11-30",
            time_slot="10:00", status="confirmed", consultation_fee=1000,
        )
        db.add(appointment)
        db.commit()
        db.refresh(appointment)
        appointment_id = appointment.id
    finally:
        db.close()

    headers = token_headers(created)
    request = {"idempotency_key": "phase5-idempotency-key-001"}
    checkout = client.post(f"/api/payments/appointments/{appointment_id}/checkout", json=request, headers=headers)
    assert checkout.status_code == 201, checkout.text
    payment = checkout.json()["payment"]
    assert payment["amount_minor"] == 100000
    assert payment["currency"] == "PKR"
    assert payment["status"] == "processing"
    assert "tracker=track_test_phase5" in payment["checkout_url"]

    replay = client.post(f"/api/payments/appointments/{appointment_id}/checkout", json=request, headers=headers)
    assert replay.status_code == 201, replay.text
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["payment"]["id"] == payment["id"]

    payload = {
        "event_id": "evt_phase5_success_001", "event": "payment.succeeded",
        "tracker": {"token": "track_test_phase5", "state": "succeeded", "amount": 100000, "currency": "PKR"},
        "amount": 100000, "currency": "PKR",
    }
    raw_body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(b"sandbox-webhook-secret", raw_body, hashlib.sha256).hexdigest()
    webhook = client.post("/api/webhooks/safepay", content=raw_body, headers={"Content-Type": "application/json", "X-SFPY-SIGNATURE": signature})
    assert webhook.status_code == 200, webhook.text
    status_response = client.get(f"/api/payments/{payment['id']}", headers=headers)
    assert status_response.status_code == 200
    assert status_response.json()["payment"]["status"] == "succeeded"

    duplicate = client.post("/api/webhooks/safepay", content=raw_body, headers={"Content-Type": "application/json", "X-SFPY-SIGNATURE": signature})
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True


def test_safepay_webhook_rejects_unsigned_payload(monkeypatch):
    monkeypatch.setenv("SAFEPAY_WEBHOOK_SECRET", "sandbox-webhook-secret")
    response = client.post("/api/webhooks/safepay", json={"event": "payment.succeeded"})
    assert response.status_code == 401
