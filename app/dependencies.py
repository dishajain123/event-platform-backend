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
from app.database import get_db
from app.modules.identity.exceptions import InvalidTokenError
from app.modules.identity.models import User
from app.modules.identity.repository import UserRepository
from app.modules.rbac.models import RoleName
from app.redis_client import get_redis
from app.security import TokenType, decode_token

import jwt as _pyjwt

bearer_scheme = HTTPBearer(auto_error=True)


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


def require_role(*allowed_roles: RoleName):
    """
    Dependency factory for GLOBAL roles (Super Admin, Operations Admin,
    Finance Admin, Finance Operator, Finance Auditor). Use on any Console
    endpoint that isn't scoped to a single event.

    Usage: dependencies=[Depends(require_role(RoleName.SUPER_ADMIN))]
    """

    async def _check(
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.exceptions import PermissionDeniedError

        allowed = set(allowed_roles)
        if not await user_has_global_role(db, current_user.id, allowed):
            raise PermissionDeniedError(
                "You don't have permission to perform this action."
            )
        return current_user

    return _check


def require_scoped_role(
    *allowed_roles: RoleName,
    event_id_param: str = "event_id",
    allow_global_roles: set[RoleName] | None = None,
):
    """
    Dependency factory for EVENT-SCOPED roles (Event Manager, Event
    Coordinator, Staff Lead, Staff Member). Reads event_id from the
    path parameters and checks the caller has an active assignment to
    one of allowed_roles for THAT SPECIFIC event — an Event Manager for
    event A is correctly rejected when calling an endpoint for event B.

    allow_global_roles lets platform-wide roles (typically Super Admin /
    Operations Admin) bypass the scope check, since they're meant to
    reach every event.
    """

    async def _check(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        from app.exceptions import PermissionDeniedError

        raw_event_id = request.path_params.get(event_id_param)
        if raw_event_id is None:
            raise PermissionDeniedError(
                f"Path parameter '{event_id_param}' is required for this scoped endpoint."
            )
        event_id = uuid.UUID(raw_event_id)

        allowed = set(allowed_roles)
        has_access = await user_has_scoped_role(
            db, current_user.id, allowed, event_id, allow_global_roles=allow_global_roles
        )
        if not has_access:
            raise PermissionDeniedError(
                "You don't have permission to perform this action for this event."
            )
        return current_user

    return _check


def get_redis_dep() -> Redis:
    return get_redis()