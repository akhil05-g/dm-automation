import os
import pytest
from fastapi.testclient import TestClient

# Set temp DB path for testing
os.environ["DATABASE_PATH"] = "./test_linkplease.db"

from app.database import init_db, get_db
from app.main import app

@pytest.fixture(autouse=True)
def setup_db():
    if os.path.exists("./test_linkplease.db"):
        os.remove("./test_linkplease.db")
    init_db()
    yield
    if os.path.exists("./test_linkplease.db"):
        os.remove("./test_linkplease.db")

client = TestClient(app)

def test_rule_creation():
    response = client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list here!"})
    assert response.status_code == 201
    data = response.json()
    assert data["keyword"] == "PRICE"
    assert "rule_id" in data

def test_duplicate_event_blocked():
    client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list"})
    
    payload = {
        "event_id": "evt_001",
        "event_type": "comment.created",
        "sent_at": "2026-08-17T10:00:00Z",
        "data": {
            "comment_id": "cmt_001",
            "post_id": "post_1",
            "text": "PRICE please",
            "from": {"user_id": "usr_100", "username": "user100"}
        }
    }
    
    # First delivery
    res1 = client.post("/webhook", json=payload)
    assert res1.status_code == 200
    
    # Redelivery of same event_id
    res2 = client.post("/webhook", json=payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "duplicate_event_blocked"
    
    # Check stats
    stats = client.get("/stats").json()
    assert stats["duplicates_blocked"] == 1

def test_duplicate_user_rule_dmed_blocked():
    client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list"})
    
    # Comment 1 from usr_100
    p1 = {
        "event_id": "evt_001",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_001",
            "text": "PRICE please",
            "from": {"user_id": "usr_100", "username": "user100"}
        }
    }
    client.post("/webhook", json=p1)
    
    # Comment 2 from SAME usr_100 with different event_id & comment_id
    p2 = {
        "event_id": "evt_002",
        "event_type": "comment.created",
        "data": {
            "comment_id": "cmt_002",
            "text": "PRICE again!!",
            "from": {"user_id": "usr_100", "username": "user100"}
        }
    }
    client.post("/webhook", json=p2)
    
    stats = client.get("/stats").json()
    assert stats["duplicates_blocked"] == 1
