"""
Business logic for the identity module: OTP issuance/verification with
expiry, resend cooldown, and attempt limits (all enforced via Redis,
since OTP state is short-lived and doesn't belong in Postgres); JWT
session issuance; identity document encryption.
"""
import uuid

from cryptography.fernet import Fernet
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.modules.identity.exceptions import (
    InvalidOTPError,
    OTPExpiredError,
    OTPResendTooSoonError,
    TooManyOTPAttemptsError,
    UserNotFoundError,
)
from app.modules.identity.models import DocumentType, IdentityDocument, User
from app.modules.identity.repository import IdentityDocumentRepository, UserRepository
from app.security import TokenType, create_token, generate_otp, hash_otp

settings = get_settings()


def _otp_redis_key(mobile_number: str) -> str:
    return f"otp:{mobile_number}"


def _otp_cooldown_key(mobile_number: str) -> str:
    return f"otp:cooldown:{mobile_number}"


def _otp_attempts_key(mobile_number: str) -> str:
    return f"otp:attempts:{mobile_number}"


class IdentityService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis
        self.users = UserRepository(db)
        self.documents = IdentityDocumentRepository(db)

    # ---- OTP flow ----

    async def request_otp(self, mobile_number: str) -> int:
        """
        Generates and stores a hashed OTP with a TTL, enforces the resend
        cooldown, and (in a later phase) dispatches it via the SMS provider
        integration. Returns seconds until the next resend is allowed.
        """
        if await self.redis.get(_otp_cooldown_key(mobile_number)):
            ttl = await self.redis.ttl(_otp_cooldown_key(mobile_number))
            raise OTPResendTooSoonError(
                f"Please wait {ttl} seconds before requesting another OTP."
            )

        otp = generate_otp()
        hashed = hash_otp(otp, mobile_number)

        await self.redis.set(_otp_redis_key(mobile_number), hashed, ex=settings.otp_expiry_seconds)
        await self.redis.set(
            _otp_cooldown_key(mobile_number), "1", ex=settings.otp_resend_cooldown_seconds
        )
        await self.redis.delete(_otp_attempts_key(mobile_number))

        # Phase 6 wires this to app/integrations/sms_provider.py for real dispatch.
        # For now (and for local/dev), the OTP is returned by the stub sender —
        # see app/integrations/sms_provider.py — never logged or returned in the API response.
        from app.integrations.sms_provider import send_otp_sms

        await send_otp_sms(mobile_number, otp)

        return settings.otp_resend_cooldown_seconds

    async def verify_otp(self, mobile_number: str, otp: str) -> User:
        attempts_key = _otp_attempts_key(mobile_number)
        attempts = int(await self.redis.get(attempts_key) or 0)
        if attempts >= settings.otp_max_verify_attempts:
            raise TooManyOTPAttemptsError(
                "Too many incorrect attempts. Please request a new OTP."
            )

        stored_hash = await self.redis.get(_otp_redis_key(mobile_number))
        if stored_hash is None:
            raise OTPExpiredError("This OTP has expired. Please request a new one.")

        if hash_otp(otp, mobile_number) != stored_hash:
            await self.redis.incr(attempts_key)
            await self.redis.expire(attempts_key, settings.otp_expiry_seconds)
            raise InvalidOTPError("Incorrect OTP.")

        # Success — OTP is single-use, clear it immediately.
        await self.redis.delete(_otp_redis_key(mobile_number))
        await self.redis.delete(attempts_key)

        user, _created = await self.users.get_or_create(mobile_number)
        await self.db.commit()
        return user

    def issue_tokens(self, user_id: uuid.UUID) -> tuple[str, str]:
        access = create_token(user_id, TokenType.ACCESS)
        refresh = create_token(user_id, TokenType.REFRESH)
        return access, refresh

    # ---- User lookup ----

    async def get_user_or_raise(self, user_id: uuid.UUID) -> User:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("User not found.")
        return user

    # ---- Identity documents ----

    def _fernet(self) -> Fernet:
        if not settings.identity_doc_encryption_key:
            raise RuntimeError(
                "IDENTITY_DOC_ENCRYPTION_KEY is not set — generate one with "
                "Fernet.generate_key() and add it to your .env before storing documents."
            )
        return Fernet(settings.identity_doc_encryption_key.encode())

    async def add_identity_document(
        self, user_id: uuid.UUID, document_type: DocumentType, document_number: str
    ) -> IdentityDocument:
        encrypted = self._fernet().encrypt(document_number.encode()).decode()
        doc = await self.documents.add(user_id, document_type, encrypted)
        await self.db.commit()
        return doc

    async def list_identity_documents(self, user_id: uuid.UUID) -> list[IdentityDocument]:
        return await self.documents.list_for_user(user_id)