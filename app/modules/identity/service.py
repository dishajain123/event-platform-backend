"""
Business logic for the identity module: OTP issuance/verification with
expiry, resend cooldown, and attempt limits (all enforced via Redis,
since OTP state is short-lived and doesn't belong in Postgres); JWT
session issuance; identity document encryption.
"""
import uuid
import hashlib
import time

from cryptography.fernet import Fernet
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import write_audit_log
from app.exceptions import PermissionDeniedError
from app.exceptions import RateLimitedError
from app.modules.identity.exceptions import (
    InvalidOTPError,
    OTPExpiredError,
    OTPResendTooSoonError,
    TooManyOTPAttemptsError,
    UserNotFoundError,
)
from app.modules.identity.models import DocumentType, IdentityDocument, User
from app.modules.identity.repository import IdentityDocumentRepository, UserRepository
from app.modules.identity.phone import normalize_mobile_number
from app.modules.rbac.models import AssignmentStatus, RoleName
from app.modules.rbac.repository import RoleAssignmentRepository
from app.modules.rbac.service import RBACService
from app.security import TokenType, create_token, generate_otp, hash_otp

settings = get_settings()


def _otp_redis_key(mobile_number: str) -> str:
    return f"otp:{mobile_number}"


def _otp_cooldown_key(mobile_number: str) -> str:
    return f"otp:cooldown:{mobile_number}"


def _otp_attempts_key(mobile_number: str) -> str:
    return f"otp:attempts:{mobile_number}"


def _request_limit_key(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:32]
    return f"otp:limit:{kind}:{digest}"


async def _claim_rate_limit(redis: Redis, key: str, seconds: int) -> bool:
    """Claim a Redis throttle key atomically, with compatibility for test doubles."""
    try:
        return bool(await redis.set(key, "1", ex=seconds, nx=True))
    except TypeError:
        if await redis.get(key):
            return False
        await redis.set(key, "1", ex=seconds)
        return True


