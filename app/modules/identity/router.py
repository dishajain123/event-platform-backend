"""
Identity endpoints — auth (used by both mobile app and console) and
identity document management.
"""
from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.identity.models import User
from app.modules.identity.schemas import (
    IdentityDocumentIn,
    IdentityDocumentOut,
    OTPRequestIn,
    OTPRequestOut,
    OTPVerifyIn,
    RefreshTokenIn,
    TokenPairOut,
    UserOut,
)
from app.modules.identity.service import IdentityService
from app.redis_client import get_redis
from app.security import TokenType, create_token, decode_token

router = APIRouter(tags=["identity"])


def get_identity_service(
    db: AsyncSession = Depends(get_db), redis: Redis = Depends(get_redis)
) -> IdentityService:
    return IdentityService(db, redis)


@router.post("/auth/otp/request", response_model=OTPRequestOut)
async def request_otp(
    payload: OTPRequestIn, service: IdentityService = Depends(get_identity_service)
) -> OTPRequestOut:
    """Called by: both mobile app (visitor/staff signup+login) and console (staff login)."""
    cooldown = await service.request_otp(payload.mobile_number)
    return OTPRequestOut(
        message="OTP sent.",
        resend_available_in_seconds=cooldown,
    )


@router.post("/auth/otp/verify", response_model=TokenPairOut)
async def verify_otp(
    payload: OTPVerifyIn, service: IdentityService = Depends(get_identity_service)
) -> TokenPairOut:
    """Called by: both. On success, issues an access + refresh token pair."""
    user = await service.verify_otp(payload.mobile_number, payload.otp)
    access, refresh = service.issue_tokens(user.id)
    return TokenPairOut(access_token=access, refresh_token=refresh)


@router.post("/auth/refresh", response_model=TokenPairOut)
async def refresh_token(payload: RefreshTokenIn) -> TokenPairOut:
    """Called by: both. Exchanges a valid refresh token for a new access token."""
    claims = decode_token(payload.refresh_token)
    if claims.get("type") != TokenType.REFRESH.value:
        from app.modules.identity.exceptions import InvalidTokenError

        raise InvalidTokenError("Not a refresh token.")
    import uuid as _uuid

    new_access = create_token(_uuid.UUID(claims["sub"]), TokenType.ACCESS)
    return TokenPairOut(access_token=new_access, refresh_token=payload.refresh_token)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    """
    Called by: both. Stateless JWTs mean logout is primarily a client-side
    token-discard; a token-blocklist in Redis can be added here later if
    server-side revocation becomes a requirement.
    """
    return None


@router.get("/users/me", response_model=UserOut)
async def get_my_profile(current_user: User = Depends(get_current_user)) -> User:
    """Called by: both."""
    return current_user


@router.post(
    "/users/me/identity-documents",
    response_model=IdentityDocumentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_my_identity_document(
    payload: IdentityDocumentIn,
    current_user: User = Depends(get_current_user),
    service: IdentityService = Depends(get_identity_service),
) -> IdentityDocumentOut:
    """Called by: mobile app (self-upload only — you can only add your own documents)."""
    doc = await service.add_identity_document(
        current_user.id, payload.document_type, payload.document_number
    )
    return IdentityDocumentOut.model_validate(doc)