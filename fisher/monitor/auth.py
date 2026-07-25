import json
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

from jose import JWTError, jwt
from jose.exceptions import ExpiredSignatureError
import bcrypt
# For production use, consider replacing bcrypt with passlib:
# from passlib.hash import bcrypt as passlib_bcrypt

CREDENTIALS_DIR = str(Path.home() / ".fisher")
CREDENTIALS_FILE = str(Path.home() / ".fisher" / "credentials.json")
SECRET_KEY_FILE = str(Path.home() / ".fisher" / "secret_key")


def _get_or_create_secret_key() -> str:
    env_key = os.environ.get("FISHER_JWT_SECRET")
    if env_key:
        return env_key
    try:
        os.makedirs(CREDENTIALS_DIR, exist_ok=True)
        if os.path.exists(SECRET_KEY_FILE):
            with open(SECRET_KEY_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        os.makedirs(CREDENTIALS_DIR, exist_ok=True)
        with open(SECRET_KEY_FILE, "w", encoding="utf-8") as f:
            f.write(key)
    except OSError:
        pass
    return key


SECRET_KEY = _get_or_create_secret_key()
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def _generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def create_default_admin(password: str | None = None) -> None:
    os.makedirs(CREDENTIALS_DIR, exist_ok=True)
    if os.path.exists(CREDENTIALS_FILE):
        return

    pw = password or _generate_password()
    hashed = hash_password(pw)
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump({"username": "admin", "password_hash": hashed}, f, indent=2)


def authenticate(username: str, password: str) -> bool:
    if not os.path.exists(CREDENTIALS_FILE):
        return False

    try:
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return False

    if data.get("username") != username:
        return False

    return verify_password(password, data["password_hash"])


def create_access_token(
    username: str,
    expires_delta: timedelta | None = None,
) -> str:
    if expires_delta is None:
        expires_delta = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)

    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except ExpiredSignatureError:
        raise JWTError("Token has expired")
    except JWTError as e:
        raise JWTError(f"Invalid token: {e}")
    username: str = payload.get("sub")
    if username is None:
        raise JWTError("Token missing subject")
    return username
