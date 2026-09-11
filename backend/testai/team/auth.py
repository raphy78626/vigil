"""Team authentication — JWT tokens, password hashing, and role-based access."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
import uuid
from base64 import b64decode, b64encode
from pathlib import Path
from typing import Dict, Optional

from fastapi import Header, HTTPException

# Load secret from env → persisted file → generate new one.
# The committed default string is never used as a fallback.
def _load_or_generate_secret() -> str:
    env_val = os.environ.get("VIGIL_SECRET_KEY", "")
    if env_val and env_val != "vigil-dev-secret-change-in-production":
        return env_val
    secret_path = Path(os.environ.get("VIGIL_DATA_DIR", "~/.vigil")).expanduser() / "secret"
    if secret_path.exists():
        return secret_path.read_text().strip()
    # Generate and persist a new secret
    new_secret = secrets.token_hex(32)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    secret_path.write_text(new_secret)
    secret_path.chmod(0o600)
    return new_secret


SECRET_KEY = _load_or_generate_secret()
TOKEN_EXPIRY_HOURS = 24

ROLES = {
    "admin": {"can_manage_users", "can_manage_monitors", "can_delete", "can_replay", "can_export", "can_view"},
    "member": {"can_replay", "can_export", "can_view", "can_manage_monitors"},
    "viewer": {"can_view"},
}


class TeamAuth:
    def __init__(self, db=None):
        self._db = db

    def set_db(self, db):
        self._db = db

    def hash_password(self, password: str) -> str:
        salt = os.urandom(16).hex()
        hashed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
        return f"{salt}:{hashed}"

    def verify_password(self, password: str, stored_hash: str) -> bool:
        if ":" not in stored_hash:
            return False
        salt, hashed = stored_hash.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000).hex()
        return hmac.compare_digest(check, hashed)

    def create_user(self, username: str, password: str, email: str = "", role: str = "member") -> Dict:
        if role not in ROLES:
            raise ValueError(f"Invalid role: {role}")
        existing = self._db.get_user_by_username(username)
        if existing:
            raise ValueError(f"Username '{username}' already exists")

        user = {
            "id": str(uuid.uuid4()),
            "username": username,
            "email": email,
            "password_hash": self.hash_password(password),
            "role": role,
        }
        self._db.insert_user(user)
        return {"id": user["id"], "username": username, "email": email, "role": role}

    def login(self, username: str, password: str) -> Optional[Dict]:
        user = self._db.get_user_by_username(username)
        if not user:
            return None
        if not self.verify_password(password, user["password_hash"]):
            return None
        self._db.update_user_login(user["id"])
        token = self._generate_token(user["id"], user["role"])
        return {"token": token, "user": {"id": user["id"], "username": user["username"], "role": user["role"]}}

    def validate_token(self, token: str) -> Optional[Dict]:
        try:
            payload_b64, sig = token.rsplit(".", 1)
            expected_sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig, expected_sig):
                return None
            payload = json.loads(b64decode(payload_b64 + "=="))
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except Exception:
            return None

    def check_permission(self, token: str, permission: str) -> bool:
        payload = self.validate_token(token)
        if not payload:
            return False
        role = payload.get("role", "viewer")
        return permission in ROLES.get(role, set())

    def _generate_token(self, user_id: str, role: str) -> str:
        payload = {
            "sub": user_id,
            "role": role,
            "exp": int(time.time()) + TOKEN_EXPIRY_HOURS * 3600,
            "iat": int(time.time()),
        }
        payload_b64 = b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
        return f"{payload_b64}.{sig}"

    def ensure_admin_exists(self) -> Optional[str]:
        """Create default admin user if no users exist.

        Returns the generated password (print it to stdout once on first run),
        or None if an admin already existed.
        """
        users = self._db.get_users()
        if not users:
            password = secrets.token_urlsafe(16)
            self.create_user("admin", password, email="admin@vigil.dev", role="admin")
            # Persist password so it survives restarts; file is 0600
            passwd_path = Path(os.environ.get("VIGIL_DATA_DIR", "~/.vigil")).expanduser() / "admin.passwd"
            passwd_path.parent.mkdir(parents=True, exist_ok=True)
            passwd_path.write_text(password)
            passwd_path.chmod(0o600)
            return password
        return None


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------

def _extract_token(authorization: str) -> str:
    """Strip 'Bearer ' prefix from an Authorization header value."""
    return authorization.removeprefix("Bearer ").strip()


def require_auth(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: validate token, return payload. Raises 401 on failure."""
    from testai import state as _state  # late import to avoid circular

    token = _extract_token(authorization)
    if not token:
        raise HTTPException(status_code=401, detail="Authorization header required (Bearer token).")
    payload = _state.team_auth.validate_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return payload


def require_admin(authorization: str = Header(default="")) -> dict:
    """FastAPI dependency: validate token AND require 'admin' role."""
    payload = require_auth(authorization)
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required.")
    return payload
