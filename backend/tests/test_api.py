import base64

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.db import Database
from app.engine import Engine

from .helpers import FakeClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "panel_password", "test-sifre-123")
    main.app.state.engine = Engine(FakeClient(), Database("sqlite+aiosqlite:///:memory:"), 1000.0)
    main.app.state.background = False
    with TestClient(main.app) as c:
        yield c
    del main.app.state.engine


def h(pw="test-sifre-123"):
    return {"Authorization": "Basic " + base64.b64encode(f"admin:{pw}".encode()).decode()}


def test_requires_auth(client):
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers=h("yanlis")).status_code == 401
    assert client.get("/").status_code == 401


def test_status_and_panel(client):
    r = client.get("/api/status", headers=h())
    assert r.status_code == 200 and r.json()["mode"] == "paper" and r.json()["equity"] == 1000
    assert "AI Kripto Trader" in client.get("/", headers=h()).text


def test_settings_roundtrip(client):
    r = client.put("/api/settings", headers=h(), json={"risk": {"min_score": 80}})
    assert r.status_code == 200 and r.json()["risk"]["min_score"] == 80
    assert client.put("/api/settings", headers=h(), json={"risk": {"max_open_positions": 0}}).status_code == 400


def test_bot_controls(client):
    assert client.post("/api/bot/run", headers=h(), json={"running": True}).json()["running"]
    assert client.post("/api/bot/emergency", headers=h(), json={"active": True}).json()["emergency_stop"]
    assert client.post("/api/bot/run", headers=h(), json={"running": True}).status_code == 400


def test_live_mode_refused(monkeypatch):
    monkeypatch.setattr(settings, "trading_mode", "live")
    monkeypatch.setattr(settings, "panel_password", "test-sifre-123")
    with pytest.raises(RuntimeError):
        settings.validate_safety()
