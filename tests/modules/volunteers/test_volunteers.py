from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.staff.models import StaffAssignment
from app.modules.volunteers.models import VolunteerApplicationStatus, VolunteerApplicationType
from app.modules.volunteers.service import VolunteerService


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _event(db, creator):
    events = EventService(db)
    event = await events.create_event(
        created_by=creator.id,
        name="Volunteer Event",
        description=None,
        category="community",
        start_date=datetime.now(timezone.utc) + timedelta(days=5),
        end_date=datetime.now(timezone.utc) + timedelta(days=6),
        organization_id=None,
    )
    await ConfigEngineService(db).upsert_configuration(
        event.id, participation_types=["viewer"], fee_amount=None, currency="INR", capacity=10,
        approval_required=False, rules={}, discount_rules=None,
    )
    event = await events.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    return await events.publish(event.id, creator.id)


@pytest.mark.asyncio
async def test_volunteer_application_scope_duplicate_lifecycle_and_activation(db_session):
    creator = User(mobile_number="+919800000001")
    applicant = User(mobile_number="+919800000002")
    operations = User(mobile_number="+919800000003")
    manager = User(mobile_number="+919800000004")
    outsider = User(mobile_number="+919800000005")
    db_session.add_all([creator, applicant, operations, manager, outsider])
    await db_session.flush()
    event = await _event(db_session, creator)
    await _role(db_session, operations, RoleName.OPERATIONS_ADMIN)
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    service = VolunteerService(db_session)

    application = await service.create_application(applicant, {
        "event_id": event.id,
        "full_name": "Volunteer Applicant",
        "phone": "+919000000000",
        "email": "volunteer@example.com",
        "skills_experience": "First aid",
        "availability": "All event days",
        "preferred_responsibility": "Registration desk",
        "message": "Happy to help",
    })
    assert application.user_id == applicant.id
    assert application.phone == applicant.mobile_number
    with pytest.raises(ConflictError):
        await service.create_application(applicant, {
            "event_id": event.id, "full_name": "Duplicate", "phone": applicant.mobile_number,
        })
    with pytest.raises(PermissionDeniedError):
        await service.get_visible(outsider, application.id)
    with pytest.raises(PermissionDeniedError):
        await service.list_manageable(outsider, event.id)

    await service.update_status(manager, application.id, VolunteerApplicationStatus.UNDER_REVIEW)
    await service.update_status(operations, application.id, VolunteerApplicationStatus.APPROVED)
    activated = await service.activate(manager, application.id)
    assert activated.activated_staff_assignment_id is not None
    with pytest.raises(ConflictError):
        await service.activate(manager, application.id)
    with pytest.raises(ValidationError):
        await service.update_status(manager, application.id, VolunteerApplicationStatus.REJECTED)

    manager_application = await service.create_application(applicant, {
        "event_id": event.id,
        "application_type": VolunteerApplicationType.EVENT_MANAGER,
        "full_name": "Volunteer Applicant",
        "phone": applicant.mobile_number,
    })
    await service.update_status(operations, manager_application.id, VolunteerApplicationStatus.APPROVED)
    with pytest.raises(ValidationError, match="Admin Accounts"):
        await service.activate(operations, manager_application.id)
    assert manager_application.activated_staff_assignment_id is None
