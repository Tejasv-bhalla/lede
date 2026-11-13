"""Encrypt secrets (users' model API keys) before they reach the database."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class Sealer:
    def __init__(self, secret: str) -> None:
        # Fernet needs 32 url-safe base64 bytes; derive them from any secret string.
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def seal(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def open(self, token: str) -> str | None:
        """The secret, or None if it was sealed with a different settings secret."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None
