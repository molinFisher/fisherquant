import pytest
import os
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from fisher.monitor.auth import (
    create_default_admin,
    authenticate,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
    CREDENTIALS_DIR,
    CREDENTIALS_FILE,
)


@pytest.fixture
def temp_credentials_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_DIR", str(tmp_path))
    monkeypatch.setattr("fisher.monitor.auth.CREDENTIALS_FILE", str(tmp_path / "credentials.json"))
    return tmp_path


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "test_password"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)
        assert not verify_password("wrong", hashed)


class TestAdminCreation:
    def test_creates_credentials_file(self, temp_credentials_dir):
        create_default_admin(password="admin123")
        cred_file = temp_credentials_dir / "credentials.json"
        assert cred_file.exists()

    def test_credentials_contains_admin(self, temp_credentials_dir):
        create_default_admin(password="admin123")
        cred_file = temp_credentials_dir / "credentials.json"
        data = json.loads(cred_file.read_text())
        assert data["username"] == "admin"
        assert "password_hash" in data

    def test_creates_random_password_if_none(self, temp_credentials_dir):
        create_default_admin()
        cred_file = temp_credentials_dir / "credentials.json"
        assert cred_file.exists()
        data = json.loads(cred_file.read_text())
        assert len(data["username"]) > 0

    def test_does_not_overwrite_existing(self, temp_credentials_dir):
        create_default_admin(password="first")
        first_hash = json.loads((temp_credentials_dir / "credentials.json").read_text())["password_hash"]
        create_default_admin(password="second")
        second_hash = json.loads((temp_credentials_dir / "credentials.json").read_text())["password_hash"]
        assert first_hash == second_hash


class TestAuthenticate:
    def test_authenticate_valid_credentials(self, temp_credentials_dir):
        create_default_admin(password="admin123")
        result = authenticate("admin", "admin123")
        assert result is True

    def test_authenticate_invalid_password(self, temp_credentials_dir):
        create_default_admin(password="admin123")
        result = authenticate("admin", "wrong")
        assert result is False

    def test_authenticate_invalid_user(self, temp_credentials_dir):
        create_default_admin(password="admin123")
        result = authenticate("nobody", "admin123")
        assert result is False

    def test_authenticate_no_credentials_file(self, temp_credentials_dir):
        result = authenticate("admin", "admin123")
        assert result is False


class TestJWTToken:
    def test_create_token(self):
        token = create_access_token("admin")
        assert token is not None
        assert isinstance(token, str)
        assert len(token) > 0

    def test_get_current_user_valid(self):
        token = create_access_token("admin")
        username = get_current_user(token)
        assert username == "admin"

    def test_get_current_user_invalid_token(self):
        with pytest.raises(Exception):
            get_current_user("invalid.token.here")

    def test_token_expiry(self):
        token = create_access_token("admin", expires_delta=timedelta(seconds=-1))
        with pytest.raises(Exception):
            get_current_user(token)
