"""Auth credential manager — per-domain credential vault for AI Explorer.

Stores encrypted credentials so the Explorer can get past login walls automatically.
Supports:
  - Multiple credentials per domain (different roles/accounts)
  - Tagged roles (admin, viewer, standard)
  - Auto-detection of login pages
  - Integration with auth.py storage state
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from cryptography.fernet import Fernet

_VAULT_DIR = Path.home() / ".vigil" / "credentials"
_KEY_FILE = Path.home() / ".vigil" / "vault.key"
_KEY_ENV = "VIGIL_VAULT_KEY"


def _derive_fernet_key(passphrase: str) -> bytes:
    raw = hashlib.pbkdf2_hmac("sha256", passphrase.encode(), b"vigil-vault-salt-2026", 100_000)
    return base64.urlsafe_b64encode(raw)


def _load_or_create_key() -> bytes:
    """Return a Fernet key from env, key file, or generate and persist a new one."""
    env_val = os.environ.get(_KEY_ENV, "")
    if env_val:
        return _derive_fernet_key(env_val)

    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        return _derive_fernet_key(_KEY_FILE.read_text().strip())

    passphrase = secrets.token_hex(32)
    _KEY_FILE.write_text(passphrase)
    _KEY_FILE.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600 — owner only
    return _derive_fernet_key(passphrase)


def _xor_decrypt_legacy(data: bytes, key: bytes) -> bytes:
    """Decrypt data written by the old XOR implementation — migration only."""
    return bytes(d ^ key[i % len(key)] for i, d in enumerate(data))


def _legacy_key() -> bytes:
    passphrase = os.environ.get(_KEY_ENV, "vigil-default-key")
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode(), b"vigil-vault-salt-2026", 100_000)


class CredentialManager:
    def __init__(self, vault_dir: Optional[Path] = None):
        self._vault_dir = vault_dir or _VAULT_DIR
        self._vault_dir.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key())

    def save_credential(self, domain: str, username: str, password: str,
                        role: str = "standard", label: str = "") -> Dict:
        """Save a credential for a domain."""
        cred = {
            "domain": domain,
            "username": username,
            "password": password,
            "role": role,
            "label": label or f"{role}@{domain}",
            "created": datetime.now(timezone.utc).isoformat(),
        }
        creds = self._load_domain(domain)
        creds = [c for c in creds if c.get("username") != username or c.get("role") != role]
        creds.append(cred)
        self._save_domain(domain, creds)
        return {"domain": domain, "username": username, "role": role, "label": cred["label"]}

    def get_credentials(self, domain: str, role: str = None) -> List[Dict]:
        """Get all credentials for a domain, optionally filtered by role."""
        creds = self._load_domain(domain)
        if role:
            creds = [c for c in creds if c.get("role") == role]
        return [self._sanitize(c) for c in creds]

    def get_login_credential(self, domain: str, role: str = "standard") -> Optional[Dict]:
        """Get the best credential for auto-login."""
        creds = self._load_domain(domain)
        for c in creds:
            if c.get("role") == role:
                return c
        return creds[0] if creds else None

    def list_domains(self) -> List[Dict]:
        """List all domains with stored credentials."""
        domains = []
        for f in self._vault_dir.glob("*.vault"):
            domain = f.stem.replace("_", ".")
            creds = self._load_domain(domain)
            domains.append({
                "domain": domain,
                "credentials_count": len(creds),
                "roles": sorted(set(c.get("role", "") for c in creds)),
            })
        return domains

    def delete_credential(self, domain: str, username: str) -> bool:
        creds = self._load_domain(domain)
        new_creds = [c for c in creds if c.get("username") != username]
        if len(new_creds) == len(creds):
            return False
        self._save_domain(domain, new_creds)
        return True

    def detect_login_page(self, url: str, page_html: str = "") -> Dict:
        """Heuristic detection of login pages."""
        signals = {
            "url_signals": [],
            "html_signals": [],
            "is_login_page": False,
            "confidence": 0.0,
        }
        score = 0.0

        url_lower = url.lower()
        for kw in ("login", "signin", "sign-in", "auth", "sso", "oauth", "cas/login"):
            if kw in url_lower:
                signals["url_signals"].append(kw)
                score += 0.3

        html_lower = page_html.lower()
        for kw in ("password", 'type="password"', "log in", "sign in", "username", "credentials"):
            if kw in html_lower:
                signals["html_signals"].append(kw)
                score += 0.15

        signals["confidence"] = min(1.0, score)
        signals["is_login_page"] = score >= 0.3
        return signals

    def _domain_filename(self, domain: str) -> Path:
        safe = domain.replace(".", "_").replace(":", "_").replace("/", "_")
        return self._vault_dir / f"{safe}.vault"

    def _load_domain(self, domain: str) -> List[Dict]:
        path = self._domain_filename(domain)
        if not path.exists():
            return []
        try:
            raw = path.read_bytes()
            try:
                envelope = json.loads(raw)
                if isinstance(envelope, dict) and envelope.get("v") == 2:
                    plaintext = self._fernet.decrypt(envelope["data"].encode())
                    return json.loads(plaintext.decode())
            except (json.JSONDecodeError, KeyError):
                pass
            # Legacy XOR format — decrypt and immediately re-save as v2
            encrypted = base64.b64decode(raw)
            decrypted = _xor_decrypt_legacy(encrypted, _legacy_key())
            creds = json.loads(decrypted.decode())
            self._save_domain(domain, creds)  # migrate in place
            return creds
        except Exception:
            return []

    def _save_domain(self, domain: str, creds: List[Dict]):
        path = self._domain_filename(domain)
        token = self._fernet.encrypt(json.dumps(creds).encode()).decode()
        path.write_text(json.dumps({"v": 2, "data": token}))

    def _sanitize(self, cred: Dict) -> Dict:
        return {
            "domain": cred.get("domain", ""),
            "username": cred.get("username", ""),
            "role": cred.get("role", ""),
            "label": cred.get("label", ""),
            "created": cred.get("created", ""),
            "has_password": bool(cred.get("password")),
        }
