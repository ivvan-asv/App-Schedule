"""Encryption of secrets stored in the database (RNF02: AES-256 at rest)."""
import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

NONCE_BYTES = 12


class TokenEncryptionNotConfigured(RuntimeError):
    """TOKEN_ENCRYPTION_KEY is missing or is not 32 bytes of base64."""


class TokenCipher:
    """AES-256-GCM. Each value is stored as nonce || ciphertext+tag."""

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise TokenEncryptionNotConfigured("TOKEN_ENCRYPTION_KEY must decode to 32 bytes")
        self._aead = AESGCM(key)

    @classmethod
    def from_settings(cls) -> "TokenCipher":
        if not settings.TOKEN_ENCRYPTION_KEY:
            raise TokenEncryptionNotConfigured(
                "Set TOKEN_ENCRYPTION_KEY to store calendar tokens "
                "(see docs/calendar-credentials.md)"
            )
        try:
            key = base64.b64decode(settings.TOKEN_ENCRYPTION_KEY, validate=True)
        except binascii.Error as error:
            raise TokenEncryptionNotConfigured("TOKEN_ENCRYPTION_KEY is not valid base64") from error
        return cls(key)

    def encrypt(self, value: str) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return nonce + self._aead.encrypt(nonce, value.encode(), None)

    def decrypt(self, value: bytes) -> str:
        try:
            return self._aead.decrypt(value[:NONCE_BYTES], value[NONCE_BYTES:], None).decode()
        except InvalidTag as error:
            raise ValueError("Token was encrypted with another key or was modified") from error
