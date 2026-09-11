from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError as SchemaValidationError
from sqlalchemy import func, select

from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.exceptions import PermissionDeniedError, ValidationError
from app.modules.events.models import Event
from app.modules.events.schemas import EventCreateIn
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.identity.service import IdentityService
from app.modules.rbac.models import AssignmentStatus, Role, RoleAssignment, RoleName


async def admin(db, name=RoleName.OPERATIONS_ADMIN):
    user = User(mobile_number="+919898989898")
    db.add(user)
    await db.flush()
    role = (await db.execute(select(Role).where(Role.name == name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id))
    await db.commit()
    return user


def event_fields(manager_id):
    return dict(name="Managed event", organizer_user_id=manager_id,
        start_date=datetime.now(timezone.utc), end_date=datetime.now(timezone.utc) + timedelta(days=1))


@pytest.mark.asyncio
async def test_designation_is_not_global_permission_and_creation_assigns_atomically(db_session):
    db = db_session
    actor = await admin(db)
    identity = IdentityService(db, None)
    manager, created = await identity.find_or_create_for_admin_provisioning(
        "+919898980001", "Manager", is_event_manager=True, actor_user_id=actor.id)
    assert created and manager.is_event_manager
    assert not await user_has_global_role(db, manager.id, {RoleName.EVENT_MANAGER})
    assert not await db.scalar(select(func.count(RoleAssignment.id)).where(RoleAssignment.user_id == manager.id))
    assert [user.id for user in await identity.list_event_managers()] == [manager.id]
    event = await EventService(db).create_event(created_by=actor.id, **event_fields(manager.id))
    assert event.organizer_user_id == manager.id
    assert await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, event.id)
    other = Event(**event_fields(None))
    db.add(other)
    await db.commit()
    assert not await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, other.id)


@pytest.mark.asyncio
async def test_reassignment_revokes_only_this_event_and_manager_cannot_reassign(db_session):
    db = db_session
    actor = await admin(db)
    first = User(mobile_number="+919898980002", is_event_manager=True)
    second = User(mobile_number="+919898980003", is_event_manager=True)
    db.add_all([first, second])
    await db.commit()
    service = EventService(db)
    event = await service.create_event(created_by=actor.id, **event_fields(first.id))
    other = await service.create_event(created_by=actor.id, **event_fields(first.id))
    with pytest.raises(PermissionDeniedError):
        await service.update_event(event.id, first.id, organizer_user_id=second.id)
    await service.update_event(event.id, actor.id, organizer_user_id=second.id)
    await service.update_event(event.id, actor.id, organizer_user_id=second.id)
    assert not await user_has_scoped_role(db, first.id, {RoleName.EVENT_MANAGER}, event.id)
    assert await user_has_scoped_role(db, first.id, {RoleName.EVENT_MANAGER}, other.id)
    assert await user_has_scoped_role(db, second.id, {RoleName.EVENT_MANAGER}, event.id)
    assert await db.scalar(select(func.count(RoleAssignment.id)).where(
        RoleAssignment.event_id == event.id, RoleAssignment.status == AssignmentStatus.ACTIVE)) == 1


@pytest.mark.asyncio
async def test_ineligible_and_inactive_accounts_cannot_be_selected(db_session):
    db = db_session
    actor = await admin(db)
    normal = User(mobile_number="+919898980004")
    inactive = User(mobile_number="+919898980005", is_event_manager=True, is_active=False)
    db.add_all([normal, inactive])
    await db.commit()
    for target in [normal, inactive]:
        with pytest.raises(ValidationError):
            await EventService(db).create_event(created_by=actor.id, **event_fields(target.id))
    assert await IdentityService(db, None).list_event_managers() == []
    assert await db.scalar(select(func.count(Event.id))) == 0


@pytest.mark.asyncio
async def test_assignment_failure_rolls_back_event_and_assignment(db_session, monkeypatch):
    db = db_session
    actor = await admin(db)
    manager = User(mobile_number="+919898980006", is_event_manager=True)
    db.add(manager)
    await db.commit()
    async def fail(*args, **kwargs):
        raise RuntimeError("simulated assignment audit failure")
    monkeypatch.setattr("app.modules.events.manager.write_audit_log", fail)
    with pytest.raises(RuntimeError):
        await EventService(db).create_event(created_by=actor.id, **event_fields(manager.id))
    await db.rollback()
    assert await db.scalar(select(func.count(Event.id))) == 0
    assert await db.scalar(select(func.count(RoleAssignment.id)).where(RoleAssignment.event_id.is_not(None))) == 0


@pytest.mark.asyncio
async def test_finance_cannot_designate_manager(db_session):
    actor = await admin(db_session, RoleName.FINANCE_ADMIN)
    with pytest.raises(PermissionDeniedError):
        await IdentityService(db_session, None).find_or_create_for_admin_provisioning(
            "+919898980007", is_event_manager=True, actor_user_id=actor.id)


def test_event_create_api_requires_existing_manager_id():
    fields = event_fields(None)
    with pytest.raises(SchemaValidationError):
        EventCreateIn(**fields)


@pytest.mark.asyncio
async def test_deactivation_removes_picker_option_but_lists_events_for_reassignment(db_session):
    db = db_session
    actor = await admin(db)
    manager = User(mobile_number="+919898980010", is_event_manager=True)
    db.add(manager)
    await db.commit()
    event = await EventService(db).create_event(created_by=actor.id, **event_fields(manager.id))
    identity = IdentityService(db, None)
    await identity.update_account_status(actor=actor, target_user_id=manager.id, is_active=False)
    assert await identity.list_event_managers() == []
    accounts, _ = await identity.page_accounts()
    target = next(item for item in accounts if item["id"] == manager.id)
    assert not target["is_active"]
    assert target["managed_events"] == [{"id": str(event.id), "name": event.name}]


