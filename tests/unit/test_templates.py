import pytest
from fastapi.testclient import TestClient
from fisher.monitor.auth import create_default_admin, create_access_token
from fisher.monitor.app import create_app
import tempfile
import os


@pytest.fixture
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    cred_dir = os.path.join(tmp, ".fisher")
    os.makedirs(cred_dir, exist_ok=True)
    monkeypatch.setattr("fisher.monitor.app.CREDENTIALS_DIR", cred_dir)
    monkeypatch.setattr("fisher.monitor.app.CREDENTIALS_FILE", os.path.join(cred_dir, "credentials.json"))
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_DIR", cred_dir)
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_FILE", os.path.join(cred_dir, "credentials.json"))
    create_default_admin(password="test123")
    app = create_app()
    return TestClient(app)


@pytest.fixture
def token():
    return create_access_token("admin")


class TestTemplateRender:
    def test_login_page_renders(self, client):
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "Sign In" in resp.text or "sign" in resp.text.lower()

    def test_dashboard_renders(self, client, token):
        resp = client.get("/dashboard", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert "FisherQuant" in resp.text
