"""Deterministic, cross-platform demo data for local development.

This is deliberately backend-owned. Mobile and Console receive these rows
through the same APIs used in production; they do not maintain mock copies.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text

from app.core import model_registry  # noqa: F401
from app.database import AsyncSessionLocal
from app.modules.config_engine.models import EventConfiguration, EventFieldSchema
from app.modules.event_categories.models import MainCategory, SubCategory
from app.modules.events.models import Event, EventStatus, ScheduleItem, ScheduleStatus, Venue
from app.modules.identity.models import User
from app.modules.notifications.models import Notification, NotificationChannel, NotificationDeliveryStatus
from app.modules.organizations.models import Organization
from app.modules.payments.models import Payment, PaymentStatus, Refund, RefundStatus
from app.modules.rbac.models import SCOPED_ROLES, Role, RoleAssignment, RoleName
from app.modules.registrations.models import Registration, RegistrationParticipant, RegistrationStatus
from app.modules.staff.models import StaffAssignment, StaffAssignmentStatus, StaffAssignmentHistory
from app.modules.teams.models import Team, TeamMember, TeamMemberRole, TeamStatus
from app.modules.tickets.models import AccessPolicy, AccessZone, CheckIn, CheckInSource, Ticket, TicketStatus
from app.modules.volunteer_shifts.models import VolunteerShift, VolunteerShiftStatus
from app.modules.volunteers.models import VolunteerApplication, VolunteerApplicationStatus


from zoneinfo import ZoneInfo
from scripts.seed.go360_data import CATEGORIES, EVENTS, LIVE_DETAILS
from scripts.seed.engagement import seed_engagement, seed_marketplace
from scripts.seed.ownership import SeedWriter, reset_owned, seed_id, snapshot_unowned, assert_preserved

SIZES = {'small': 8, 'medium': 24, 'large': 72}
IST = ZoneInfo('Asia/Kolkata')


def festival_time(day, hour=9):
    return datetime(2027, 12, day, hour, tzinfo=IST)


async def taxonomy(writer, refresh):
    db = writer.db
    mains, subs = {}, {}
    # Existing console-created taxonomy is borrowed, never registered for deletion.
    for name, topics in CATEGORIES.items():
        aliases = {name.casefold(), 'g360° live'} if name == 'GO-360° LIVE' else {name.casefold()}
        matches = [r for r in (await db.execute(select(MainCategory).where(MainCategory.deleted_at.is_(None)))).scalars()
                   if r.name.strip().casefold() in aliases]
        if len(matches) > 1:
            raise RuntimeError(f'Ambiguous existing category: {name}; no changes committed.')
        root = matches[0] if matches else await writer.add(MainCategory, name, name=name, is_active=True)
        if root.id != seed_id(MainCategory.__tablename__, name):
            writer.borrowed[str(root.id)] = name
            if refresh:
                root.name = name
        else:
            writer.records.setdefault(MainCategory.__tablename__, []).append(str(root.id))
        mains[name] = root
        for topic in topics:
            matches = [r for r in (await db.execute(select(SubCategory).where(SubCategory.main_category_id == root.id, SubCategory.deleted_at.is_(None)))).scalars()
                       if r.name.strip().casefold() == topic.casefold()]
            if len(matches) > 1:
                raise RuntimeError(f'Ambiguous existing sub-category: {name}/{topic}')
            key = f'{name}/{topic}'
            sub = matches[0] if matches else await writer.add(SubCategory, key, name=topic, main_category_id=root.id, is_active=True)
            if sub.id != seed_id(SubCategory.__tablename__, key):
                writer.borrowed[str(sub.id)] = key
                if refresh:
                    sub.name = topic
            else:
                writer.records.setdefault(SubCategory.__tablename__, []).append(str(sub.id))
            subs[key] = sub
    await db.flush()
    return mains, subs


async def build_dataset(db, size='medium', refresh=False):
    w = SeedWriter(db)
    roles = {}
    for name in RoleName:
        row = (await db.execute(select(Role).where(Role.name == name))).scalar_one_or_none()
        if row is None:
            row = Role(name=name, is_scoped=name in SCOPED_ROLES)
            db.add(row)
            await db.flush()
        roles[name] = row
    names = ['Mira Kapoor', 'Kabir Shah', 'Ishita Rao', 'Neel Verma', 'Tara Iyer', 'Rohan Desai']
    people = ['Aarav Mehta', 'Ananya Shah', 'Vivaan Joshi', 'Diya Patel', 'Arjun Nair', 'Saanvi Rao', 'Aditya Kulkarni', 'Meera Iyer']
    names += [f'{people[i % len(people)]} {i // len(people) + 1}' for i in range(SIZES[size])]
    users = []
    for i, name in enumerate(names):
        users.append(await w.add(User, str(i), name=name, email=f'go360-{i:03d}@example.test',
            mobile_number=f'+919700{i:06d}', is_active=i != len(names)-1,
            is_event_manager=i in (2, 5)))
    ops, finance, manager, staff, volunteer, spare_manager = users[:6]
    for user, role in [(ops, RoleName.OPERATIONS_ADMIN), (finance, RoleName.FINANCE_ADMIN)]:
        await w.add(RoleAssignment, str(user.id), user_id=user.id, role_id=roles[role].id, assigned_by=ops.id)
    org = await w.add(Organization, 'go360', name='GO-360° Goregaon', contact_email='go360-operations@example.test')
    mains, subs = await taxonomy(w, refresh)
    events = {}
    # Dates/names mirror the artwork. Operational states below simulate festival-day use.
    for index, (key, main, topic, name, first, last, detail) in enumerate(EVENTS):
        start, end = festival_time(first), festival_time(last, 21)
        event = await w.add(Event, key, name=name, description=detail, organization_id=org.id,
            organizer_user_id=manager.id, created_by=ops.id, main_category_id=mains[main].id,
            sub_category_id=subs[f'{main}/{topic}'].id, category=main, start_date=start, end_date=end,
            status=EventStatus.REGISTRATION_OPEN)
        events[key] = event
        await w.add(RoleAssignment, f'manager/{key}', user_id=manager.id, event_id=event.id,
            role_id=roles[RoleName.EVENT_MANAGER].id, assigned_by=ops.id)
        staff_role = await w.add(RoleAssignment, f'staff/{key}', user_id=staff.id, event_id=event.id,
            role_id=roles[RoleName.STAFF_MEMBER].id, assigned_by=ops.id)
        assignment = await w.add(StaffAssignment, key, event_id=event.id, user_id=staff.id,
            invitee_mobile=staff.mobile_number, full_name=staff.name, role_name=RoleName.STAFF_MEMBER,
            role_label='Guest Services', status=StaffAssignmentStatus.ACTIVE, invited_by=ops.id,
            accepted_by=staff.id, accepted_at=start-timedelta(days=30), linked_role_assignment_id=staff_role.id)
        await w.add(StaffAssignmentHistory, key, assignment_id=assignment.id, action='accepted',
            actor_user_id=staff.id, after_value={'status': 'active'}, notes='Synthetic festival scenario')
        fee = Decimal('0') if main == 'Contribute 360°' else Decimal('499')
        await w.add(EventConfiguration, key, event_id=event.id, participation_types=['individual', 'team', 'viewer'],
            fee_amount=fee, currency='INR', capacity=200, volunteer_open=True, approval_required=False,
            details={'registration_end_at': end.isoformat(), 'seed_simulation': True,
                     **({'programme': LIVE_DETAILS} if key == 'live' else {})},
            rules={'min_age': 18, 'max_age': 90, 'team_size': {'min': 2, 'max': 8}})
        for mode in ('individual', 'team', 'viewer'):
            await w.add(EventFieldSchema, f'{key}/{mode}', event_id=event.id, participation_type=mode,
                fields=[{'key': 'emergency_contact', 'label': 'Emergency contact', 'type': 'text', 'required': False}])
        venue = await w.add(Venue, key, event_id=event.id, name=detail, address=detail, capacity=200, is_shared=False)
        await w.add(ScheduleItem, key, event_id=event.id, venue_id=venue.id, title=name, start_time=start,
            end_time=end, status=ScheduleStatus.SCHEDULED)
        zone = await w.add(AccessZone, key, event_id=event.id, code='MAIN', name='Main entrance')
        policy = await w.add(AccessPolicy, key, event_id=event.id, access_type='general',
            allowed_zone_ids=[str(zone.id)], allows_reentry=True, max_entries=2, valid_from=start, valid_until=end)
        states = [RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.SUBMITTED,
                  RegistrationStatus.PENDING_PAYMENT if fee else RegistrationStatus.APPROVED,
                  RegistrationStatus.CANCELLED, RegistrationStatus.REJECTED]
        event_regs = []
        for scenario, state in enumerate(states):
            user = users[6 + (index + scenario) % (len(users)-7)]
            ref = f'{key}/{scenario}'
            reg = await w.add(Registration, ref, event_id=event.id, user_id=user.id, participation_type='individual',
                status=state, submitted_at=start-timedelta(days=14),
                checked_in_at=start+timedelta(hours=1) if state == RegistrationStatus.CHECKED_IN else None,
                cancellation_reason='Plans changed' if state == RegistrationStatus.CANCELLED else None,
                cancelled_at=start-timedelta(days=3) if state == RegistrationStatus.CANCELLED else None,
                rejected_by=ops.id if state == RegistrationStatus.REJECTED else None,
                rejection_reason='Eligibility not met' if state == RegistrationStatus.REJECTED else None)
            participant = await w.add(RegistrationParticipant, ref, registration_id=reg.id,
                user_id=user.id, full_name=user.name, date_of_birth=date(1994, 6, 15), is_captain=False)
            event_regs.append((state, reg, participant, user))
            payment = None
            if fee and state not in {RegistrationStatus.SUBMITTED, RegistrationStatus.REJECTED}:
                payment_status = PaymentStatus.REFUNDED if state == RegistrationStatus.CANCELLED else PaymentStatus.INITIATED if state == RegistrationStatus.PENDING_PAYMENT else PaymentStatus.VERIFIED
                payment = await w.add(Payment, ref, event_id=event.id, registration_id=reg.id, user_id=user.id,
                    amount=fee, currency='INR', status=payment_status, gateway_provider='seed',
                    gateway_order_id=f'go360-order-{ref}', gateway_payment_id=None if payment_status == PaymentStatus.INITIATED else f'go360-payment-{ref}',
                    verified_at=None if payment_status == PaymentStatus.INITIATED else start-timedelta(days=10))
                if payment_status == PaymentStatus.REFUNDED:
                    await w.add(Refund, ref, payment_id=payment.id, requested_by=user.id, approved_by=finance.id,
                        amount=fee, reason='Plans changed', status=RefundStatus.PROCESSED,
                        processed_at=start-timedelta(days=2), gateway_refund_id=f'go360-refund-{ref}')
            if state in {RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN}:
                from app.modules.tickets.service import TicketService
                payload = f'ticket:{reg.id}:{participant.id}'
                ticket = await w.add(Ticket, ref, event_id=event.id, registration_id=reg.id, participant_id=participant.id,
                    user_id=user.id, payment_id=payment.id if payment else None, ticket_code=f'GO360-{key}-{scenario}',
                    barcode_payload=payload, barcode_signature=TicketService(db)._sign_payload(payload),
                    access_policy_id=policy.id, access_type='general', entry_count=int(scenario == 1),
                    status=TicketStatus.CHECKED_IN if scenario == 1 else TicketStatus.ISSUED,
                    checked_in_at=start+timedelta(hours=1) if scenario == 1 else None,
                    checked_in_by=staff.id if scenario == 1 else None)
                if scenario == 1:
                    await w.add(CheckIn, ref, ticket_id=ticket.id, event_id=event.id, venue_id=venue.id,
                        scanned_by=staff.id, source=CheckInSource.ONLINE, scan_payload=payload, entry_number=1,
                        created_at=start+timedelta(hours=1))
            await w.add(Notification, ref, event_id=event.id, recipient_user_id=user.id, channel=NotificationChannel.PUSH,
                title=f'{name}: registration update', body=f'Synthetic scenario: {state.value.replace("_", " ")}.',
                delivery_status=NotificationDeliveryStatus.SENT if scenario % 2 == 0 else NotificationDeliveryStatus.FAILED,
                dedupe_key=f'go360/{ref}', sent_at=start-timedelta(days=10) if scenario % 2 == 0 else None,
                last_error='Simulated delivery failure' if scenario % 2 else None)
        shift = await w.add(VolunteerShift, key, event_id=event.id, title='Welcome desk', location=detail,
            starts_at=start, ends_at=start+timedelta(hours=3), required_count=4, status=VolunteerShiftStatus.OPEN)
        await w.add(VolunteerApplication, key, event_id=event.id, user_id=volunteer.id, full_name=volunteer.name,
            phone=volunteer.mobile_number, email=volunteer.email, status=VolunteerApplicationStatus.APPROVED,
            reviewed_by=ops.id, reviewed_at=start-timedelta(days=7))
        await seed_engagement(w, event=event, key=key, index=index, regs=event_regs,
            users=users, manager=manager, staff=staff, volunteer=volunteer, ops=ops,
            finance=finance, start=start, end=end)
    await seed_marketplace(w, events, users, ops, finance)
    for i, key in enumerate(('cricket', 'football', 'open-sports')):
        event = events[key]
        team = await w.add(Team, key, event_id=event.id, captain_user_id=users[6].id,
            name=['Goregaon Strikers', 'Aarey United', 'Westside Warriors'][i], team_code=f'GO360-TEAM-{i}', status=TeamStatus.SUBMITTED,
            submitted_at=festival_time(20))
        reg = await w.add(Registration, f'team/{key}', event_id=event.id, user_id=users[6].id, team_id=team.id,
            participation_type='team', status=RegistrationStatus.SUBMITTED, submitted_at=festival_time(20))
        # Complete the cycle only on creation; additive seeding never edits existing rows.
        if team.id in w.created:
            team.registration_id = reg.id
        for j in range(3):
            user = users[6+j]
            await w.add(TeamMember, f'{key}/{j}', team_id=team.id, user_id=user.id, full_name=user.name,
                is_captain=j == 0, role=TeamMemberRole.CAPTAIN if j == 0 else TeamMemberRole.MEMBER)
            await w.add(RegistrationParticipant, f'team/{key}/{j}', registration_id=reg.id, user_id=user.id,
                full_name=user.name, date_of_birth=date(1994, 6, 15), is_captain=j == 0)
    return await w.save()


async def seed_platform(size='medium', command='add'):
    from app.config import get_settings
    from app.database import engine
    engine.echo = False
    if get_settings().environment.lower() not in {'development', 'test', 'local'}:
        raise RuntimeError('Dummy seeding is restricted to development/test/local databases.')
    async with AsyncSessionLocal() as db:
        async with db.begin():
            if db.bind.dialect.name == 'postgresql':
                await db.execute(text('SELECT pg_advisory_xact_lock(3602027)'))
            baseline = await snapshot_unowned(db)
            protected = await reset_owned(db) if command in {'reset', 'refresh'} else {}
            counts = await build_dataset(db, size, refresh=command in {'reset', 'refresh'})
            await assert_preserved(db, baseline, allow_taxonomy_labels=command in {'reset', 'refresh'})
        if protected:
            print('Preserved legacy/seed rows referenced by non-seed data:', protected)
    from app.core.discovery_updates import notify_discovery_change
    from app.config import get_settings
    await notify_discovery_change('POST', get_settings().api_v1_prefix + '/events', 200)
    from app.redis_client import _pool
    await _pool.disconnect()
    return counts


async def main():
    parser = argparse.ArgumentParser(description='Screenshot-based GO-360° dummy dataset; never truncates tables')
    parser.add_argument('command', choices=('seed', 'add', 'reset', 'refresh'))
    parser.add_argument('--size', choices=tuple(SIZES), default='medium')
    args = parser.parse_args()
    print(json.dumps(await seed_platform(args.size, args.command), indent=2))


if __name__ == '__main__':
    import json
    asyncio.run(main())