class IdentityService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis
        self.users = UserRepository(db)
        self.documents = IdentityDocumentRepository(db)
        self.role_assignments = RoleAssignmentRepository(db)
        self.rbac = RBACService(db)

    # ---- OTP flow ----

    async def request_otp(
        self, mobile_number: str, *, client_ip: str | None = None, device_id: str | None = None
    ) -> int:
        """
        Generates and stores a hashed OTP with a TTL, enforces the resend
        cooldown, and (in a later phase) dispatches it via the SMS provider
        integration. Returns seconds until the next resend is allowed.
        """
        normalized_mobile = normalize_mobile_number(mobile_number)

        cooldown_key = _otp_cooldown_key(normalized_mobile)
        if await self.redis.get(cooldown_key):
            ttl = await self.redis.ttl(_otp_cooldown_key(normalized_mobile))
            raise OTPResendTooSoonError(
                f"Please wait {ttl} seconds before requesting another OTP."
            )
        if not await _claim_rate_limit(self.redis, cooldown_key, settings.otp_resend_cooldown_seconds):
            ttl = await self.redis.ttl(cooldown_key)
            raise OTPResendTooSoonError(f"Please wait {ttl} seconds before requesting another OTP.")

        if client_ip:
            ip_window = str(int(time.time()) // settings.otp_rate_limit_window_seconds)
            ip_key = _request_limit_key("ip", f"{client_ip}:{ip_window}")
            ip_count = await self.redis.incr(ip_key)
            await self.redis.expire(ip_key, settings.otp_rate_limit_window_seconds)
            if ip_count > settings.otp_ip_max_requests_per_window:
                raise RateLimitedError("Too many OTP requests. Please try again shortly.")
        if device_id:
            device_key = _request_limit_key("device", device_id)
            if not await _claim_rate_limit(self.redis, device_key, settings.otp_ip_cooldown_seconds):
                raise RateLimitedError("Too many OTP requests from this device. Please try again shortly.")
            await self.redis.set(device_key, "1", ex=settings.otp_ip_cooldown_seconds)
        window_key = _request_limit_key(
            "global", str(int(time.time()) // settings.otp_rate_limit_window_seconds)
        )
        count = await self.redis.incr(window_key)
        await self.redis.expire(window_key, settings.otp_rate_limit_window_seconds)
        if count > settings.otp_global_max_requests_per_window:
            raise RateLimitedError("OTP service is temporarily busy. Please try again shortly.")

        otp = generate_otp()
        hashed = hash_otp(otp, normalized_mobile)

        await self.redis.set(_otp_redis_key(normalized_mobile), hashed, ex=settings.otp_expiry_seconds)
        await self.redis.delete(_otp_attempts_key(normalized_mobile))

        # Phase 6 wires this to app/integrations/sms_provider.py for real dispatch.
        # For now (and for local/dev), the OTP is returned by the stub sender —
        # see app/integrations/sms_provider.py — never logged or returned in the API response.
        from app.integrations.sms_provider import send_otp_sms

        await send_otp_sms(normalized_mobile, otp)

        return settings.otp_resend_cooldown_seconds

    async def verify_otp(self, mobile_number: str, otp: str) -> User:
        normalized_mobile = normalize_mobile_number(mobile_number)
        attempts_key = _otp_attempts_key(normalized_mobile)
        attempts = int(await self.redis.get(attempts_key) or 0)
        if attempts >= settings.otp_max_verify_attempts:
            raise TooManyOTPAttemptsError(
                "Too many incorrect attempts. Please request a new OTP."
            )

        stored_hash = await self.redis.get(_otp_redis_key(normalized_mobile))
        if stored_hash is None:
            raise OTPExpiredError("This OTP has expired. Please request a new one.")

        if hash_otp(otp, normalized_mobile) != stored_hash:
            await self.redis.incr(attempts_key)
            await self.redis.expire(attempts_key, settings.otp_expiry_seconds)
            raise InvalidOTPError("Incorrect OTP.")

        # Success — OTP is single-use, clear it immediately.
        await self.redis.delete(_otp_redis_key(normalized_mobile))
        await self.redis.delete(attempts_key)

        user, _created = await self.users.get_or_create(normalized_mobile)
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

    async def find_or_create_for_admin_provisioning(
        self, mobile_number: str, name: str | None = None
    ) -> tuple[User, bool]:
        """
        Console-only path (see AdminUserLookupIn) for provisioning a
        global admin role — Operations Admin, Finance Admin, Finance
        Operator, Finance Auditor — for someone who may never have
        opened the public app. Reuses the same get_or_create the OTP
        flow already relies on, so there's exactly one place a User row
        is ever created from a mobile number, whichever path triggers it.
        """
        normalized_mobile = normalize_mobile_number(mobile_number)
        user, created = await self.users.get_or_create(normalized_mobile)
        if name and not user.name:
            user.name = name
        await self.db.commit()
        await self.db.refresh(user)
        return user, created

    async def list_accounts(self) -> list[dict]:
        users = await self.users.list_all()
        results: list[dict] = []

        for user in users:
            assignments = await self.role_assignments.list_for_user(user.id)
            roles: list[dict] = []
            for assignment in assignments:
                if assignment.status != AssignmentStatus.ACTIVE:
                    continue
                role = await self.rbac.roles.get_by_id(assignment.role_id)
                if role is None:
                    continue
                roles.append(
                    {
                        "role_name": role.name,
                        "event_id": assignment.event_id,
                        "status": assignment.status.value,
                    }
                )

            results.append(
                {
                    "id": user.id,
                    "mobile_number": user.mobile_number,
                    "name": user.name,
                    "email": user.email,
                    "is_active": user.is_active,
                    "roles": roles,
                }
            )

        return results

    async def page_accounts(self, *, page=1, page_size=25) -> tuple[list[dict], int]:
        users, total = await self.users.page_all(page=page, page_size=page_size)
        results = []
        for user in users:
            assignments = await self.role_assignments.list_for_user(user.id)
            roles = []
            for assignment in assignments:
                if assignment.status != AssignmentStatus.ACTIVE:
                    continue
                role = await self.rbac.roles.get_by_id(assignment.role_id)
                if role:
                    roles.append({"role_name": role.name, "event_id": assignment.event_id})
            results.append({"id": user.id, "mobile_number": user.mobile_number, "name": user.name, "email": user.email, "is_active": user.is_active, "roles": roles})
        return results, total

    async def update_account_status(
        self,
        *,
        actor: User,
        target_user_id: uuid.UUID,
        is_active: bool,
    ) -> User:
        target_user = await self.users.get_by_id(target_user_id)
        if target_user is None:
            raise UserNotFoundError("User not found.")

        actor_roles = await self.rbac.get_active_role_names_for_user(actor.id)
        target_roles = await self.rbac.get_active_role_names_for_user(target_user.id)

        if RoleName.SUPER_ADMIN not in actor_roles:
            if RoleName.OPERATIONS_ADMIN in actor_roles:
                disallowed = target_roles - {
                    RoleName.OPERATIONS_ADMIN,
                    RoleName.EVENT_MANAGER,
                    RoleName.EVENT_COORDINATOR,
                    RoleName.STAFF_LEAD,
                    RoleName.STAFF_MEMBER,
                }
                if disallowed:
                    raise PermissionDeniedError("You don't have permission to manage this account.")
            elif RoleName.FINANCE_ADMIN in actor_roles:
                disallowed = target_roles - {
                    RoleName.FINANCE_ADMIN,
                    RoleName.FINANCE_OPERATOR,
                    RoleName.FINANCE_AUDITOR,
                }
                if disallowed:
                    raise PermissionDeniedError("You don't have permission to manage this account.")
            else:
                raise PermissionDeniedError("You don't have permission to manage this account.")

        before = {"is_active": target_user.is_active}
        target_user.is_active = is_active
        await write_audit_log(
            self.db,
            entity_type="user",
            entity_id=target_user.id,
            action="updated_status",
            actor_user_id=actor.id,
            before_value=before,
            after_value={"is_active": is_active},
        )
        await self.db.commit()
        await self.db.refresh(target_user)
        return target_user

    async def update_own_profile(self, actor: User, *, name: str | None, email: str | None) -> User:
        """
        Closes a real gap: previously there was no way whatsoever for a
        user to change their own name or email — GET /users/me was the
        only endpoint touching a user's own profile at all. Deliberately
        takes `actor` as both the target and the caller (no target_user_id
        parameter) so this can never be used to edit someone else's
        profile — that would need a real admin-provisioning flow, not this.
        """
        before = {"name": actor.name, "email": actor.email}
        if name is not None:
            actor.name = name
        if email is not None:
            actor.email = email
        await write_audit_log(
            self.db,
            entity_type="user",
            entity_id=actor.id,
            action="updated_own_profile",
            actor_user_id=actor.id,
            before_value=before,
            after_value={"name": actor.name, "email": actor.email},
        )
        await self.db.commit()
        await self.db.refresh(actor)
        return actor

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
