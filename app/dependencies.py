"""
Shared FastAPI dependencies: get_current_user, require_role,
require_scoped_role. Every module's router imports from here rather
than reimplementing auth/permission checks.
"""
import uuid

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.database import get_db
from app.modules.identity.exceptions import InvalidTokenError
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository
from app.modules.rbac.models import RoleName
from app.redis_client import get_redis
from app.security import TokenType, decode_token

import jwt as _pyjwt

bearer_scheme = HTTPBearer(auto_error=True)
optional_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        claims = decode_token(token)
    except _pyjwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired token.") from exc

    if claims.get("type") != TokenType.ACCESS.value:
        raise InvalidTokenError("An access token is required for this endpoint.")

    user_id = uuid.UUID(claims["sub"])
    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        raise InvalidTokenError("User not found or inactive.")
    return user


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(optional_bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """
    For endpoints that serve BOTH an unauthenticated public audience and
    an authenticated Console audience with elevated visibility (e.g.
    the media gallery: the public/mobile app sees published items only,
    while Console staff managing the event need to see drafts too).
    Returns None on a missing or invalid token rather than raising —
    the caller decides what "not authenticated" means for that endpoint.
    """
    if credentials is None:
        return None
    try:
        claims = decode_token(credentials.credentials)
    except _pyjwt.PyJWTError:
        return None
    if claims.get("type") != TokenType.ACCESS.value:
        return None
    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError):
        return None
    user = await UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active:
        return None
    return user


def require_role(*allowed_roles: RoleName):
    """
    Dependency factory for GLOBAL roles. Use this on endpoints that are
    meant for platform-wide access, not event-scoped access.
    """
    allowed = set(allowed_roles)

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if not await user_has_global_role(db, current_user.id, allowed):
            raise PermissionDeniedError("You don't have permission to access this resource.")
        return current_user

    return _check


def require_scoped_role(
    *allowed_roles: RoleName,
    allow_global_roles: set[RoleName] | None = None,
):
    """
    Dependency factory for event-scoped roles. The event_id is read from
    the URL path, so this should only be used on routes whose path
    contains `{event_id}`.
    """
    allowed = set(allowed_roles)

    async def _check(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        raw_event_id = request.path_params.get("event_id")
        if raw_event_id is None:
            raise PermissionDeniedError("This endpoint requires an event_id in the path.")
        try:
            event_id = uuid.UUID(str(raw_event_id))
        except (TypeError, ValueError) as exc:
            raise PermissionDeniedError("Invalid event scope.") from exc

        if not await user_has_scoped_role(
            db,
            current_user.id,
            allowed,
            event_id,
            allow_global_roles=allow_global_roles,
        ):
            raise PermissionDeniedError("You don't have permission to access this event.")
        return current_user

    return _check
