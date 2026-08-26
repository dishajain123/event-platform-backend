"""
JWT issuance/verification and OTP hashing.

OTPs are never stored in plaintext, even in Redis with a short TTL —
they're hashed with a server-side pepper the same way a password would
be, just with SHA-256 rather than bcrypt since OTPs are short-lived and
high-entropy enough that the slower bcrypt cost isn't needed here.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum

import jwt

from app.config import get_settings

settings = get_settings()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


def generate_otp() -> str:
    """Cryptographically random numeric OTP, length from settings."""
    return "".join(secrets.choice("0123456789") for _ in range(settings.otp_length))


def hash_otp(otp: str, mobile_number: str) -> str:
    """
    Peppered hash of an OTP, scoped to the mobile number it was issued for —
    so a leaked hash for one number can't be replayed against another.
    """
    payload = f"{otp}:{mobile_number}:{settings.otp_hash_pepper}".encode()
    return hashlib.sha256(payload).hexdigest()


def create_token(user_id: uuid.UUID, token_type: TokenType) -> str:
    now = datetime.now(timezone.utc)
    if token_type == TokenType.ACCESS:
        expires_delta = timedelta(minutes=settings.access_token_expire_minutes)
    else:
        expires_delta = timedelta(days=settings.refresh_token_expire_days)

    payload = {
        "sub": str(user_id),
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or a subclass) if the token is invalid or expired."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])