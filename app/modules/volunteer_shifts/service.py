import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.events.models import Event
from app.modules.notifications.service import NotificationService
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationStatus, VolunteerApplicationType
from app.modules.volunteer_shifts.models import (
    ACTIVE_SHIFT_STATUSES,
    ALLOWED_ASSIGNMENT_TRANSITIONS,
    ALLOWED_SHIFT_TRANSITIONS,
    ASSIGNABLE_STATUSES,
    VolunteerAssignmentStatus,
    VolunteerAttendance,
    VolunteerAttendanceStatus,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftStatus,
)
from app.modules.volunteer_shifts.repository import VolunteerShiftRepository
from app.modules.volunteer_shifts.schemas import EligibleVolunteerOut, ShiftOut


class VolunteerShiftService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = VolunteerShiftRepository(db)

    @staticmethod
    def _utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    async def _global(self, actor: User) -> bool:
        return await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})

    async def _manager(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db, actor.id, {RoleName.EVENT_MANAGER}, event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def _event_ids(self, actor: User, requested: uuid.UUID | None = None) -> set[uuid.UUID] | None:
        if await self._global(actor):
            return {requested} if requested else None
        ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        if requested is not None and requested not in ids:
            raise PermissionDeniedError("You don't have permission to access this event.")
        return {requested} if requested else ids

    async def _get_shift(self, shift_id: uuid.UUID, *, lock=False) -> VolunteerShift:
        shift = await self.repo.get_shift(shift_id, lock=lock)
        if shift is None:
            raise NotFoundError("Volunteer shift not found.")
        return shift

    async def _eligible_application(self, user_id: uuid.UUID, event_id: uuid.UUID, required_role: str | None):
        stmt = select(VolunteerApplication).where(
            VolunteerApplication.user_id == user_id,
            VolunteerApplication.event_id == event_id,
            VolunteerApplication.application_type == VolunteerApplicationType.VOLUNTEER,
            VolunteerApplication.status == VolunteerApplicationStatus.APPROVED,
        )
        application = (await self.db.execute(stmt)).scalar_one_or_none()
        if application is None:
            raise PermissionDeniedError("Only approved volunteers can be assigned to this shift.")
        if required_role:
            haystack = " ".join(filter(None, [application.preferred_responsibility, application.skills_experience])).lower()
            if required_role.lower() not in haystack:
                raise PermissionDeniedError("The volunteer does not meet this shift's role requirement.")
        return application

    async def _audit(self, entity_type, entity_id, action, actor_id, before=None, after=None):
        await write_audit_log(self.db, entity_type=entity_type, entity_id=entity_id, action=action,
                              actor_user_id=actor_id, before_value=before, after_value=after)

    async def _notify(self, *, event_id, user_id, title, body, kind, dedupe, metadata):
        try:
            notification = NotificationService(self.db)
            await notification._queue_automated(
                event_id=event_id, user_id=user_id, title=title, body=body,
                notification_type="volunteer_shift", dedupe_key=dedupe, target_metadata=metadata,
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()

    async def create_shift(self, actor: User, event_id: uuid.UUID, payload):
        if not await self._manager(actor, event_id):
            raise PermissionDeniedError("You don't have permission to manage shifts for this event.")
        if await self.db.get(Event, event_id) is None:
            raise NotFoundError("Event not found.")
        if payload.starts_at >= payload.ends_at:
            raise ValidationError("starts_at must be before ends_at.")
        if payload.status not in {VolunteerShiftStatus.DRAFT, VolunteerShiftStatus.OPEN}:
            raise ValidationError("A new shift can only start as draft or open.")
        shift = VolunteerShift(event_id=event_id, **payload.model_dump())
        self.db.add(shift)
        await self.db.flush()
        await self._audit("volunteer_shift", shift.id, "created", actor.id, after={"event_id": str(event_id)})
        await self.db.commit()
        await self.db.refresh(shift)
        return await self._shift_out(shift)

    async def update_shift(self, actor: User, shift_id: uuid.UUID, payload):
        shift = await self._get_shift(shift_id, lock=True)
        if not await self._manager(actor, shift.event_id):
            raise PermissionDeniedError("You don't have permission to manage this shift.")
        values = payload.model_dump(exclude_unset=True)
        start = values.get("starts_at", shift.starts_at)
        end = values.get("ends_at", shift.ends_at)
        if start >= end:
            raise ValidationError("starts_at must be before ends_at.")
        if "required_count" in values and values["required_count"] < await self.repo.count_assigned(shift.id):
            raise ValidationError("required_count cannot be below the assigned volunteer count.")
        requested_status = values.get("status")
        if requested_status is not None and requested_status != shift.status:
            if requested_status in {VolunteerShiftStatus.FULL, VolunteerShiftStatus.IN_PROGRESS, VolunteerShiftStatus.COMPLETED}:
                raise ValidationError("This shift status is managed by assignment and attendance actions.")
            if requested_status not in ALLOWED_SHIFT_TRANSITIONS[shift.status]:
                raise ValidationError(f"Cannot move shift from {shift.status} to {requested_status}.")
        before = {"status": shift.status.value, "starts_at": shift.starts_at.isoformat(), "ends_at": shift.ends_at.isoformat()}
        for key, value in values.items():
            setattr(shift, key, value)
        await self._audit("volunteer_shift", shift.id, "updated", actor.id, before=before,
                          after={"status": shift.status.value})
        await self.db.commit(); await self.db.refresh(shift)
        if values.get("status") in {VolunteerShiftStatus.CANCELLED} or any(
            key in values for key in {"starts_at", "ends_at", "location", "title"}
        ):
            recipients = await self.repo.user_ids_for_shift(shift.id)
            change_key = shift.updated_at.isoformat()
            shift_status = shift.status.value
            for user_id in recipients:
                await self._notify(
                    event_id=shift.event_id, user_id=user_id, title="Volunteer shift changed",
                    body="A volunteer shift you requested or accepted has changed.", kind="shift_change",
                    dedupe=f"volunteer-shift:{shift.id}:changed:{change_key}",
                    metadata={"shift_id": str(shift.id), "status": shift_status},
                )
            await self.db.refresh(shift)
        return await self._shift_out(shift)

    async def list_shifts(self, actor: User, *, event_id=None, page=1, page_size=25, search=None, status=None):
        ids = await self._event_ids(actor, event_id)
        rows, total = await self.repo.list_shifts(ids, page=page, page_size=page_size, search=search, status=status)
        return [await self._shift_out(row) for row in rows], total

    async def list_available(self, *, page=1, page_size=25, search=None):
        rows, total = await self.repo.list_shifts(None, page=page, page_size=page_size, search=search, status=VolunteerShiftStatus.OPEN)
        return [await self._shift_out(row) for row in rows], total

    async def _shift_out(self, shift):
        assigned = await self.repo.count_assigned(shift.id)
        return ShiftOut.model_validate({**shift.__dict__, "assigned_count": assigned, "available_count": max(0, shift.required_count - assigned)})

    async def get_visible_shift(self, actor: User, shift_id: uuid.UUID):
        shift = await self._get_shift(shift_id)
        if await self._manager(actor, shift.event_id):
            return await self._shift_out(shift)
        assignment = await self.repo.assignment_for_user(shift.id, actor.id)
        if assignment is None:
            raise PermissionDeniedError("You cannot access this shift.")
        return await self._shift_out(shift)

    async def eligible_volunteers(self, actor: User, shift_id: uuid.UUID, *, page=1, page_size=25, search=None):
        shift = await self._get_shift(shift_id)
        if not await self._manager(actor, shift.event_id):
            raise PermissionDeniedError("You don't have permission to view eligible volunteers for this shift.")
        rows, total = await self.repo.eligible_volunteers(
            shift.event_id, shift_id=shift.id, starts_at=shift.starts_at, ends_at=shift.ends_at,
            required_role=shift.required_role, page=page, page_size=page_size, search=search,
        )
        return [EligibleVolunteerOut(user_id=row.user_id, application_id=row.id, full_name=row.full_name, preferred_responsibility=row.preferred_responsibility) for row in rows], total

    async def _create_assignment(self, actor: User, shift: VolunteerShift, user_id: uuid.UUID, *, requested: bool):
        application = await self._eligible_application(user_id, shift.event_id, shift.required_role)
        if await self.repo.assignment_for_user(shift.id, user_id):
            raise ConflictError("This volunteer already has an assignment for this shift.")
        if shift.status == VolunteerShiftStatus.FULL:
            raise ConflictError("This shift is full.")
        if shift.status != VolunteerShiftStatus.OPEN:
            raise ValidationError("This shift is not accepting assignments.")
        if not requested and await self.repo.overlap(user_id, shift.starts_at, shift.ends_at):
            raise ConflictError("This volunteer has an overlapping approved or active shift.")
        if not requested:
            assigned = await self.repo.count_assigned(shift.id)
            if assigned >= shift.required_count:
                shift.status = VolunteerShiftStatus.FULL
                await self.db.flush()
                raise ConflictError("This shift is full.")
        assignment = VolunteerShiftAssignment(
            event_id=shift.event_id, shift_id=shift.id, user_id=user_id,
            volunteer_application_id=application.id, requested_by=actor.id,
            status=VolunteerAssignmentStatus.REQUESTED if requested else VolunteerAssignmentStatus.APPROVED,
            reviewed_by=None if requested else actor.id,
            reviewed_at=None if requested else datetime.now(timezone.utc),
        )
        self.db.add(assignment)
        await self.db.flush()
        await self._sync_status(shift)
        await self._audit("volunteer_shift_assignment", assignment.id, "requested" if requested else "approved", actor.id,
                          after={"shift_id": str(shift.id), "user_id": str(user_id), "status": assignment.status.value})
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            raise ConflictError("This volunteer already has an assignment for this shift.") from exc
        await self.db.refresh(assignment)
        await self._notify(event_id=shift.event_id, user_id=user_id,
                           title="Volunteer shift update", body="You have a new volunteer shift assignment.",
                           kind="assignment", dedupe=f"volunteer-shift:{assignment.id}:created",
                           metadata={"shift_id": str(shift.id), "assignment_id": str(assignment.id)})
        await self.db.refresh(assignment)
        return assignment

    async def request_shift(self, actor: User, shift_id: uuid.UUID):
        shift = await self._get_shift(shift_id, lock=True)
        return await self._create_assignment(actor, shift, actor.id, requested=True)

    async def assign_shift(self, actor: User, shift_id: uuid.UUID, user_id: uuid.UUID):
        shift = await self._get_shift(shift_id, lock=True)
        if not await self._manager(actor, shift.event_id):
            raise PermissionDeniedError("You don't have permission to assign this shift.")
        return await self._create_assignment(actor, shift, user_id, requested=False)

    async def list_assignments(self, actor: User, *, event_id=None, shift_id=None, user_id=None, page=1, page_size=25, status=None, search=None):
        if user_id is not None and user_id != actor.id and not (await self._global(actor)):
            raise PermissionDeniedError("You cannot access another volunteer's assignments.")
        ids = await self._event_ids(actor, event_id)
        if shift_id:
            shift = await self._get_shift(shift_id)
            if ids is not None and shift.event_id not in ids:
                raise PermissionDeniedError("You don't have permission to access this event.")
            if user_id is None and not await self._manager(actor, shift.event_id):
                user_id = actor.id
        elif user_id is None and not (await self._global(actor)):
            user_id = actor.id
        return await self.repo.list_assignments(event_ids=ids, user_id=user_id, shift_id=shift_id, page=page, page_size=page_size, status=status, search=search)

    async def update_assignment(self, actor: User, assignment_id: uuid.UUID, status: VolunteerAssignmentStatus):
        assignment = await self.repo.assignment(assignment_id, lock=True)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        manager = await self._manager(actor, assignment.event_id)
        if actor.id != assignment.user_id and not manager:
            raise PermissionDeniedError("You cannot modify this assignment.")
        if status in {VolunteerAssignmentStatus.APPROVED, VolunteerAssignmentStatus.REJECTED} and not manager:
            raise PermissionDeniedError("Only an event manager can review a shift request.")
        if status not in ALLOWED_ASSIGNMENT_TRANSITIONS[assignment.status]:
            raise ValidationError(f"Cannot move assignment from {assignment.status} to {status}.")
        shift = await self._get_shift(assignment.shift_id, lock=True)
        if shift.status in {VolunteerShiftStatus.CANCELLED, VolunteerShiftStatus.COMPLETED}:
            raise ValidationError("This shift is no longer accepting attendance.")
        if status == VolunteerAssignmentStatus.APPROVED:
            await self._eligible_application(assignment.user_id, assignment.event_id, shift.required_role)
            if await self.repo.overlap(assignment.user_id, shift.starts_at, shift.ends_at, exclude_shift_id=shift.id):
                raise ConflictError("This volunteer has an overlapping approved or active shift.")
            if await self.repo.count_assigned(shift.id) >= shift.required_count:
                raise ConflictError("This shift is full.")
        before = assignment.status.value
        assignment.status = status
        assignment.reviewed_by = actor.id
        assignment.reviewed_at = datetime.now(timezone.utc)
        if status == VolunteerAssignmentStatus.CANCELLED:
            attendance = await self.repo.attendance(assignment.id, lock=True)
            if attendance and attendance.status == VolunteerAttendanceStatus.CHECKED_IN:
                attendance.status = VolunteerAttendanceStatus.CANCELLED
                await self.db.flush()
                await self._audit("volunteer_attendance", attendance.id, "cancelled", actor.id,
                                  after={"assignment_id": str(assignment.id)})
        await self._sync_status(shift)
        await self._audit("volunteer_shift_assignment", assignment.id, status.value, actor.id,
                          before={"status": before}, after={"status": status.value})
        await self.db.commit(); await self.db.refresh(assignment)
        if status in {VolunteerAssignmentStatus.APPROVED, VolunteerAssignmentStatus.REJECTED, VolunteerAssignmentStatus.CANCELLED}:
            await self._notify(event_id=assignment.event_id, user_id=assignment.user_id,
                               title="Volunteer assignment update", body=f"Your shift assignment is {status.value}.",
                               kind="assignment", dedupe=f"volunteer-shift:{assignment.id}:{status.value}", metadata={"assignment_id": str(assignment.id)})
            await self.db.refresh(assignment)
        return assignment

    async def get_assignment_visible(self, actor: User, assignment_id: uuid.UUID):
        assignment = await self.repo.assignment(assignment_id)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        if actor.id != assignment.user_id and not await self._manager(actor, assignment.event_id):
            raise PermissionDeniedError("You cannot access this assignment.")
        shift = await self._get_shift(assignment.shift_id)
        attendance = await self.repo.attendance(assignment.id)
        from app.modules.volunteer_shifts.schemas import AssignmentDetailOut
        return AssignmentDetailOut.model_validate({
            **assignment.__dict__,
            "shift": await self._shift_out(shift),
            "attendance": attendance,
        })

    async def _sync_status(self, shift):
        assigned = await self.repo.count_assigned(shift.id)
        if shift.status in {VolunteerShiftStatus.OPEN, VolunteerShiftStatus.FULL}:
            shift.status = VolunteerShiftStatus.FULL if assigned >= shift.required_count else VolunteerShiftStatus.OPEN

    async def check_in(self, actor: User, assignment_id: uuid.UUID):
        assignment = await self.repo.assignment(assignment_id, lock=True)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        if actor.id != assignment.user_id and not await user_has_scoped_role(
            self.db, actor.id, {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER},
            assignment.event_id, allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
        ):
            raise PermissionDeniedError("You cannot check in this volunteer.")
        attendance = await self.repo.attendance(assignment.id, lock=True)
        if attendance and attendance.status != VolunteerAttendanceStatus.NOT_CHECKED_IN:
            raise ConflictError("This assignment has already checked in.")
        if assignment.status != VolunteerAssignmentStatus.APPROVED:
            raise ValidationError("Only approved assignments can check in.")
        shift = await self._get_shift(assignment.shift_id, lock=True)
        now = datetime.now(timezone.utc)
        if now < self._utc(shift.starts_at):
            raise ValidationError("Check-in is not open for this shift yet.")
        if attendance is None:
            attendance = VolunteerAttendance(event_id=assignment.event_id, shift_id=assignment.shift_id, assignment_id=assignment.id, user_id=assignment.user_id, status=VolunteerAttendanceStatus.CHECKED_IN, first_check_in_at=now)
            self.db.add(attendance)
        else:
            attendance.status = VolunteerAttendanceStatus.CHECKED_IN; attendance.first_check_in_at = attendance.first_check_in_at or now
        assignment.status = VolunteerAssignmentStatus.ACTIVE; assignment.check_in_at = now
        shift.status = VolunteerShiftStatus.IN_PROGRESS
        await self.db.flush()
        await self._audit("volunteer_attendance", attendance.id, "checked_in", actor.id, after={"assignment_id": str(assignment.id)})
        await self.db.commit(); await self.db.refresh(attendance)
        return attendance

    async def check_out(self, actor: User, assignment_id: uuid.UUID):
        assignment = await self.repo.assignment(assignment_id, lock=True)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        if actor.id != assignment.user_id and not await self._manager(actor, assignment.event_id):
            raise PermissionDeniedError("You cannot check out this volunteer.")
        if assignment.status != VolunteerAssignmentStatus.ACTIVE:
            raise ValidationError("Only active assignments can check out.")
        attendance = await self.repo.attendance(assignment.id, lock=True)
        if attendance is None or attendance.status != VolunteerAttendanceStatus.CHECKED_IN:
            raise ValidationError("Check-out requires a successful check-in.")
        now = datetime.now(timezone.utc)
        attendance.status = VolunteerAttendanceStatus.CHECKED_OUT
        attendance.final_check_out_at = now
        attendance.worked_seconds = max(0, int((now - self._utc(attendance.first_check_in_at)).total_seconds()))
        assignment.status = VolunteerAssignmentStatus.COMPLETED; assignment.check_out_at = now
        shift = await self._get_shift(assignment.shift_id, lock=True)
        if now >= self._utc(shift.ends_at):
            shift.status = VolunteerShiftStatus.COMPLETED
        await self.db.flush()
        await self._audit("volunteer_attendance", attendance.id, "checked_out", actor.id, after={"worked_seconds": attendance.worked_seconds})
        await self.db.commit(); await self.db.refresh(attendance)
        return attendance

    async def get_attendance(self, actor: User, assignment_id: uuid.UUID):
        assignment = await self.repo.assignment(assignment_id)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        if actor.id != assignment.user_id and not await self._manager(actor, assignment.event_id):
            raise PermissionDeniedError("You cannot access this volunteer attendance.")
        return await self.repo.attendance(assignment_id)

    async def mark_no_show(self, actor: User, assignment_id: uuid.UUID):
        assignment = await self.repo.assignment(assignment_id, lock=True)
        if assignment is None:
            raise NotFoundError("Volunteer shift assignment not found.")
        if not await self._manager(actor, assignment.event_id):
            raise PermissionDeniedError("Only an event manager can mark a volunteer as no-show.")
        shift = await self._get_shift(assignment.shift_id, lock=True)
        if datetime.now(timezone.utc) < self._utc(shift.ends_at):
            raise ValidationError("A volunteer cannot be marked no-show before the shift ends.")
        if assignment.status != VolunteerAssignmentStatus.APPROVED:
            raise ValidationError("Only an approved, unchecked-in assignment can be marked no-show.")
        if await self.repo.attendance(assignment.id):
            raise ConflictError("Attendance already exists for this assignment.")
        attendance = VolunteerAttendance(
            event_id=assignment.event_id, shift_id=assignment.shift_id, assignment_id=assignment.id,
            user_id=assignment.user_id, status=VolunteerAttendanceStatus.NO_SHOW,
        )
        self.db.add(attendance)
        await self.db.flush()
        await self._audit("volunteer_attendance", attendance.id, "no_show", actor.id,
                          after={"assignment_id": str(assignment.id)})
        await self.db.commit(); await self.db.refresh(attendance)
        return attendance
