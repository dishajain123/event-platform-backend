"""
Proves the OTP flow end-to-end: request -> verify -> user auto-created
-> tokens issued, plus the failure paths (wrong OTP, expired OTP,
too many attempts, resend cooldown).
"""
import pytest

from app.modules.identity.exceptions import (
    InvalidOTPError,
    OTPExpiredError,
    OTPResendTooSoonError,
    TooManyOTPAttemptsError,
)
from app.modules.identity.service import IdentityService
from app.security import decode_token


@pytest.mark.asyncio
async def test_otp_request_then_verify_creates_user_and_issues_tokens(db_session, fake_redis):
    service = IdentityService(db_session, fake_redis)
    mobile = "+919876543210"

    await service.request_otp(mobile)

    from app.security import hash_otp

    known_otp = "123456"
    fake_redis.store[f"otp:{mobile}"] = (hash_otp(known_otp, mobile), None)

    user = await service.verify_otp(mobile, known_otp)
    assert user.mobile_number == mobile

    access, refresh = service.issue_tokens(user.id)
    access_claims = decode_token(access)
    assert access_claims["sub"] == str(user.id)
    assert access_claims["type"] == "access"


@pytest.mark.asyncio
async def test_wrong_otp_is_rejected_and_counts_as_an_attempt(db_session, fake_redis):
    service = IdentityService(db_session, fake_redis)
    mobile = "+919876543211"

    from app.security import hash_otp

    fake_redis.store[f"otp:{mobile}"] = (hash_otp("111111", mobile), None)

    with pytest.raises(InvalidOTPError):
        await service.verify_otp(mobile, "000000")

    assert fake_redis.store[f"otp:attempts:{mobile}"][0] == "1"


@pytest.mark.asyncio
async def test_expired_otp_is_rejected(db_session, fake_redis):
    service = IdentityService(db_session, fake_redis)
    mobile = "+919876543212"
    with pytest.raises(OTPExpiredError):
        await service.verify_otp(mobile, "123456")


@pytest.mark.asyncio
async def test_too_many_attempts_is_rejected(db_session, fake_redis):
    service = IdentityService(db_session, fake_redis)
    mobile = "+919876543213"
    from app.security import hash_otp

    fake_redis.store[f"otp:{mobile}"] = (hash_otp("111111", mobile), None)
    fake_redis.store[f"otp:attempts:{mobile}"] = ("5", None)

    with pytest.raises(TooManyOTPAttemptsError):
        await service.verify_otp(mobile, "000000")


@pytest.mark.asyncio
async def test_resend_before_cooldown_expires_is_rejected(db_session, fake_redis):
    service = IdentityService(db_session, fake_redis)
    mobile = "+919876543214"

    await service.request_otp(mobile)
    with pytest.raises(OTPResendTooSoonError):
        await service.request_otp(mobile)

@pytest.mark.asyncio
async def test_user_can_update_their_own_name_and_email(db_session, fake_redis):
    """
    Regression test for a real gap found while building the mobile app's
    Profile screen: there was no way whatsoever for a user to change
    their own name or email — GET /users/me was the only endpoint
    touching a user's own profile at all.
    """
    from app.modules.identity.models import User

    user = User(mobile_number="+919700000001")
    db_session.add(user)
    await db_session.flush()
    assert user.name is None
    assert user.email is None

    service = IdentityService(db_session, fake_redis)
    updated = await service.update_own_profile(user, name="Asha Rao", email="asha@example.com")
    assert updated.name == "Asha Rao"
    assert updated.email == "asha@example.com"

    # A partial update (name only) leaves the other field untouched.
    updated_again = await service.update_own_profile(user, name="Asha R.", email=None)
    assert updated_again.name == "Asha R."
    assert updated_again.email == "asha@example.com"


@pytest.mark.asyncio
async def test_user_can_list_their_own_identity_documents_after_uploading(db_session, fake_redis, monkeypatch):
    """
    Regression test for a real gap found while building the mobile app's
    Profile screen: list_identity_documents() already existed correctly
    implemented in the service, but only the upload (POST) endpoint was
    ever wired to a router endpoint — a user who'd uploaded a document
    had no way to ever see it (or its verification status) again.
    """
    from cryptography.fernet import Fernet
    from app.modules.identity import service as identity_service_module
    from app.modules.identity.models import DocumentType, User

    monkeypatch.setattr(
        identity_service_module.settings, "identity_doc_encryption_key", Fernet.generate_key().decode()
    )

    user = User(mobile_number="+919700000002")
    db_session.add(user)
    await db_session.flush()

    service = IdentityService(db_session, fake_redis)
    await service.add_identity_document(user.id, DocumentType.AADHAAR, "123412341234")

    docs = await service.list_identity_documents(user.id)
    assert len(docs) == 1
    assert docs[0].document_type == DocumentType.AADHAAR