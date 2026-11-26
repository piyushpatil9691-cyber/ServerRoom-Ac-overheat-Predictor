"""Authenticated encryption helpers using Fernet for SMTP credentials."""

from __future__ import annotations

import os
from cryptography.fernet import Fernet, InvalidToken

from config import get_settings


class EncryptionError(RuntimeError):
    """Raised when encryption key is missing/invalid or decryption fails."""


def _resolve_fernet(encryption_key: str | None = None) -> Fernet:
    raw_key = encryption_key
    if raw_key is None:
        raw_key = os.environ.get("CREDENTIALS_ENCRYPTION_KEY") or get_settings().credentials_encryption_key

    if not raw_key or raw_key.startswith("REPLACE_WITH_"):
        raise EncryptionError(
            "CREDENTIALS_ENCRYPTION_KEY is not configured. Set a valid Fernet key in the environment or .env."
        )
    try:
        return Fernet(raw_key.strip().encode("utf-8"))
    except Exception as exc:
        raise EncryptionError("CREDENTIALS_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def is_encryption_configured(encryption_key: str | None = None) -> bool:
    """Return True if a valid Fernet key is available in the environment."""
    try:
        _resolve_fernet(encryption_key)
        return True
    except EncryptionError:
        return False


def encrypt_secret(plaintext: str, encryption_key: str | None = None) -> str:
    """Encrypt a secret string using Fernet authenticated encryption."""
    if not plaintext:
        raise ValueError("Secret value cannot be empty.")
    fernet = _resolve_fernet(encryption_key)
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret(ciphertext: str, encryption_key: str | None = None) -> str:
    """Decrypt a Fernet-encrypted secret string."""
    if not ciphertext:
        raise ValueError("Encrypted secret is empty.")
    fernet = _resolve_fernet(encryption_key)
    try:
        plaintext = fernet.decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionError(
            "Unable to decrypt stored credentials. Ensure CREDENTIALS_ENCRYPTION_KEY matches the key used to save them."
        ) from exc


def mask_secret(value: str | None) -> str:
    """Return a safe masked representation without exposing secret characters."""
    if not value:
        return "Not configured"
    return "•••••••••••• (Configured)"
