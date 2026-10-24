import io
import pytest
from fastapi.testclient import TestClient
from main import app, seed_admin_user

seed_admin_user()

client = TestClient(app)

state = {
    "admin_token": None,
    "client_token": None,
    "lawyer_token": None,
    "client_id": None,
    "lawyer_user_id": None,
    "lawyer_id": None,
    "post_id": None,
    "chat_msg_id": None,
    "booking_id": None,
}


def test_01_public_geo_search():
    response = client.get("/api/v1/lawyers/nearby?client_lat=31.5204&client_lng=74.3587&radius_km=10")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_02_seeded_admin_login():
    response = client.post("/api/v1/auth/token", data={"username": "03000000000", "password": "admin123"})
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "admin"
    state["admin_token"] = data["access_token"]


def test_03_client_registration():
    response = client.post(
        "/api/v1/auth/register",
        data={"name": "Usman Khan", "phone": "03001234567", "password": "clientpass123", "role": "client"}
    )
    assert response.status_code in [201, 400]


def test_04_lawyer_registration_with_proposal_credentials():
    fake_card = io.BytesIO(b"fake bar card binary image")
    response = client.post(
        "/api/v1/auth/register",
        data={
            "name": "Advocate Chaudhry Zafar",
            "phone": "03219876543",
            "email": "zafar.advocate@example.com",
            "password": "lawyerpass123",
            "role": "lawyer",
            "specialty": "Corporate & Criminal",
            "address": "Chamber 44, High Court Bar, Lahore",
            "license_number": "LHC-88991",
            "bar_association": "Lahore High Court Bar Association",
            "experience_years": 12,
            "lat": 31.5204,
            "lng": 74.3587
        },
        files={"law_card": ("bar_card.jpg", fake_card, "image/jpeg")}
    )
    assert response.status_code in [201, 400]


def test_05_logins_and_capture_user_ids():
    res_c = client.post("/api/v1/auth/token", data={"username": "03001234567", "password": "clientpass123"})
    assert res_c.status_code == 200
    state["client_token"] = res_c.json()["access_token"]
    state["client_id"] = res_c.json().get("user_id")

    res_l = client.post("/api/v1/auth/token", data={"username": "03219876543", "password": "lawyerpass123"})
    assert res_l.status_code == 200
    state["lawyer_token"] = res_l.json()["access_token"]
    state["lawyer_user_id"] = res_l.json().get("user_id")


def test_06_admin_approve_lawyer():
    headers = {"Authorization": f"Bearer {state['admin_token']}"}
    pending_res = client.get("/api/v1/admin/lawyers/pending", headers=headers)
    assert pending_res.status_code == 200
    pending_list = pending_res.json()

    if len(pending_list) > 0:
        target = pending_list[-1]
        state["lawyer_id"] = target["id"]
        state["lawyer_user_id"] = target["user_id"]

        app_res = client.post(f"/api/v1/admin/lawyers/{target['id']}/approve", headers=headers)
        assert app_res.status_code == 200
    else:
        lawyers_res = client.get("/api/v1/lawyers/nearby?client_lat=31.5204&client_lng=74.3587&radius_km=100")
        assert lawyers_res.status_code == 200
        lawyers = lawyers_res.json()
        target = next((l for l in lawyers if l["user_id"] == state["lawyer_user_id"]), lawyers[0] if lawyers else None)
        assert target is not None, "Verified lawyer not found in database"
        state["lawyer_id"] = target["id"]
        state["lawyer_user_id"] = target["user_id"]


def test_07_verified_lawyer_in_search():
    response = client.get("/api/v1/lawyers/nearby?client_lat=31.5204&client_lng=74.3587&radius_km=10")
    assert response.status_code == 200
    lawyers = response.json()
    assert any(l["name"] == "Advocate Chaudhry Zafar" for l in lawyers)


def test_08_appointment_creation_and_cancellation_workflow():
    headers_client = {"Authorization": f"Bearer {state['client_token']}"}
    headers_lawyer = {"Authorization": f"Bearer {state['lawyer_token']}"}

    book_res = client.post(
        "/api/v1/bookings",
        json={
            "lawyer_id": state["lawyer_id"],
            "date": "2026-11-01",
            "time": "10:00 AM",
            "summary": "Property dispute legal consult"
        },
        headers=headers_client
    )
    assert book_res.status_code == 201
    booking_id = book_res.json()["booking_id"]

    resp_res = client.post(
        f"/api/v1/bookings/{booking_id}/respond?action=accepted",
        headers=headers_lawyer
    )
    assert resp_res.status_code == 200
    assert resp_res.json()["status"] == "Accepted"

    cancel_res = client.post(
        f"/api/v1/bookings/{booking_id}/cancel",
        headers=headers_client
    )
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "Cancelled"


def test_09_lawyer_create_bar_campaign_post():
    headers = {"Authorization": f"Bearer {state['lawyer_token']}"}
    response = client.post(
        "/api/v1/posts",
        data={
            "content": "Official Manifesto for Lahore High Court Bar Elections 2026!",
            "bar_association": "Lahore High Court Bar Association"
        },
        headers=headers
    )
    assert response.status_code == 201


def test_10_get_bar_social_feed_and_like():
    feed_res = client.get("/api/v1/posts?bar_association=Lahore High Court Bar Association")
    assert feed_res.status_code == 200
    feed = feed_res.json()
    assert len(feed) > 0
    state["post_id"] = feed[0]["id"]

    headers = {"Authorization": f"Bearer {state['client_token']}"}
    like_res = client.post(f"/api/v1/posts/{state['post_id']}/like", headers=headers)
    assert like_res.status_code == 200


def test_11_confidential_chat_and_custom_price_quote():
    headers_client = {"Authorization": f"Bearer {state['client_token']}"}
    headers_lawyer = {"Authorization": f"Bearer {state['lawyer_token']}"}

    client_msg_res = client.post(
        "/api/v1/chat/send",
        json={"receiver_id": state["lawyer_user_id"], "message": "Respected Advocate, I need advice regarding corporate tax appeal."},
        headers=headers_client
    )
    assert client_msg_res.status_code == 201

    history_res = client.get(f"/api/v1/chat/history/{state['lawyer_user_id']}", headers=headers_client)
    assert history_res.status_code == 200
    client_user_id = history_res.json()[0]["sender_id"]

    lawyer_quote_res = client.post(
        "/api/v1/chat/send",
        json={
            "receiver_id": client_user_id,
            "message": "Quotation for representation and filing of tax appeal.",
            "quote_amount": 25000.0
        },
        headers=headers_lawyer
    )
    assert lawyer_quote_res.status_code == 201
    state["chat_msg_id"] = lawyer_quote_res.json()["chat_id"]


def test_12_client_accept_in_chat_quote():
    headers = {"Authorization": f"Bearer {state['client_token']}"}
    response = client.post(
        f"/api/v1/chat/quote/{state['chat_msg_id']}/respond?action=accepted",
        headers=headers
    )
    assert response.status_code == 200
    assert "accepted" in response.json()["message"].lower()


def test_13_websocket_realtime_chat_delivery():
    lawyer_user_id = state["lawyer_user_id"]
    with client.websocket_connect(f"/ws/chat/{lawyer_user_id}") as websocket:
        websocket.send_text("ping")
        data = websocket.receive_text()
        assert data == "pong"