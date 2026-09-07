import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.models import Event
from app.modules.identity.models import User
from app.modules.incidents.models import Incident, IncidentSeverity, IncidentStatus
from app.modules.incidents.repository import IncidentRepository
from app.modules.incidents.schemas import IncidentCreateIn, IncidentUpdateIn
from app.modules.notifications.models import NotificationChannel, NotificationDeliveryStatus
from app.modules.notifications.repository import NotificationRepository
from app.modules.rbac.models import RoleName


MANAGE_ROLES = {RoleName.EVENT_MANAGER}
GLOBAL_ROLES = {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}
REPORT_ROLES = {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR, RoleName.STAFF_LEAD, RoleName.STAFF_MEMBER}
TERMINAL = {IncidentStatus.CLOSED, IncidentStatus.CANCELLED}
TRANSITIONS = {
    IncidentStatus.OPEN: {IncidentStatus.ACKNOWLEDGED, IncidentStatus.IN_PROGRESS, IncidentStatus.CANCELLED},
    IncidentStatus.ACKNOWLEDGED: {IncidentStatus.IN_PROGRESS, IncidentStatus.RESOLVED, IncidentStatus.CANCELLED},
    IncidentStatus.IN_PROGRESS: {IncidentStatus.RESOLVED, IncidentStatus.CANCELLED},
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED, IncidentStatus.IN_PROGRESS},
    IncidentStatus.CLOSED: set(),
    IncidentStatus.CANCELLED: set(),
}


class IncidentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = IncidentRepository(db)

    async def _global(self, user: User) -> bool:
        return await user_has_global_role(self.db, user.id, GLOBAL_ROLES)

    async def _can_manage(self, user: User, event_id: uuid.UUID) -> bool:
        return await self._global(user) or await user_has_scoped_role(
            self.db, user.id, MANAGE_ROLES, event_id, allow_global_roles=GLOBAL_ROLES
        )

    async def _can_report(self, user: User, event_id: uuid.UUID) -> bool:
        return await self._global(user) or await user_has_scoped_role(
            self.db, user.id, REPORT_ROLES, event_id, allow_global_roles=GLOBAL_ROLES
        )

    async def _event(self, event_id: uuid.UUID) -> None:
        if await self.db.get(Event, event_id) is None:
            raise NotFoundError("Event not found.")

    async def _ensure_assignment(self, user: User | None, event_id: uuid.UUID) -> None:
        if user is None:
            raise ValidationError("The assignee account was not found.")
        if not await self._can_report(user, event_id):
            raise PermissionDeniedError("The assignee is not authorized for this event.")

    async def _escalate(self, incident: Incident) -> None:
        recipients = await self.repo.operational_recipient_ids(incident.event_id)
        notifications = NotificationRepository(self.db)
        for recipient_id in recipients:
            await notifications.create(
                event_id=incident.event_id,
                recipient_user_id=recipient_id,
                channel=NotificationChannel.PUSH,
                title="Critical incident requires attention",
                body=incident.title,
                target_metadata={"incident_id": str(incident.id), "event_id": str(incident.event_id), "deep_link": "/ops/incidents"},
                delivery_status=NotificationDeliveryStatus.QUEUED,
                notification_type="incident_escalation",
                dedupe_key=f"incident:{incident.id}:critical:{recipient_id}",
            )
        incident.escalation_count += 1
        await write_audit_log(
            self.db, entity_type="incident", entity_id=incident.id,
            action="escalated", actor_user_id=None,
            after_value={"event_id": str(incident.event_id), "severity": incident.severity.value},
        )

    async def create(self, actor: User, payload: IncidentCreateIn) -> Incident:
        await self._event(payload.event_id)
        if not await self._can_report(actor, payload.event_id):
            raise PermissionDeniedError("You are not authorized to report incidents for this event.")
        if payload.assigned_user_id is not None:
            assigned = await self.db.get(User, payload.assigned_user_id)
            await self._ensure_assignment(assigned, payload.event_id)
        incident = await self.repo.create(
            event_id=payload.event_id, reporter_user_id=actor.id,
            assigned_user_id=payload.assigned_user_id, category=payload.category.strip(),
            title=payload.title.strip(), description=payload.description.strip(), severity=payload.severity,
        )
        await write_audit_log(self.db, entity_type="incident", entity_id=incident.id, action="created", actor_user_id=actor.id, after_value={"event_id": str(incident.event_id), "status": incident.status.value, "severity": incident.severity.value})
        if incident.severity == IncidentSeverity.CRITICAL:
            await self._escalate(incident)
        await self.db.commit()
        await self.db.refresh(incident)
        return incident

    async def get(self, actor: User, incident_id: uuid.UUID) -> Incident:
        incident = await self.repo.get(incident_id)
        if incident is None:
            raise NotFoundError("Incident not found.")
        if not await self._can_report(actor, incident.event_id):
            raise PermissionDeniedError("You are not authorized to view this incident.")
        return incident

    async def page(self, actor: User, **filters):
        global_access = await self._global(actor)
        event_id = filters.get("event_id")
        event_ids = None if global_access else await user_scoped_event_ids(self.db, actor.id, REPORT_ROLES)
        if not global_access and event_id is not None and event_id not in event_ids:
            raise PermissionDeniedError("You are not authorized to view this event.")
        return await self.repo.page(event_ids=event_ids, **filters)

    async def update(self, actor: User, incident_id: uuid.UUID, payload: IncidentUpdateIn) -> Incident:
        incident = await self.get(actor, incident_id)
        if not await self._can_manage(actor, incident.event_id):
            raise PermissionDeniedError("You are not authorized to manage this incident.")
        if incident.status in TERMINAL and payload.status not in {None, IncidentStatus.IN_PROGRESS}:
            raise ConflictError("A closed or cancelled incident cannot be changed.")
        before = {"status": incident.status.value, "severity": incident.severity.value, "assigned_user_id": str(incident.assigned_user_id) if incident.assigned_user_id else None}
        if payload.assigned_user_id is not None:
            assigned = await self.db.get(User, payload.assigned_user_id)
            await self._ensure_assignment(assigned, incident.event_id)
        if payload.status is not None and payload.status != incident.status:
            if payload.status not in TRANSITIONS[incident.status]:
                raise ValidationError(f"Invalid incident transition: {incident.status.value} to {payload.status.value}.")
            incident.status = payload.status
            now = datetime.now(timezone.utc)
            if payload.status == IncidentStatus.ACKNOWLEDGED: incident.acknowledged_at = now
            if payload.status == IncidentStatus.IN_PROGRESS: incident.in_progress_at = now
            if payload.status == IncidentStatus.RESOLVED: incident.resolved_at = now
            if payload.status == IncidentStatus.CLOSED: incident.closed_at = now
            if payload.status == IncidentStatus.CANCELLED: incident.cancelled_at = now
            await write_audit_log(self.db, entity_type="incident", entity_id=incident.id, action="status_changed", actor_user_id=actor.id, before_value={"status": before["status"]}, after_value={"status": incident.status.value})
        for field in ("category", "title", "description", "resolution_notes", "assigned_user_id"):
            if field in payload.model_fields_set:
                old = getattr(incident, field)
                new = getattr(payload, field)
                if field == "category" or field == "title" or field == "description": new = new.strip() if new else new
                setattr(incident, field, new)
                if old != new:
                    await write_audit_log(self.db, entity_type="incident", entity_id=incident.id, action="reassigned" if field == "assigned_user_id" else "updated", actor_user_id=actor.id, before_value={field: str(old) if old else None}, after_value={field: str(new) if new else None})
        if "severity" in payload.model_fields_set and payload.severity is not None and payload.severity != incident.severity:
            old = incident.severity
            incident.severity = payload.severity
            await write_audit_log(self.db, entity_type="incident", entity_id=incident.id, action="severity_changed", actor_user_id=actor.id, before_value={"severity": old.value}, after_value={"severity": incident.severity.value})
            if incident.severity == IncidentSeverity.CRITICAL and old != IncidentSeverity.CRITICAL:
                await self._escalate(incident)
        await self.db.commit()
        await self.db.refresh(incident)
        return incident
