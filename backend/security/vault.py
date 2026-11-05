"""Secret vault: API keys (broker, AI) are encrypted at rest with a key derived from SECRET_KEY."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from backend.config import settings


def _fernet() -> Fernet:
    key = hashlib.sha256(("robin-vault:" + settings.SECRET_KEY).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError):
        return ""


def mask(secret: str) -> str:
    if not secret:
        return ""
    return secret[:4] + "…" + secret[-4:] if len(secret) > 10 else "••••"
