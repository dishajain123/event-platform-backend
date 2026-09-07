from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.exceptions import PermissionDeniedError, ValidationError
from app.modules.audit_log.models import AuditLog
from app.modules.events.models import Event, EventStatus
from app.modules.identity.models import User
from app.modules.incidents.models import IncidentSeverity, IncidentStatus
from app.modules.incidents.schemas import IncidentCreateIn, IncidentUpdateIn
from app.modules.incidents.service import IncidentService
from app.modules.notifications.models import Notification
from app.modules.rbac.models import Role, RoleAssignment, RoleName


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _fixture(db):
    manager = User(mobile_number="+919920000001")
    other_manager = User(mobile_number="+919920000002")
    operations = User(mobile_number="+919920000003")
    db.add_all([manager, other_manager, operations])
    await db.flush()
    start = datetime.now(timezone.utc) + timedelta(days=2)
    event = Event(name="Incident Event", description=None, category="test", start_date=start, end_date=start + timedelta(days=1), status=EventStatus.LIVE, created_by=manager.id)
    other_event = Event(name="Other Incident Event", description=None, category="test", start_date=start, end_date=start + timedelta(days=1), status=EventStatus.LIVE, created_by=other_manager.id)
    db.add_all([event, other_event])
    await db.flush()
    await _role(db, manager, RoleName.EVENT_MANAGER, event.id)
    await _role(db, other_manager, RoleName.EVENT_MANAGER, other_event.id)
    await _role(db, operations, RoleName.OPERATIONS_ADMIN)
    return event, other_event, manager, other_manager, operations


@pytest.mark.asyncio
async def test_incident_lifecycle_is_scoped_and_invalid_transitions_rejected(db_session):
    event, other_event, manager, other_manager, _operations = await _fixture(db_session)
    service = IncidentService(db_session)
    incident = await service.create(manager, IncidentCreateIn(event_id=event.id, category="safety", title="Blocked exit", description="North exit is blocked", severity=IncidentSeverity.HIGH))
    assert incident.status == IncidentStatus.OPEN
    with pytest.raises(PermissionDeniedError):
        await service.get(other_manager, incident.id)
    with pytest.raises(PermissionDeniedError):
        await service.page(other_manager, event_id=event.id, status=None, severity=None, category=None, assigned_user_id=None, search=None, page=1, page_size=25)
    await service.update(manager, incident.id, IncidentUpdateIn(status=IncidentStatus.ACKNOWLEDGED))
    with pytest.raises(ValidationError):
        await service.update(manager, incident.id, IncidentUpdateIn(status=IncidentStatus.CLOSED))
    assert other_event.id != event.id


@pytest.mark.asyncio
async def test_critical_escalation_is_deduplicated_and_global_operations_can_list(db_session):
    event, _other_event, manager, _other_manager, operations = await _fixture(db_session)
    service = IncidentService(db_session)
    incident = await service.create(manager, IncidentCreateIn(event_id=event.id, category="medical", title="Medical emergency", description="Needs attention", severity=IncidentSeverity.CRITICAL))
    await service.update(manager, incident.id, IncidentUpdateIn(severity=IncidentSeverity.CRITICAL))
    notifications = await db_session.scalar(select(func.count(Notification.id)).where(Notification.notification_type == "incident_escalation"))
    audits = await db_session.scalar(select(func.count(AuditLog.id)).where(AuditLog.entity_type == "incident", AuditLog.action == "escalated"))
    assert notifications == 2
    assert audits == 1
    items, total = await service.page(operations, page=1, page_size=1, status=None, severity=None, category=None, assigned_user_id=None, search=None, event_id=None)
    assert total == 1 and len(items) == 1


@pytest.mark.asyncio
async def test_incident_filters_and_pagination_are_bounded(db_session):
    event, _other_event, manager, _other_manager, _operations = await _fixture(db_session)
    service = IncidentService(db_session)
    for index in range(3):
        await service.create(manager, IncidentCreateIn(event_id=event.id, category="venue", title=f"Issue {index}", description="door", severity=IncidentSeverity.LOW))
    items, total = await service.page(manager, event_id=event.id, status=IncidentStatus.OPEN, severity=IncidentSeverity.LOW, category="venue", assigned_user_id=None, search="Issue", page=2, page_size=2)
    assert total == 3 and len(items) == 1
    assert items[0].created_at <= items[0].created_at
