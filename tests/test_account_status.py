from datetime import datetime, timedelta, timezone
import uuid
import pytest
from sqlalchemy import select
from httpx import ASGITransport, AsyncClient
from app.core.permissions import can_manage_account
from app.database import get_db
from app.redis_client import get_redis
from app.exceptions import PermissionDeniedError
from app.main import app
from app.config import get_settings
from app.modules.identity.models import User
from app.modules.identity.schemas import AccountStatusUpdateIn, UserOut
from app.modules.identity.service import IdentityService, _otp_redis_key
from app.modules.identity.exceptions import AccountDisabledError
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.events.models import Event
from app.modules.organizations.models import Organization
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationStatus
from app.modules.audit_log.models import AuditLog
from app.security import create_token, TokenType, hash_otp, hash_password

async def user(db, role=None, event=None):
    u = User(email=f'{uuid.uuid4()}@example.test', mobile_number='+91'+str(uuid.uuid4().int)[:10])
    db.add(u)
    await db.flush()
    if role:
        r = (await db.execute(select(Role).where(Role.name == role))).scalar_one()
        db.add(RoleAssignment(user_id=u.id, role_id=r.id, event_id=event))
        await db.flush()
    return u

@pytest.mark.asyncio
@pytest.mark.parametrize('actor_role,target_role,allowed', [
    (RoleName.SUPER_ADMIN, RoleName.SUPER_ADMIN, True),
    (RoleName.SUPER_ADMIN, None, True),
    (RoleName.OPERATIONS_ADMIN, RoleName.EVENT_MANAGER, True),
    (RoleName.OPERATIONS_ADMIN, RoleName.OPERATIONS_ADMIN, False),
    (RoleName.OPERATIONS_ADMIN, RoleName.STAFF_MEMBER, False),
    (RoleName.OPERATIONS_ADMIN, None, False),
    (RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, True),
    (RoleName.FINANCE_ADMIN, RoleName.FINANCE_AUDITOR, True),
    (RoleName.FINANCE_ADMIN, RoleName.FINANCE_ADMIN, False),
    (RoleName.FINANCE_ADMIN, RoleName.EVENT_MANAGER, False),
    (RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR, False),
])
async def test_hierarchy_and_reactivation(db_session, actor_role, target_role, allowed):
    db = db_session
    actor = await user(db, actor_role)
    target = await user(db, target_role)
    await db.commit()
    service = IdentityService(db, None)
    assert await can_manage_account(db, actor, target) == allowed
    if not allowed:
        with pytest.raises(PermissionDeniedError):
            await service.update_account_status(actor=actor, target_user_id=target.id, is_active=False)
        assert target.is_active
        return
    identity = target.id
    await service.update_account_status(actor=actor, target_user_id=identity, is_active=False)
    assert UserOut.model_validate(target).status == 'DISABLED'
    await service.update_account_status(actor=actor, target_user_id=identity, is_active=True)
    assert target.id == identity and target.is_active
    logs = (await db.execute(select(AuditLog).where(AuditLog.entity_id == identity))).scalars().all()
    assert {row.action for row in logs} == {'account_disabled', 'account_reactivated'}

@pytest.mark.asyncio
async def test_self_and_mixed_privilege_escalation_are_blocked(db_session):
    db = db_session
    actor = await user(db, RoleName.SUPER_ADMIN)
    service = IdentityService(db, None)
    with pytest.raises(PermissionDeniedError, match='own'):
        await service.update_account_status(actor=actor, target_user_id=actor.id, is_active=False)
    ops = await user(db, RoleName.OPERATIONS_ADMIN)
    finance = await user(db, RoleName.FINANCE_ADMIN)
    finance.is_event_manager = True
    await db.commit()
    assert not await can_manage_account(db, ops, finance)

async def event(db, organization):
    row = Event(name='Event', organization_id=organization.id, start_date=datetime.now(timezone.utc), end_date=datetime.now(timezone.utc)+timedelta(days=1))
    db.add(row)
    await db.flush()
    return row

@pytest.mark.asyncio
async def test_manager_volunteer_scope_and_organization_isolation(db_session):
    db = db_session
    a, b = Organization(name='Org A'), Organization(name='Org B')
    db.add_all([a,b]); await db.flush()
    first, other = await event(db,a), await event(db,b)
    manager = await user(db, RoleName.EVENT_MANAGER, first.id)
    volunteer = await user(db, RoleName.STAFF_MEMBER, first.id)
    application = VolunteerApplication(event_id=first.id, user_id=volunteer.id, full_name='Volunteer', phone=volunteer.mobile_number, status=VolunteerApplicationStatus.APPROVED)
    db.add(application); await db.commit()
    service = IdentityService(db, None)
    await service.update_account_status(actor=manager, target_user_id=volunteer.id, is_active=False)
    await service.update_account_status(actor=manager, target_user_id=volunteer.id, is_active=True)
    outside = VolunteerApplication(event_id=other.id, user_id=volunteer.id, full_name='Volunteer', phone=volunteer.mobile_number, status=VolunteerApplicationStatus.APPROVED)
    db.add(outside); await db.commit()
    assert not await can_manage_account(db, manager, volunteer)
    listed,_ = await service.manageable_accounts(manager)
    assert volunteer.id not in {item['id'] for item in listed}
    with pytest.raises(PermissionDeniedError):
        await service.update_account_status(actor=manager, target_user_id=volunteer.id, is_active=False)

@pytest.mark.asyncio
async def test_disabled_otp_login_old_tokens_and_reactivation(db_session, fake_redis):
    db = db_session
    actor = await user(db, RoleName.SUPER_ADMIN)
    target = await user(db, RoleName.FINANCE_OPERATOR)
    target.password_hash = hash_password('test-password')
    target.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    access = create_token(target.id, TokenType.ACCESS)
    refresh = create_token(target.id, TokenType.REFRESH)
    service = IdentityService(db, fake_redis)
    await fake_redis.set(_otp_redis_key(target.mobile_number), hash_otp('123456', target.mobile_number))
    await service.update_account_status(actor=actor, target_user_id=target.id, is_active=False)
    with pytest.raises(AccountDisabledError): await service.request_otp(target.mobile_number)
    with pytest.raises(AccountDisabledError): await service.verify_otp(target.mobile_number,'123456')
    with pytest.raises(AccountDisabledError): await service.login_with_email(target.email,'test-password')
    async def db_override(): yield db
    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_redis] = lambda: fake_redis
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
            prefix = get_settings().api_v1_prefix
            response = await client.get(prefix+'/users/me', headers={'Authorization':f'Bearer {access}'})
            assert response.status_code == 401 and response.json()['error_code'] == 'account_disabled'
            response = await client.post(prefix+'/auth/refresh', json={'refresh_token':refresh})
            assert response.status_code == 401
            await service.update_account_status(actor=actor, target_user_id=target.id, is_active=True)
            response = await client.get(prefix+'/users/me', headers={'Authorization':f'Bearer {access}'})
            assert response.status_code == 200 and response.json()['status'] == 'ACTIVE'
            assert (await service.verify_otp(target.mobile_number,'123456')).id == target.id
            assert (await service.login_with_email(target.email,'test-password')).id == target.id
    finally:
        app.dependency_overrides.clear()


def test_status_contract_rejects_conflicts():
    from pydantic import ValidationError
    assert AccountStatusUpdateIn(status='DISABLED').is_active is False
    with pytest.raises(ValidationError): AccountStatusUpdateIn(status='DISABLED', is_active=True)
    with pytest.raises(ValidationError): AccountStatusUpdateIn()
