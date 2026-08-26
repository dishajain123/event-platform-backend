"""Staff endpoints for invitations, acceptance, reassignment, and history."""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_scoped_role
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.staff.schemas import (
    StaffAssignmentCreateIn,
    StaffAssignmentHistoryOut,
    StaffAssignmentOut,
    StaffAssignmentReassignIn,
)
from app.modules.staff.service import StaffService

router = APIRouter(prefix="/events/{event_id}/staff", tags=["staff"])
accept_router = APIRouter(tags=["staff"])


def get_staff_service(db: AsyncSession = Depends(get_db)) -> StaffService:
    return StaffService(db)


@router.post(
    "/assignments",
    response_model=StaffAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def create_staff_assignment(
    event_id: str,
    payload: StaffAssignmentCreateIn,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.create_assignment(
        event_id=uuid.UUID(event_id),
        actor=current_user,
        invitee_mobile=payload.invitee_mobile,
        role_label=payload.role_label,
        full_name=payload.full_name,
        venue_id=payload.venue_id,
    )


@router.get(
    "/assignments",
    response_model=list[StaffAssignmentOut],
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def list_staff_assignments(
    event_id: str,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.list_assignments(event_id=uuid.UUID(event_id), actor=current_user)


@router.post(
    "/assignments/{assignment_id}/reassign",
    response_model=StaffAssignmentOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def reassign_staff_assignment(
    event_id: str,
    assignment_id: str,
    payload: StaffAssignmentReassignIn,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.reassign_assignment(
        uuid.UUID(assignment_id),
        current_user,
        invitee_mobile=payload.invitee_mobile,
        role_label=payload.role_label,
        full_name=payload.full_name,
        venue_id=payload.venue_id,
    )


@router.post(
    "/assignments/{assignment_id}/revoke",
    response_model=StaffAssignmentOut,
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def revoke_staff_assignment(
    event_id: str,
    assignment_id: str,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.revoke_assignment(uuid.UUID(assignment_id), current_user)


@router.get(
    "/assignments/{assignment_id}/history",
    response_model=list[StaffAssignmentHistoryOut],
    dependencies=[
        Depends(
            require_scoped_role(
                RoleName.EVENT_MANAGER,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )
    ],
)
async def list_staff_assignment_history(
    event_id: str,
    assignment_id: str,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.list_history(
        event_id=uuid.UUID(event_id), assignment_id=uuid.UUID(assignment_id), actor=current_user
    )


@accept_router.post(
    "/staff/assignments/{assignment_id}/accept",
    response_model=StaffAssignmentOut,
)
async def accept_staff_assignment(
    assignment_id: str,
    current_user: User = Depends(get_current_user),
    service: StaffService = Depends(get_staff_service),
):
    return await service.accept_assignment(uuid.UUID(assignment_id), current_user)
