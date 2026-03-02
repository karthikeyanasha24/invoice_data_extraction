"""
Encrypt/decrypt sensitive data (private keys, passwords) at rest.
Uses Fernet (symmetric encryption). Key from ENCRYPTION_KEY or derived from SECRET_KEY.
"""
import os
import base64
import hashlib
import logging
from typing import Optional

logger = logging.getLogger("zodiac.encryption")

_FERNET = None


def _get_fernet():
    """Lazy-load Fernet with key from env or SECRET_KEY."""
    global _FERNET
    if _FERNET is not None:
        return _FERNET
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        logger.warning("cryptography not installed; data cannot be encrypted")
        return None

    key_b64 = os.getenv("ENCRYPTION_KEY") or os.getenv("DELIVERY_ENCRYPTION_KEY")
    if key_b64 and len(key_b64) >= 32:
        try:
            Fernet(key_b64)
            _FERNET = Fernet(key_b64)
            return _FERNET
        except Exception as e:
            logger.warning("Invalid ENCRYPTION_KEY: %s", e)

    secret = os.getenv("SECRET_KEY", "your-secret-key-here-change-in-production")
    digest = hashlib.sha256(secret.encode()).digest()
    key_b64 = base64.urlsafe_b64encode(digest).decode()
    _FERNET = Fernet(key_b64)
    return _FERNET


def encrypt_secret(plain: Optional[str]) -> Optional[str]:
    """Encrypt a string for storage. Returns None if plain is None or empty."""
    if not plain or not plain.strip():
        return None
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.encrypt(plain.encode("utf-8")).decode("ascii")
    except Exception as e:
        logger.exception("Encrypt failed: %s", e)
        return None


def decrypt_secret(encrypted: Optional[str]) -> Optional[str]:
    """Decrypt a stored string. Returns None if encrypted is None or empty."""
    if not encrypted or not encrypted.strip():
        return None
    f = _get_fernet()
    if not f:
        return None
    try:
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except Exception as e:
        logger.warning("Decrypt failed: %s", e)
        return None


# Backward compatibility aliases
encrypt_delivery_secret = encrypt_secret
decrypt_delivery_secret = decrypt_secret
