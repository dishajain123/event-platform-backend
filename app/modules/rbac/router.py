"""
RBAC endpoints. Role assignment is Super Admin / Operations Admin only
(Operations Admin creates every field-role account per the platform's
account model; Super Admin can additionally create the other global
admin roles).
"""
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.rbac.schemas import MyRoleAssignmentOut, RoleAssignmentIn, RoleAssignmentOut, RoleOut
from app.modules.rbac.service import RBACService
from app.modules.rbac.models import RoleName

router = APIRouter(tags=["rbac"])


def get_rbac_service(db: AsyncSession = Depends(get_db)) -> RBACService:
    return RBACService(db)


@router.get("/users/me/role-assignments", response_model=list[MyRoleAssignmentOut])
async def list_my_role_assignments(
    current_user: User = Depends(get_current_user),
    service: RBACService = Depends(get_rbac_service),
):
    """
    Called by: both console and mobile app, immediately after login —
    the only way a client can discover what roles the current session
    actually holds (and which events it's scoped to). Open to any
    authenticated user for their OWN assignments only; there is no
    user_id parameter, so this can never be used to enumerate anyone
    else's roles.
    """
    return await service.list_my_active_role_assignments(current_user.id)


@router.get(
    "/roles",
    response_model=list[RoleOut],
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def list_roles(service: RBACService = Depends(get_rbac_service)):
    """Called by: console."""
    return await service.list_roles()


@router.post(
    "/users/{user_id}/role-assignments",
    response_model=RoleAssignmentOut,
    status_code=status.HTTP_201_CREATED,
)
async def assign_role(
    user_id: str,
    payload: RoleAssignmentIn,
    current_user: User = Depends(
        require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN)
    ),
    service: RBACService = Depends(get_rbac_service),
):
    """Called by: console (Super Admin / Operations Admin)."""
    import uuid as _uuid

    assignment = await service.assign_role(
        target_user_id=_uuid.UUID(user_id),
        role_name=payload.role_name,
        event_id=payload.event_id,
        assigned_by=current_user.id,
    )
    return assignment