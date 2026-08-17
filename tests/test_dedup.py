import os
import pytest
from fastapi.testclient import TestClient
os.environ["DATABASE_PATH"] = "./test_linkplease.db"
from app.database import init_db
from app.main import app

client = TestClient(app)
def test_rule_creation():
    init_db()
    res = client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list"})
    assert res.status_code == 201
