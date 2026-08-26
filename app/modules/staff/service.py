"""Business logic for staff invitation, activation, and reassignment."""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.integrations.sms_provider import send_staff_invite_sms
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.staff.exceptions import (
    InvalidStaffAssignmentStateError,
    StaffAssignmentConflictError,
    StaffAssignmentNotFoundError,
)
from app.modules.staff.models import StaffAssignment, StaffAssignmentHistory, StaffAssignmentStatus
from app.modules.staff.repository import StaffAssignmentHistoryRepository, StaffAssignmentRepository


class StaffService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.assignments = StaffAssignmentRepository(db)
        self.history = StaffAssignmentHistoryRepository(db)

    async def _can_manage_event(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    def _snapshot(self, assignment: StaffAssignment) -> dict:
        return {
            "event_id": str(assignment.event_id),
            "venue_id": str(assignment.venue_id) if assignment.venue_id else None,
            "user_id": str(assignment.user_id) if assignment.user_id else None,
            "invitee_mobile": assignment.invitee_mobile,
            "full_name": assignment.full_name,
            "role_label": assignment.role_label,
            "status": assignment.status.value,
            "invited_by": str(assignment.invited_by),
            "accepted_by": str(assignment.accepted_by) if assignment.accepted_by else None,
            "revoked_by": str(assignment.revoked_by) if assignment.revoked_by else None,
            "superseded_by_id": str(assignment.superseded_by_id) if assignment.superseded_by_id else None,
        }

    async def _get_assignment_or_raise(self, assignment_id: uuid.UUID) -> StaffAssignment:
        assignment = await self.assignments.get_by_id(assignment_id)
        if assignment is None:
            raise StaffAssignmentNotFoundError("Staff assignment not found.")
        return assignment

    async def create_assignment(
        self, *, event_id: uuid.UUID, actor: User, invitee_mobile: str, role_label: str,
        full_name: str | None = None, venue_id: uuid.UUID | None = None
    ) -> StaffAssignment:
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to manage staff for this event.")

        conflict = await self.assignments.find_active_conflict(
            event_id=event_id, invitee_mobile=invitee_mobile, role_label=role_label, venue_id=venue_id
        )
        if conflict is not None:
            raise StaffAssignmentConflictError("An active staff assignment already exists.")

        assignment = await self.assignments.create(
            event_id=event_id,
            venue_id=venue_id,
            invitee_mobile=invitee_mobile,
            full_name=full_name,
            role_label=role_label,
            status=StaffAssignmentStatus.INVITED,
            invited_by=actor.id,
        )
        await self.history.create(
            assignment_id=assignment.id,
            action="created",
            actor_user_id=actor.id,
            before_value=None,
            after_value=self._snapshot(assignment),
            notes="Staff invitation created.",
        )
        await write_audit_log(
            self.db,
            entity_type="staff_assignment",
            entity_id=assignment.id,
            action="created",
            actor_user_id=actor.id,
            after_value=self._snapshot(assignment),
        )
        await send_staff_invite_sms(invitee_mobile, role_label)
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def list_assignments(self, *, event_id: uuid.UUID, actor: User) -> list[StaffAssignment]:
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to view staff for this event.")
        return await self.assignments.list_for_event(event_id)

    async def accept_assignment(self, assignment_id: uuid.UUID, actor: User) -> StaffAssignment:
        assignment = await self._get_assignment_or_raise(assignment_id)
        if assignment.status == StaffAssignmentStatus.REVOKED:
            raise InvalidStaffAssignmentStateError("This assignment has been revoked.")
        if assignment.invitee_mobile != actor.mobile_number:
            raise InvalidStaffAssignmentStateError("This invitation was not issued to your mobile number.")

        before = self._snapshot(assignment)
        assignment.user_id = actor.id
        assignment.status = StaffAssignmentStatus.ACTIVE
        assignment.accepted_by = actor.id
        assignment.accepted_at = datetime.now(timezone.utc)
        if assignment.full_name is None and actor.name:
            assignment.full_name = actor.name

        await self.history.create(
            assignment_id=assignment.id,
            action="accepted",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(assignment),
            notes="Staff invitation accepted.",
        )
        await write_audit_log(
            self.db,
            entity_type="staff_assignment",
            entity_id=assignment.id,
            action="accepted",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(assignment),
        )
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def reassign_assignment(
        self, assignment_id: uuid.UUID, actor: User, *, invitee_mobile: str | None = None,
        role_label: str | None = None, full_name: str | None = None, venue_id: uuid.UUID | None = None
    ) -> StaffAssignment:
        old_assignment = await self._get_assignment_or_raise(assignment_id)
        if not await self._can_manage_event(actor, old_assignment.event_id):
            raise PermissionDeniedError("You don't have permission to manage staff for this event.")

        before = self._snapshot(old_assignment)
        old_assignment.status = StaffAssignmentStatus.REVOKED
        old_assignment.revoked_by = actor.id
        old_assignment.revoked_at = datetime.now(timezone.utc)

        new_assignment = await self.assignments.create(
            event_id=old_assignment.event_id,
            venue_id=venue_id if venue_id is not None else old_assignment.venue_id,
            invitee_mobile=invitee_mobile or old_assignment.invitee_mobile,
            full_name=full_name if full_name is not None else old_assignment.full_name,
            role_label=role_label or old_assignment.role_label,
            status=StaffAssignmentStatus.INVITED,
            invited_by=actor.id,
        )
        old_assignment.superseded_by_id = new_assignment.id
        await self.history.create(
            assignment_id=old_assignment.id,
            action="reassigned_out",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(old_assignment),
            notes="Assignment was superseded by a new invitation.",
        )
        await self.history.create(
            assignment_id=new_assignment.id,
            action="reassigned_in",
            actor_user_id=actor.id,
            before_value=None,
            after_value=self._snapshot(new_assignment),
            notes="Replacement assignment created.",
        )
        await write_audit_log(
            self.db,
            entity_type="staff_assignment",
            entity_id=new_assignment.id,
            action="reassigned",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(new_assignment),
        )
        await send_staff_invite_sms(new_assignment.invitee_mobile, new_assignment.role_label)
        await self.db.commit()
        await self.db.refresh(new_assignment)
        return new_assignment

    async def revoke_assignment(self, assignment_id: uuid.UUID, actor: User, *, reason: str | None = None) -> StaffAssignment:
        assignment = await self._get_assignment_or_raise(assignment_id)
        if not await self._can_manage_event(actor, assignment.event_id):
            raise PermissionDeniedError("You don't have permission to manage staff for this event.")
        if assignment.status == StaffAssignmentStatus.REVOKED:
            raise InvalidStaffAssignmentStateError("This assignment is already revoked.")

        before = self._snapshot(assignment)
        assignment.status = StaffAssignmentStatus.REVOKED
        assignment.revoked_by = actor.id
        assignment.revoked_at = datetime.now(timezone.utc)
        await self.history.create(
            assignment_id=assignment.id,
            action="revoked",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(assignment),
            notes=reason,
        )
        await write_audit_log(
            self.db,
            entity_type="staff_assignment",
            entity_id=assignment.id,
            action="revoked",
            actor_user_id=actor.id,
            before_value=before,
            after_value=self._snapshot(assignment),
        )
        await self.db.commit()
        await self.db.refresh(assignment)
        return assignment

    async def list_history(
        self, *, event_id: uuid.UUID, assignment_id: uuid.UUID, actor: User
    ) -> list[StaffAssignmentHistory]:
        assignment = await self._get_assignment_or_raise(assignment_id)
        if assignment.event_id != event_id:
            raise StaffAssignmentNotFoundError("Staff assignment not found for this event.")
        if not await self._can_manage_event(actor, event_id):
            raise PermissionDeniedError("You don't have permission to view staff history for this event.")
        return await self.history.list_for_assignment(assignment_id)
