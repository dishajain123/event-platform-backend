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