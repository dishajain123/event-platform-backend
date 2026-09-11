"""Verify screenshot hierarchy, owned counts, FK integrity and operational links."""
import asyncio
import hashlib
import hmac
import json
import uuid
from sqlalchemy import select, func
from app.core import model_registry  # noqa: F401
from app.core.base_model import Base
from app.database import AsyncSessionLocal, engine
from app.config import get_settings
from app.modules.events.models import Event
from app.modules.event_categories.models import MainCategory, SubCategory
from app.modules.registrations.models import Registration, RegistrationParticipant
from app.modules.payments.models import Payment
from app.modules.tickets.models import Ticket, CheckIn, AccessPolicy, AccessZone
from app.modules.teams.models import Team, TeamMember
from app.modules.rbac.models import RoleAssignment, Role, RoleName, AssignmentStatus
from app.modules.identity.models import User
from scripts.seed.go360_data import CATEGORIES, EVENTS
from scripts.seed.ownership import load_manifest, seed_id


async def validate_db(db):
    checks = []
    for name, topics in CATEGORIES.items():
        roots = list((await db.execute(select(MainCategory).where(MainCategory.name == name, MainCategory.deleted_at.is_(None)))).scalars())
        checks.append((f'{name}: unique active category', len(roots) == 1 and roots[0].is_active))
        if len(roots) == 1:
            children = list((await db.execute(select(SubCategory).where(SubCategory.main_category_id == roots[0].id, SubCategory.deleted_at.is_(None)))).scalars())
            checks.append((f'{name}: exact topics', {c.name for c in children if c.is_active} == set(topics)))
    _, records = await load_manifest(db)
    counts = {}
    for name, raw_ids in records.items():
        table = Base.metadata.tables[name]
        ids = [uuid.UUID(x) for x in raw_ids]
        counts[name] = await db.scalar(select(func.count()).select_from(table).where(table.c.id.in_(ids)))
        checks.append((f'{name}: owned records exist', counts[name] == len(set(ids))))
    for key, main, topic, title, first, last, detail in EVENTS:
        e = await db.get(Event, seed_id('events', key))
        root = await db.get(MainCategory, e.main_category_id) if e else None
        sub = await db.get(SubCategory, e.sub_category_id) if e else None
        from zoneinfo import ZoneInfo
        dates = bool(e and e.start_date.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat() == f'2027-12-{first}'
            and e.end_date.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat() == f'2027-12-{last}')
        checks.append((f'{main} → {topic} → {title}', bool(e and root and sub and
            root.name == main and sub.name == topic and sub.main_category_id == root.id and
            e.name == title and e.description == detail and e.deleted_at is None and dates)))
        if e:
            assignments = list((await db.execute(select(RoleAssignment).join(Role).where(
                RoleAssignment.event_id == e.id, Role.name == RoleName.EVENT_MANAGER,
                RoleAssignment.status == AssignmentStatus.ACTIVE))).scalars())
            manager = await db.get(User, e.organizer_user_id)
            checks.append((f'{key}: primary manager', len(assignments) == 1 and
                assignments[0].user_id == e.organizer_user_id and bool(manager and manager.is_event_manager and manager.is_active)))
    # Check ALL actual FK constraints, not just event_id columns. NULL means optional.
    for table in Base.metadata.tables.values():
        for constraint in table.foreign_key_constraints:
            elements = list(constraint.elements)
            remote = elements[0].column.table.alias()
            match = [remote.c[e.column.name] == e.parent for e in elements]
            query = select(func.count()).select_from(table).where(
                *(e.parent.is_not(None) for e in elements),
                ~select(1).select_from(remote).where(*match).exists())
            checks.append((f'FK {table.name}/{constraint.name or elements[0].parent.name}', (await db.scalar(query)) == 0))
    for row in (await db.execute(select(Ticket).where(Ticket.id.in_([uuid.UUID(x) for x in records.get('tickets', [])])))).scalars():
        reg = await db.get(Registration, row.registration_id)
        participant = await db.get(RegistrationParticipant, row.participant_id)
        policy = await db.get(AccessPolicy, row.access_policy_id)
        payment = await db.get(Payment, row.payment_id) if row.payment_id else None
        valid = reg.event_id == row.event_id and participant.registration_id == reg.id and participant.user_id == row.user_id
        valid = valid and policy.event_id == row.event_id and (payment is None or payment.registration_id == reg.id)
        valid = valid and hmac.compare_digest(hmac.new(get_settings().ticket_barcode_secret.encode(), row.barcode_payload.encode(), hashlib.sha256).hexdigest(), row.barcode_signature)
        for zone_id in policy.allowed_zone_ids:
            zone = await db.get(AccessZone, uuid.UUID(zone_id))
            valid = valid and bool(zone and zone.event_id == row.event_id)
        entries = await db.scalar(select(func.count()).select_from(CheckIn).where(CheckIn.ticket_id == row.id))
        checks.append((f'ticket {row.ticket_code}: owner/payment/access/signature/attendance', bool(valid and entries == row.entry_count)))
    for row in (await db.execute(select(Team).where(Team.id.in_([uuid.UUID(x) for x in records.get('teams', [])])))).scalars():
        reg = await db.get(Registration, row.registration_id)
        checks.append((f'team {row.name}: registration', bool(reg and reg.team_id == row.id and reg.event_id == row.event_id and reg.participation_type == 'team')))
    return counts, checks


async def validate():
    engine.echo = False
    async with AsyncSessionLocal() as db:
        counts, checks = await validate_db(db)
    print(json.dumps({'screenshot_counts': {'main_categories': len(CATEGORIES), 'sub_categories': sum(map(len, CATEGORIES.values())), 'events': len(EVENTS)}, 'owned_record_counts': counts, 'checks': len(checks),
        'failed': [name for name, passed in checks if not passed]}, indent=2))
    return int(not counts or any(not passed for _, passed in checks))


if __name__ == '__main__':
    raise SystemExit(asyncio.run(validate()))