@pytest.mark.asyncio
async def test_admin_duplicate_and_template_creation_also_assign_selected_manager(db_session):
    db = db_session
    actor = await admin(db)
    manager = User(mobile_number="+919898980011", is_event_manager=True)
    db.add(manager)
    await db.commit()
    service = EventService(db)
    source = await service.create_event(created_by=actor.id, **event_fields(manager.id))
    fields = dict(name="Copy", organizer_user_id=manager.id,
        start_date=source.start_date + timedelta(days=10), end_date=source.end_date + timedelta(days=10))
    duplicate = await service.duplicate_event(actor, source.id, **fields)
    assert await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, duplicate.id)
    template = await service.create_template(actor, name="Template", description=None, source_event_id=source.id)
    copied = await service.create_event_from_template(actor, template.id, **fields)
    assert await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, copied.id)
    fields.pop("organizer_user_id")
    with pytest.raises(ValidationError):
        await service.duplicate_event(actor, source.id, **fields)


@pytest.mark.asyncio
async def test_category_deletion_revokes_event_assignment_without_deleting_manager(db_session):
    from app.modules.event_categories.models import MainCategory, SubCategory
    from app.modules.event_categories.service import EventCategoryService
    db = db_session
    actor = await admin(db)
    manager = User(mobile_number="+919898980012", is_event_manager=True)
    main = MainCategory(name="Parent")
    db.add_all([manager, main])
    await db.flush()
    sub = SubCategory(name="Child", main_category_id=main.id)
    db.add(sub)
    await db.commit()
    event = await EventService(db).create_event(created_by=actor.id, main_category_id=main.id,
        sub_category_id=sub.id, **event_fields(manager.id))
    await EventCategoryService(db).delete_main_category(main.id, actor.id)
    assert not await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, event.id)
    assert (await db.get(User, manager.id)).is_event_manager


@pytest.mark.asyncio
async def test_existing_email_account_designation_preserves_identity_and_permissions(db_session):
    db = db_session
    actor = await admin(db)
    user = User(email="existing@example.com", mobile_number=None)
    db.add(user)
    await db.commit()
    identity = IdentityService(db, None)
    with pytest.raises(PermissionDeniedError):
        await identity.designate_event_manager(user.id, user.id)
    designated = await identity.designate_event_manager(user.id, actor.id)
    assert designated.id == user.id and designated.is_event_manager
    assert not await db.scalar(select(func.count(RoleAssignment.id)).where(RoleAssignment.user_id == user.id))
    assert user.id in [item.id for item in await identity.list_event_managers()]


@pytest.mark.asyncio
async def test_direct_event_deletion_revokes_only_deleted_event_and_preserves_account(db_session):
    db = db_session
    actor = await admin(db)
    manager = User(email="manager@example.com", is_event_manager=True)
    db.add(manager)
    await db.commit()
    service = EventService(db)
    event = await service.create_event(created_by=actor.id, **event_fields(manager.id))
    other = await service.create_event(created_by=actor.id, **event_fields(manager.id))
    with pytest.raises(PermissionDeniedError):
        await service.delete_event(event.id, manager.id)
    await service.delete_event(event.id, actor.id)
    assert await service.events.get_by_id(event.id) is None
    assert not await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, event.id)
    assert await user_has_scoped_role(db, manager.id, {RoleName.EVENT_MANAGER}, other.id)
    assert (await db.get(User, manager.id)).is_active
    assert (await db.get(Event, event.id)).deleted_at is not None


@pytest.mark.asyncio
async def test_staff_invites_cannot_bypass_primary_manager_workflow(db_session):
    from app.modules.staff.service import StaffService
    from app.modules.staff.exceptions import InvalidStaffRoleNameError
    from app.modules.staff.models import StaffAssignment, StaffAssignmentStatus
    db = db_session
    actor = await admin(db)
    manager = User(mobile_number="+919898981001", is_event_manager=True)
    db.add(manager)
    await db.commit()
    event = await EventService(db).create_event(created_by=actor.id, **event_fields(manager.id))
    staff = StaffService(db)
    with pytest.raises(InvalidStaffRoleNameError):
        await staff.create_assignment(event_id=event.id, actor=actor,
            invitee_mobile=manager.mobile_number, role_name=RoleName.EVENT_MANAGER, role_label="Manager")
    legacy = StaffAssignment(event_id=event.id, invitee_mobile=manager.mobile_number,
        role_name=RoleName.EVENT_MANAGER, role_label="Manager", invited_by=actor.id,
        status=StaffAssignmentStatus.INVITED)
    db.add(legacy)
    await db.commit()
    with pytest.raises(InvalidStaffRoleNameError):
        await staff.accept_assignment(legacy.id, manager)
    assert await db.scalar(select(func.count(RoleAssignment.id)).where(
        RoleAssignment.event_id == event.id, RoleAssignment.status == AssignmentStatus.ACTIVE)) == 1
    with pytest.raises(InvalidStaffRoleNameError):
        await staff.revoke_assignment(legacy.id, actor)
    with pytest.raises(InvalidStaffRoleNameError):
        await staff.reassign_assignment(legacy.id, actor, role_name=RoleName.STAFF_MEMBER)
