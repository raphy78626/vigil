"""Team authentication — JWT tokens, password hashing, and role-based access."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import uuid
from base64 import b64decode, b64encode
from typing import Dict, Optional

SECRET_KEY = os.environ.get("VIGIL_SECRET_KEY", "vigil-dev-secret-change-in-production")
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
            expected_sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
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
        sig = hmac.new(SECRET_KEY.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:32]
        return f"{payload_b64}.{sig}"

    def ensure_admin_exists(self) -> None:
        """Create default admin user if no users exist."""
        users = self._db.get_users()
        if not users:
            self.create_user("admin", "admin", email="admin@vigil.dev", role="admin")
