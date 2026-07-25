import pytest
from fastapi.testclient import TestClient
from fisher.monitor.auth import create_default_admin, create_access_token
from fisher.monitor.app import create_app
import tempfile
import os
import json
from pathlib import Path


@pytest.fixture
def app(monkeypatch):
    tmp = tempfile.mkdtemp()
    cred_dir = os.path.join(tmp, ".fisher")
    os.makedirs(cred_dir, exist_ok=True)
    monkeypatch.setattr("fisher.monitor.app.CREDENTIALS_DIR", cred_dir)
    monkeypatch.setattr("fisher.monitor.app.CREDENTIALS_FILE", os.path.join(cred_dir, "credentials.json"))
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_DIR", cred_dir)
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_FILE", os.path.join(cred_dir, "credentials.json"))
    create_default_admin(password="test123")
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def auth_header():
    token = create_access_token("admin")
    return {"Authorization": f"Bearer {token}"}


class TestAuthRoutes:
    def test_login_success(self, client):
        resp = client.post("/login", data={"username": "admin", "password": "test123"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_login_failure(self, client):
        resp = client.post("/login", data={"username": "admin", "password": "wrong"})
        assert resp.status_code == 401

    def test_dashboard_protected(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code in (401, 403, 302)

    def test_dashboard_with_token(self, client, auth_header):
        resp = client.get("/dashboard", headers=auth_header)
        assert resp.status_code == 200


class TestAPIRoutes:
    def test_api_overview(self, client, auth_header):
        resp = client.get("/api/overview", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "nav" in data or "capital" in data

    def test_api_positions(self, client, auth_header):
        resp = client.get("/api/positions", headers=auth_header)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)

    def test_api_orders(self, client, auth_header):
        resp = client.get("/api/orders", headers=auth_header)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_api_risk(self, client, auth_header):
        resp = client.get("/api/risk", headers=auth_header)
        assert resp.status_code == 200
        data = resp.json()
        assert "rules" in data or "status" in data

    def test_api_without_auth(self, client):
        resp = client.get("/api/overview")
        assert resp.status_code in (401, 403)

    def test_login_page_get(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
