"""Deterministic, cross-platform demo data for local development.

This is deliberately backend-owned. Mobile and Console receive these rows
through the same APIs used in production; they do not maintain mock copies.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select, text

from app.core import model_registry  # noqa: F401
from app.core.base_model import Base
from app.database import AsyncSessionLocal
from app.modules.certificates.models import (
    BadgeAward,
    BadgeDefinition,
    Certificate,
    CertificateTemplate,
    CertificateType,
)
from app.modules.config_engine.models import EventConfiguration, EventFieldSchema
from app.modules.event_categories.models import MainCategory, SubCategory
from app.modules.events.models import Event, EventStatus, EventTemplate, ScheduleItem, ScheduleStatus, Sponsor, SponsorStatus, Venue
from app.modules.feedback.models import EventFeedback, FeedbackCategory
from app.modules.funnels.models import (
    Competition,
    CompetitionMatch,
    CompetitionStage,
    CompetitionStatus,
    Entry,
    EntryStatus,
    MatchResultStatus,
    MatchStatus,
    StageDecision,
    StageStatus,
    StageType,
)
from app.modules.guardians.models import ChildProfile, GuardianChildRelationship
from app.modules.identity.models import User
from app.modules.identity.models import DocumentType, IdentityDocument, VerificationStatus
from app.modules.audit_log.models import AuditLog
from app.modules.incidents.models import Incident, IncidentSeverity, IncidentStatus
from app.modules.interactions.models import (
    EventPoll,
    EventQuestion,
    PollChoiceMode,
    PollOption,
    PollResponse,
    PollResultVisibility,
    PollStatus,
    PollVote,
    QuestionUpvote,
    QuestionStatus,
)
from app.modules.media.models import Highlight, Media, MediaType
from app.modules.networking.models import (
    ConnectionIntent,
    ConnectionStatus,
    NetworkingDismissal,
    EventNetworkingConfig,
    NetworkingConnection,
    NetworkingProfile,
    NetworkingReport,
    NetworkingReportStatus,
    NetworkingVisibility,
)
from app.modules.notifications.models import (
    DeviceToken,
    DeviceTokenPlatform,
    Notification,
    NotificationChannel,
    NotificationDeliveryStatus,
    NotificationPreference,
    NotificationTemplate,
)
from app.modules.organizations.models import Organization
from app.modules.payments.models import DiscountCode, DiscountType, Payment, PaymentStatus, PaymentWebhookInbox, Refund, RefundStatus, WebhookProcessingStatus
from app.modules.assistance.models import AssistanceRequest, AssistanceRequestStatus
from app.modules.referrals.models import Referral, ReferralReward, ReferralRewardStatus, ReferralRewardType
from app.modules.rbac.models import GLOBAL_ROLES, SCOPED_ROLES, Permission, Role, RoleAssignment, RoleName, RolePermission
from app.modules.registrations.models import Registration, RegistrationParticipant, RegistrationStatus
from app.modules.sponsorships.models import (
    SponsorEngagement,
    SponsorEngagementType,
    SponsorshipCategory,
    SponsorshipDeliverable,
    SponsorshipDeliverableStatus,
    SponsorshipInquiry,
    SponsorshipInquiryEvent,
    SponsorshipInquiryStatus,
    SponsorshipPackage,
)
from app.modules.staff.models import StaffAssignment, StaffAssignmentStatus, StaffAssignmentHistory
from app.modules.teams.models import InvitationStatus, JoinRequestStatus, Team, TeamInvitation, TeamJoinRequest, TeamMember, TeamMemberRole, TeamStatus
from app.modules.tickets.models import AccessPolicy, AccessType, AccessZone, CheckIn, CheckInSource, Ticket, TicketStatus, TicketTransfer, TicketTransferStatus
from app.modules.volunteer_shifts.models import (
    VolunteerAssignmentStatus,
    VolunteerAttendance,
    VolunteerAttendanceStatus,
    VolunteerShift,
    VolunteerShiftAssignment,
    VolunteerShiftStatus,
)
from app.modules.volunteers.models import (
    VolunteerApplication,
    VolunteerApplicationStatus,
    VolunteerApplicationType,
)
from app.modules.waitlists.models import WaitlistEntry, WaitlistStatus


SEED_PREFIX = "DEMO-"
NAMESPACE = uuid.UUID("8a6dc0e8-3c3e-4e29-9ec4-8b6d2e7b7b01")
SIZES = {"small": 8, "medium": 24, "large": 72}


def stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{value}")


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


async def get_or_add(db, model, identity: dict, values: dict):
    row = (await db.execute(select(model).filter_by(**identity))).scalar_one_or_none()
    if row is not None:
        return row
    row = model(**identity, **values)
    db.add(row)
    await db.flush()
    return row


async def seed_roles(db) -> dict[RoleName, Role]:
    roles = {}
    for role_name in sorted(GLOBAL_ROLES | SCOPED_ROLES, key=str):
        role = await get_or_add(
            db,
            Role,
            {"name": role_name},
            {"id": stable_id("role", role_name.value), "is_scoped": role_name in SCOPED_ROLES},
        )
        roles[role_name] = role
    return roles


async def seed_permissions(db, roles: dict[RoleName, Role]) -> None:
    permission_specs = {
        "event.manage": "Create and configure assigned events",
        "registration.review": "Review registrations for assigned events",
        "payment.review": "Review payment and refund records",
        "ticket.scan": "Validate and scan event tickets",
        "competition.manage": "Manage competition fixtures and results",
        "volunteer.manage": "Manage volunteer applications and shifts",
    }
    permissions = {}
    for code, description in permission_specs.items():
        permissions[code] = await get_or_add(
            db,
            Permission,
            {"code": code},
            {"id": stable_id("permission", code), "description": description},
        )
    role_permission_map = {
        RoleName.OPERATIONS_ADMIN: tuple(permission_specs),
        RoleName.SUPER_ADMIN: tuple(permission_specs),
        RoleName.FINANCE_ADMIN: ("payment.review",),
        RoleName.FINANCE_OPERATOR: ("payment.review",),
        RoleName.FINANCE_AUDITOR: ("payment.review",),
        RoleName.EVENT_MANAGER: tuple(permission_specs),
        RoleName.EVENT_COORDINATOR: ("registration.review", "ticket.scan"),
        RoleName.STAFF_LEAD: ("ticket.scan", "volunteer.manage"),
        RoleName.STAFF_MEMBER: ("ticket.scan",),
    }
    for role_name, codes in role_permission_map.items():
        for code in codes:
            await get_or_add(
                db,
                RolePermission,
                {"role_id": roles[role_name].id, "permission_id": permissions[code].id},
                {"id": stable_id("role-permission", f"{role_name.value}:{code}")},
            )


async def seed_users(db, count: int) -> dict[str, User]:
    names = [
        ("superadmin", "Aarav Mehta"),
        ("operations", "Mira Kapoor"),
        ("finance", "Kabir Shah"),
        ("manager", "Ishita Rao"),
        ("staff", "Neel Verma"),
        ("volunteer", "Tara Iyer"),
    ]
    names += [(f"participant-{i:03d}", f"Participant {i:03d}") for i in range(1, count + 1)]
    users = {}
    for index, (key, name) in enumerate(names, 1):
        users[key] = await get_or_add(
            db,
            User,
            {"mobile_number": f"+919800{index:06d}"},
            {
                "id": stable_id("user", key),
                "name": name,
                "email": f"{key}@event-platform.test",
                "is_active": key != "participant-007",
            },
        )
    return users


async def seed_categories(db):
    category_specs = {
        "Sports": ["Athletics", "Football", "Badminton"],
        "Culture": ["Music", "Dance", "Theatre"],
        "Technology": ["Innovation", "Robotics", "Coding"],
    }
    categories = {}
    for name, sub_names in category_specs.items():
        category = await get_or_add(
            db,
            MainCategory,
            {"name": name},
            {"id": stable_id("main-category", name), "description": f"{name} events"},
        )
        categories[name] = category
        for sub_name in sub_names:
            await get_or_add(
                db,
                SubCategory,
                {"main_category_id": category.id, "name": sub_name},
                {"id": stable_id("sub-category", sub_name), "description": f"{sub_name} activities"},
            )
    return categories


async def seed_events(db, users, categories):
    organization = await get_or_add(
        db,
        Organization,
        {"name": f"{SEED_PREFIX}Open Events Lab"},
        {"id": stable_id("organization", "open-events-lab"), "contact_email": "ops@event-platform.test"},
    )
    now = utc_now()
    specs = [
        ("summit", "National Innovation Summit", "Technology", "Innovation", EventStatus.REGISTRATION_OPEN, now + timedelta(days=14), now + timedelta(days=16)),
        ("festival", "Community Culture Festival", "Culture", "Music", EventStatus.PUBLISHED, now + timedelta(days=45), now + timedelta(days=47)),
        ("championship", "City Sports Championship", "Sports", "Athletics", EventStatus.COMPLETED, now - timedelta(days=30), now - timedelta(days=28)),
    ]
    events = {}
    for key, name, category_name, sub_name, status, start, end in specs:
        category = categories[category_name]
        sub = (await db.execute(select(SubCategory).where(SubCategory.name == sub_name, SubCategory.main_category_id == category.id))).scalar_one()
        event = await get_or_add(
            db,
            Event,
            {"name": f"{SEED_PREFIX}{name}"},
            {
                "id": stable_id("event", key),
                "organization_id": organization.id,
                "organizer_user_id": users["manager"].id,
                "created_by": users["operations"].id,
                "description": f"Deterministic demo event for {name.lower()} workflows.",
                "category": category_name.lower(),
                "main_category_id": category.id,
                "sub_category_id": sub.id,
                "start_date": start,
                "end_date": end,
                "status": status,
            },
        )
        events[key] = event
        await get_or_add(
            db,
            EventConfiguration,
            {"event_id": event.id},
            {
                "id": stable_id("event-config", key),
                "participation_types": ["individual", "viewer", "team"],
                "fee_amount": 499 if key != "festival" else None,
                "currency": "INR",
                "capacity": 100 if key != "championship" else 60,
                "volunteer_open": True,
                "approval_required": key == "championship",
                "details": {"registration_end_at": (start - timedelta(days=2)).isoformat(), "cancellation_deadline_at": (start - timedelta(days=3)).isoformat()},
                "rules": {"min_age": 10, "max_age": 70, "team_size": {"min": 2, "max": 8}},
            },
        )
        if key == "summit":
            await get_or_add(
                db,
                EventTemplate,
                {"name": f"{SEED_PREFIX}Innovation Summit Template"},
                {
                    "id": stable_id("event-template", "summit"),
                    "owner_user_id": users["manager"].id,
                    "organization_id": organization.id,
                    "source_event_id": event.id,
                    "description": "Reusable technology summit configuration",
                    "snapshot": {"category": "Technology", "participation_types": ["individual", "viewer", "team"], "capacity": 100},
                    "is_archived": False,
                },
            )
        for participation_type in ("individual", "viewer", "team"):
            await get_or_add(
                db,
                EventFieldSchema,
                {"event_id": event.id, "participation_type": participation_type},
                {"id": stable_id("field-schema", f"{key}:{participation_type}"), "fields": [{"key": "organization", "label": "Organization", "type": "text", "required": False, "options": None}]},
            )
        venue = await get_or_add(
            db,
            Venue,
            {"event_id": event.id, "name": f"{SEED_PREFIX}{name} Hall"},
            {"id": stable_id("venue", key), "address": f"{key.title()} District, Bengaluru", "capacity": 500, "availability": [], "is_shared": False},
        )
        await get_or_add(
            db,
            ScheduleItem,
            {"event_id": event.id, "title": "Opening session"},
            {"id": stable_id("schedule", key), "venue_id": venue.id, "start_time": start + timedelta(hours=9), "end_time": start + timedelta(hours=11), "resource_key": f"{key}-main-stage", "expected_capacity": 120, "status": ScheduleStatus.COMPLETED if status == EventStatus.COMPLETED else ScheduleStatus.SCHEDULED},
        )
    return events


async def seed_roles_and_assignments(db, users, roles, events):
    global_users = {"superadmin": RoleName.SUPER_ADMIN, "operations": RoleName.OPERATIONS_ADMIN, "finance": RoleName.FINANCE_ADMIN}
    for key, role_name in global_users.items():
        await get_or_add(db, RoleAssignment, {"user_id": users[key].id, "role_id": roles[role_name].id, "event_id": None}, {"id": stable_id("assignment", key), "status": "active"})
    for event_key, user_key in (("summit", "manager"), ("festival", "manager"), ("championship", "staff")):
        await get_or_add(db, RoleAssignment, {"user_id": users[user_key].id, "role_id": roles[RoleName.EVENT_MANAGER].id, "event_id": events[event_key].id}, {"id": stable_id("assignment", f"{user_key}:{event_key}"), "status": "active"})


async def seed_registrations(db, users, events, count: int):
    registrations = []
    statuses = [RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED, RegistrationStatus.APPROVED, RegistrationStatus.PENDING_PAYMENT, RegistrationStatus.CANCELLED]
    for i in range(1, count + 1):
        user = users[f"participant-{i:03d}"]
        event = events["summit" if i % 3 else "championship"]
        status = statuses[(i - 1) % len(statuses)]
        registration = await get_or_add(
            db,
            Registration,
            {"event_id": event.id, "user_id": user.id, "child_id": None, "participation_type": "individual"},
            {"id": stable_id("registration", str(i)), "status": status, "submitted_at": utc_now() - timedelta(days=i), "cancellation_reason": "Demo cancellation" if status == RegistrationStatus.CANCELLED else None},
        )
        participant = await get_or_add(
            db,
            RegistrationParticipant,
            {"registration_id": registration.id, "full_name": user.name},
            {"id": stable_id("participant", str(i)), "user_id": user.id, "date_of_birth": date(1990 + i % 15, 4, 12), "is_captain": False},
        )
        registrations.append((registration, participant))
    return registrations


async def seed_access_and_tickets(db, users, events, registrations):
    from app.modules.tickets.service import TicketService

    ticket_service = TicketService(db)
    venue = (await db.execute(select(Venue).where(Venue.event_id == events["summit"].id))).scalars().first()
    if venue is None:
        raise RuntimeError("The demo Summit venue was not created.")
    zone = await get_or_add(db, AccessZone, {"event_id": events["summit"].id, "code": "MAIN"}, {"id": stable_id("zone", "main"), "name": "Main Gate", "is_active": True})
    policy = await get_or_add(db, AccessPolicy, {"event_id": events["summit"].id, "access_type": AccessType.GENERAL.value}, {"id": stable_id("policy", "general"), "allowed_zone_ids": [str(zone.id)], "allows_reentry": True, "max_entries": 2})
    payments = {}
    for index, (registration, _participant) in enumerate(registrations):
        payment_status = PaymentStatus.REFUNDED if registration.status == RegistrationStatus.CANCELLED else (
            PaymentStatus.INITIATED if registration.status == RegistrationStatus.PENDING_PAYMENT else PaymentStatus.VERIFIED
        )
        payment = await get_or_add(
            db,
            Payment,
            {"registration_id": registration.id},
            {
                "id": stable_id("payment", str(index)),
                "event_id": registration.event_id,
                "user_id": registration.user_id,
                "amount": Decimal("499.00"),
                "currency": "INR",
                "status": payment_status,
                "gateway_provider": "demo",
                "gateway_order_id": f"demo_order_{index:04d}",
                "gateway_payment_id": None if payment_status == PaymentStatus.INITIATED else f"demo_payment_{index:04d}",
                "verified_at": None if payment_status == PaymentStatus.INITIATED else utc_now() - timedelta(days=1),
                "captured_at": None if payment_status == PaymentStatus.INITIATED else utc_now() - timedelta(days=1),
                "reconciliation_status": "not_required",
            },
        )
        payments[registration.id] = payment
        if index == 0:
            await get_or_add(
                db,
                DiscountCode,
                {"event_id": registration.event_id, "code": "DEMO-EARLYBIRD"},
                {"id": stable_id("discount", "earlybird"), "discount_type": DiscountType.PERCENTAGE, "value": 10, "is_active": True, "max_redemptions": 50, "discount_metadata": {"label": "Demo early registration"}},
            )
            await get_or_add(
                db,
                PaymentWebhookInbox,
                {"provider_event_id": "demo-payment-captured-0001"},
                {"id": stable_id("payment-webhook", "captured"), "provider": "demo", "event_type": "payment.captured", "received_at": utc_now() - timedelta(days=1), "payload": {"payment_id": payment.gateway_payment_id, "order_id": payment.gateway_order_id}, "processing_status": WebhookProcessingStatus.PROCESSED, "attempts": 1, "processed_at": utc_now() - timedelta(days=1)},
            )
        if payment_status == PaymentStatus.REFUNDED:
            await get_or_add(db, Refund, {"payment_id": payment.id}, {"id": stable_id("refund", str(index)), "requested_by": users["finance"].id, "amount": Decimal("499.00"), "reason": "Demo cancellation", "status": RefundStatus.PROCESSED, "approved_by": users["finance"].id, "processed_at": utc_now() - timedelta(hours=12), "gateway_refund_id": f"demo_refund_{index:04d}"})
    tickets = []
    for index, (registration, participant) in enumerate(registrations):
        if registration.event_id != events["summit"].id or registration.status not in {RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}:
            continue
        payload = f"ticket:{registration.id}:{participant.id}"
        ticket = await get_or_add(db, Ticket, {"ticket_code": f"{SEED_PREFIX}TICKET-{index:04d}"}, {"id": stable_id("ticket", str(index)), "event_id": registration.event_id, "registration_id": registration.id, "participant_id": participant.id, "payment_id": payments.get(registration.id).id if payments.get(registration.id) and payments[registration.id].status == PaymentStatus.VERIFIED else None, "user_id": participant.user_id, "barcode_payload": payload, "barcode_signature": ticket_service._sign_payload(payload), "access_type": AccessType.GENERAL.value, "access_policy_id": policy.id, "entry_count": 1 if registration.status == RegistrationStatus.CHECKED_IN else 0, "status": TicketStatus.CHECKED_IN if registration.status == RegistrationStatus.CHECKED_IN else TicketStatus.ISSUED, "issued_at": utc_now() - timedelta(days=2), "checked_in_at": utc_now() - timedelta(hours=3) if registration.status == RegistrationStatus.CHECKED_IN else None, "checked_in_by": users["staff"].id if registration.status == RegistrationStatus.CHECKED_IN else None})
        # Repair the signature on an older demo row if the local barcode
        # secret changed between seed runs.
        ticket.barcode_signature = ticket_service._sign_payload(ticket.barcode_payload)
        ticket.payment_id = payments.get(registration.id).id if payments.get(registration.id) and payments[registration.id].status == PaymentStatus.VERIFIED else None
        tickets.append(ticket)
        if registration.status == RegistrationStatus.CHECKED_IN:
            await get_or_add(db, CheckIn, {"ticket_id": ticket.id, "entry_number": 1}, {"id": stable_id("checkin", str(index)), "event_id": ticket.event_id, "venue_id": venue.id, "scanned_by": users["staff"].id, "source": CheckInSource.ONLINE, "scan_payload": payload})
    if tickets:
        await get_or_add(
            db,
            TicketTransfer,
            {"ticket_id": tickets[0].id, "status": TicketTransferStatus.PENDING},
            {"id": stable_id("ticket-transfer", "pending"), "event_id": tickets[0].event_id, "from_user_id": users["participant-001"].id, "to_user_id": users["participant-005"].id},
        )
    return tickets


async def seed_supporting_modules(db, users, events, registrations):
    now = utc_now()
    await get_or_add(
        db,
        IdentityDocument,
        {"user_id": users["participant-001"].id, "document_type": DocumentType.PASSPORT},
        {"id": stable_id("identity-document", "participant-001"), "document_number_encrypted": "enc:demo:passport:001", "verification_status": VerificationStatus.VERIFIED, "verified_by": users["operations"].id, "verified_at": now - timedelta(days=2)},
    )
    await get_or_add(
        db,
        AuditLog,
        {"entity_type": "event", "entity_id": events["summit"].id, "action": "demo_event_configured"},
        {"id": stable_id("audit", "summit-configured"), "actor_user_id": users["manager"].id, "after_value": {"status": EventStatus.REGISTRATION_OPEN.value, "source": "demo_seed"}},
    )
    # Guardian/child flow.
    child = await get_or_add(db, ChildProfile, {"full_name": f"{SEED_PREFIX}Aanya Mehta"}, {"id": stable_id("child", "aanya"), "date_of_birth": date(2014, 5, 9)})
    await get_or_add(db, GuardianChildRelationship, {"guardian_user_id": users["participant-001"].id, "child_id": child.id}, {"id": stable_id("guardian", "aanya"), "relationship_label": "parent", "is_primary": True, "consent_at": now})

    # Teams, staff and volunteer workflows.
    team = await get_or_add(db, Team, {"name": f"{SEED_PREFIX}Blue Comets"}, {"id": stable_id("team", "blue-comets"), "event_id": events["summit"].id, "captain_user_id": users["participant-001"].id, "team_code": "DEMO-BLUE-COMET", "status": TeamStatus.APPROVED})
    for i, role in ((1, TeamMemberRole.CAPTAIN), (2, TeamMemberRole.MEMBER), (3, TeamMemberRole.MEMBER)):
        member = users[f"participant-{i:03d}"]
        await get_or_add(db, TeamMember, {"team_id": team.id, "user_id": member.id}, {"id": stable_id("team-member", str(i)), "full_name": member.name, "is_captain": role == TeamMemberRole.CAPTAIN, "role": role})
    await get_or_add(
        db,
        TeamInvitation,
        {"team_id": team.id, "invitee_mobile": users["participant-004"].mobile_number},
        {"id": stable_id("team-invitation", "participant-004"), "token": "DEMO-TEAM-INVITE-004", "status": InvitationStatus.PENDING},
    )
    await get_or_add(
        db,
        TeamJoinRequest,
        {"team_id": team.id, "user_id": users["participant-005"].id},
        {"id": stable_id("team-join-request", "participant-005"), "status": JoinRequestStatus.PENDING},
    )
    staff = await get_or_add(db, StaffAssignment, {"event_id": events["summit"].id, "invitee_mobile": users["staff"].mobile_number}, {"id": stable_id("staff-assignment", "staff"), "user_id": users["staff"].id, "full_name": users["staff"].name, "role_name": RoleName.STAFF_MEMBER, "role_label": "Gate Marshal", "status": StaffAssignmentStatus.ACTIVE, "invited_by": users["operations"].id, "accepted_by": users["operations"].id, "accepted_at": now})
    await get_or_add(db, StaffAssignmentHistory, {"assignment_id": staff.id, "action": "accepted"}, {"id": stable_id("staff-history", "accepted"), "actor_user_id": users["operations"].id, "after_value": {"status": "active"}})
    shift = await get_or_add(db, VolunteerShift, {"event_id": events["summit"].id, "title": "Registration desk"}, {"id": stable_id("shift", "registration"), "description": "Welcome and registration assistance", "location": "Main Gate", "starts_at": events["summit"].start_date, "ends_at": events["summit"].start_date + timedelta(hours=4), "required_count": 4, "required_role": "Guest support", "status": VolunteerShiftStatus.OPEN})
    application = await get_or_add(db, VolunteerApplication, {"event_id": events["summit"].id, "user_id": users["volunteer"].id, "application_type": VolunteerApplicationType.VOLUNTEER}, {"id": stable_id("volunteer-application", "volunteer"), "full_name": users["volunteer"].name, "phone": users["volunteer"].mobile_number, "email": users["volunteer"].email, "skills_experience": "Guest support and first aid", "availability": "Full event", "status": VolunteerApplicationStatus.APPROVED, "reviewed_by": users["manager"].id, "reviewed_at": now})
    assignment = await get_or_add(db, VolunteerShiftAssignment, {"shift_id": shift.id, "user_id": users["volunteer"].id}, {"id": stable_id("volunteer-assignment", "volunteer"), "event_id": events["summit"].id, "volunteer_application_id": application.id, "status": VolunteerAssignmentStatus.ACTIVE, "requested_by": users["volunteer"].id, "reviewed_by": users["manager"].id, "reviewed_at": now})
    await get_or_add(db, VolunteerAttendance, {"assignment_id": assignment.id}, {"id": stable_id("volunteer-attendance", "volunteer"), "event_id": events["summit"].id, "shift_id": shift.id, "user_id": users["volunteer"].id, "status": VolunteerAttendanceStatus.CHECKED_IN, "first_check_in_at": now})

    # Feedback, incidents, media and notifications.
    await get_or_add(db, EventFeedback, {"event_id": events["summit"].id, "user_id": users["participant-001"].id, "category": FeedbackCategory.EVENT_EXPERIENCE}, {"id": stable_id("feedback", "summit"), "rating": 5, "comment": "Well-organized demo event."})
    await get_or_add(db, Incident, {"event_id": events["summit"].id, "title": f"{SEED_PREFIX}Registration desk queue"}, {"id": stable_id("incident", "queue"), "reporter_user_id": users["staff"].id, "assigned_user_id": users["manager"].id, "category": "registration", "description": "Demo operational incident for command center testing.", "status": IncidentStatus.IN_PROGRESS, "severity": IncidentSeverity.MEDIUM, "in_progress_at": now})
    media = await get_or_add(db, Media, {"storage_key": "demo/summit-opening.jpg"}, {"id": stable_id("media", "summit-opening"), "event_id": events["summit"].id, "uploaded_by": users["manager"].id, "title": "Summit opening", "caption": "Demo public media", "category": "highlights", "media_type": MediaType.IMAGE, "public_url": "https://cdn.event-platform.test/demo/summit-opening.jpg", "is_published": True, "published_at": now, "published_by": users["manager"].id})
    await get_or_add(db, Highlight, {"media_id": media.id}, {"id": stable_id("highlight", "summit-opening"), "event_id": events["summit"].id, "title": "Opening highlight", "description": "Featured demo media", "display_order": 1})
    template = await get_or_add(db, NotificationTemplate, {"code": "demo.registration.confirmed"}, {"id": stable_id("notification-template", "confirmed"), "event_id": events["summit"].id, "channel": NotificationChannel.PUSH, "subject": "Registration confirmed", "body_template": "Your registration is confirmed."})
    await get_or_add(db, NotificationPreference, {"user_id": users["participant-001"].id}, {"id": stable_id("notification-preference", "participant-001"), "event_reminders": True, "registration_updates": True})
    await get_or_add(db, Notification, {"dedupe_key": "demo:registration:confirmed:participant-001"}, {"id": stable_id("notification", "confirmed"), "event_id": events["summit"].id, "recipient_user_id": users["participant-001"].id, "template_id": template.id, "channel": NotificationChannel.PUSH, "title": "Registration confirmed", "body": "Your Summit registration is confirmed.", "target_metadata": {"event_id": str(events["summit"].id)}, "delivery_status": NotificationDeliveryStatus.QUEUED, "notification_type": "registration"})
    await get_or_add(db, DeviceToken, {"token": "demo-device-token-participant-001"}, {"id": stable_id("device-token", "participant-001"), "user_id": users["participant-001"].id, "platform": DeviceTokenPlatform.WEB, "last_seen_at": now, "is_active": True})

    # Sponsor, competition, networking and engagement records.
    sponsor_category = await get_or_add(db, SponsorshipCategory, {"name": f"{SEED_PREFIX}Technology Partner"}, {"id": stable_id("sponsor-category", "technology"), "description": "Demo sponsor category", "sort_order": 1})
    package = await get_or_add(db, SponsorshipPackage, {"name": f"{SEED_PREFIX}Gold Package"}, {"id": stable_id("sponsor-package", "gold"), "category_id": sponsor_category.id, "description": "Demo package", "benefits": ["Booth", "Branding"], "minimum_offer": Decimal("50000")})
    inquiry = await get_or_add(db, SponsorshipInquiry, {"company_name": f"{SEED_PREFIX}Atlas Labs"}, {"id": stable_id("sponsor-inquiry", "atlas"), "user_id": users["participant-001"].id, "contact_person": users["participant-001"].name, "phone": users["participant-001"].mobile_number, "email": "partnerships@atlas-labs.test", "business_details": "Developer tools company", "category_id": sponsor_category.id, "package_id": package.id, "message": "Interested in the summit.", "status": SponsorshipInquiryStatus.CONFIRMED, "reviewed_by": users["operations"].id, "reviewed_at": now})
    await get_or_add(db, SponsorshipInquiryEvent, {"inquiry_id": inquiry.id, "event_id": events["summit"].id}, {"id": stable_id("sponsor-inquiry-event", "summit")})
    sponsor = await get_or_add(db, Sponsor, {"event_id": events["summit"].id, "inquiry_id": inquiry.id}, {"id": stable_id("sponsor", "atlas"), "name": "DEMO-Atlas Labs", "tier": "Gold", "logo_url": "https://cdn.event-platform.test/demo/atlas.svg", "status": SponsorStatus.ACTIVE, "category": "Technology", "description": "Demo sponsor", "offer_details": "Developer tools showcase", "benefits": ["Booth", "Branding"], "website_url": "https://atlas-labs.test", "contact_email": "partnerships@atlas-labs.test", "committed_value": Decimal("50000")})
    await get_or_add(db, SponsorshipDeliverable, {"sponsor_id": sponsor.id, "deliverable_type": "booth"}, {"id": stable_id("deliverable", "booth"), "event_id": events["summit"].id, "description": "Set up partner booth", "quantity": 1, "due_date": events["summit"].start_date - timedelta(days=1), "status": SponsorshipDeliverableStatus.IN_PROGRESS})
    await get_or_add(db, SponsorEngagement, {"sponsor_id": sponsor.id, "event_id": events["summit"].id, "participant_id": users["participant-001"].id, "engagement_type": SponsorEngagementType.BOOTH_VISIT}, {"id": stable_id("sponsor-engagement", "booth"), "captured_by": users["staff"].id, "captured_at": now, "note": "Demo booth visit", "lead_status": "captured"})
    competition = await get_or_add(db, Competition, {"event_id": events["championship"].id, "name": f"{SEED_PREFIX}Athletics Finals"}, {"id": stable_id("competition", "athletics"), "description": "Demo competition", "competition_type": "knockout", "participation_mode": "individual", "max_participants": 32, "status": CompetitionStatus.COMPLETED})
    stage = await get_or_add(db, CompetitionStage, {"event_id": events["championship"].id, "order_index": 1}, {"id": stable_id("stage", "athletics"), "competition_id": competition.id, "name": "Final", "stage_type": StageType.FINAL, "status": StageStatus.COMPLETED})
    entry_candidates = [r for r, _ in registrations if r.event_id == events["championship"].id][:2]
    entries = []
    for index, registration in enumerate(entry_candidates, 1):
        entry = await get_or_add(db, Entry, {"competition_id": competition.id, "registration_id": registration.id}, {"id": stable_id("entry", str(index)), "event_id": events["championship"].id, "current_stage_id": stage.id, "status": EntryStatus.COMPLETED, "score": Decimal(90 - index), "vote_count": 10 - index})
        entries.append(entry)
    if len(entries) >= 2:
        await get_or_add(db, CompetitionMatch, {"competition_id": competition.id, "stage_id": stage.id, "round_number": 1, "match_number": 1}, {"id": stable_id("match", "athletics-final"), "event_id": events["championship"].id, "entry_a_id": entries[0].id, "entry_b_id": entries[1].id, "winner_entry_id": entries[0].id, "scheduled_start": events["championship"].start_date + timedelta(hours=10), "scheduled_end": events["championship"].start_date + timedelta(hours=11), "status": MatchStatus.COMPLETED, "result_status": MatchResultStatus.WIN, "score_a": 90, "score_b": 89, "recorded_by": users["manager"].id, "result_recorded_at": now})
        await get_or_add(db, StageDecision, {"entry_id": entries[0].id, "stage_id": stage.id}, {"id": stable_id("stage-decision", "winner"), "decided_by": users["manager"].id, "decision": "advanced", "score": Decimal("90"), "notes": "Demo final winner"})
    await get_or_add(db, EventNetworkingConfig, {"event_id": events["summit"].id}, {"id": stable_id("networking-config", "summit"), "enabled": True, "matchmaking_enabled": True, "allowed_participant_types": ["individual"]})
    for i in range(1, min(7, len(registrations))):
        user = users[f"participant-{i:03d}"]
        await get_or_add(db, NetworkingProfile, {"event_id": events["summit"].id, "user_id": user.id}, {"id": stable_id("networking-profile", str(i)), "display_name": user.name, "organization": "Demo Organization", "designation": "Participant", "interests": ["technology", "community"] if i % 2 else ["sports", "design"], "skills": ["planning", "communication"], "bio": "Demo networking profile", "visibility": NetworkingVisibility.VISIBLE, "share_contact": False})
    await get_or_add(db, NetworkingConnection, {"event_id": events["summit"].id, "participant_low_id": users["participant-001"].id, "participant_high_id": users["participant-002"].id}, {"id": stable_id("connection", "1-2"), "requested_by": users["participant-001"].id, "intent": ConnectionIntent.CONNECT, "status": ConnectionStatus.ACCEPTED, "responded_at": now})
    await get_or_add(db, NetworkingDismissal, {"event_id": events["summit"].id, "requester_id": users["participant-003"].id, "participant_id": users["participant-004"].id}, {"id": stable_id("networking-dismissal", "3-4")})
    await get_or_add(db, NetworkingReport, {"event_id": events["summit"].id, "reporter_id": users["participant-002"].id, "reported_user_id": users["participant-003"].id}, {"id": stable_id("networking-report", "2-3"), "reason": "Demo report for moderation workflow", "status": NetworkingReportStatus.OPEN})
    poll = await get_or_add(db, EventPoll, {"event_id": events["summit"].id, "title": f"{SEED_PREFIX}Opening poll"}, {"id": stable_id("poll", "opening"), "created_by": users["manager"].id, "description": "Which session interests you most?", "starts_at": events["summit"].start_date, "ends_at": events["summit"].end_date, "choice_mode": PollChoiceMode.SINGLE, "result_visibility": PollResultVisibility.ALWAYS, "status": PollStatus.LIVE})
    for index, label in enumerate(("Workshops", "Competition", "Networking"), 1):
        await get_or_add(db, PollOption, {"poll_id": poll.id, "sort_order": index}, {"id": stable_id("poll-option", str(index)), "label": label})
    response = await get_or_add(db, PollResponse, {"poll_id": poll.id, "user_id": users["participant-001"].id}, {"id": stable_id("poll-response", "participant-001"), "submitted_at": now})
    await get_or_add(db, PollVote, {"response_id": response.id, "option_id": stable_id("poll-option", "1")}, {"id": stable_id("poll-vote", "participant-001")})
    question = await get_or_add(db, EventQuestion, {"event_id": events["summit"].id, "user_id": users["participant-001"].id, "question": "Where is the main stage?"}, {"id": stable_id("question", "stage"), "anonymous": False, "display_name": users["participant-001"].name, "status": QuestionStatus.APPROVED})
    await get_or_add(db, QuestionUpvote, {"question_id": question.id, "user_id": users["participant-002"].id}, {"id": stable_id("question-upvote", "stage-2")})

    # Waitlist, assistance, referral, certificates and badges.
    await get_or_add(db, WaitlistEntry, {"event_id": events["summit"].id, "user_id": users["participant-006"].id, "child_id": None, "team_id": None, "participation_type": "individual", "status": WaitlistStatus.WAITING}, {"id": stable_id("waitlist", "participant-006"), "joined_at": now - timedelta(hours=2)})
    assistance_registration = next(registration for registration, _ in registrations if registration.status == RegistrationStatus.CONFIRMED)
    await get_or_add(db, AssistanceRequest, {"registration_id": assistance_registration.id}, {"id": stable_id("assistance", "registration"), "event_id": assistance_registration.event_id, "requester_user_id": assistance_registration.user_id, "status": AssistanceRequestStatus.PENDING, "reason": "Demo fee assistance request", "requested_fee_waiver_amount": Decimal("100")})
    referral = await get_or_add(db, Referral, {"event_id": events["summit"].id, "referral_code": "DEMO-INVITE"}, {"id": stable_id("referral", "invite"), "referrer_user_id": users["participant-001"].id, "reward_value": Decimal("50")})
    await get_or_add(db, ReferralReward, {"referral_id": referral.id, "referred_user_id": users["participant-002"].id}, {"id": stable_id("referral-reward", "participant-002"), "registration_id": next(registration.id for registration, _ in registrations if registration.user_id == users["participant-002"].id), "reward_type": ReferralRewardType.DISCOUNT, "reward_value": Decimal("50"), "status": ReferralRewardStatus.QUALIFIED, "qualified_at": now})
    completed_registration, completed_participant = next((registration, participant) for registration, participant in registrations if registration.event_id == events["championship"].id and registration.status == RegistrationStatus.COMPLETED)
    certificate_template = await get_or_add(db, CertificateTemplate, {"event_id": events["championship"].id, "certificate_type": CertificateType.COMPLETION.value}, {"id": stable_id("certificate-template", "completion"), "title": "Championship Completion", "issuer_name": "Event Platform Demo", "criteria": {"completion": True}})
    await get_or_add(db, Certificate, {"certificate_number": "DEMO-CERT-0001"}, {"id": stable_id("certificate", "completion"), "event_id": events["championship"].id, "template_id": certificate_template.id, "registration_id": completed_registration.id, "participant_id": completed_participant.id, "user_id": completed_participant.user_id, "verification_token": "demo-certificate-token-0001", "status": "issued", "artifact_url": "https://cdn.event-platform.test/demo/certificates/DEMO-CERT-0001.pdf", "issued_by": users["operations"].id})
    badge = await get_or_add(db, BadgeDefinition, {"event_id": events["championship"].id, "name": "DEMO-Finalist"}, {"id": stable_id("badge", "finalist"), "description": "Reached the final stage", "criteria": {"stage": "final"}, "icon_reference": "trophy-finalist"})
    await get_or_add(db, BadgeAward, {"event_id": events["championship"].id, "badge_id": badge.id, "user_id": completed_participant.user_id, "participant_id": completed_participant.id}, {"id": stable_id("badge-award", "finalist"), "registration_id": completed_registration.id, "status": "awarded"})


async def seed_platform(size: str) -> dict[str, int]:
    count = SIZES[size]
    async with AsyncSessionLocal() as db:
        roles = await seed_roles(db)
        await seed_permissions(db, roles)
        users = await seed_users(db, count)
        categories = await seed_categories(db)
        events = await seed_events(db, users, categories)
        await seed_roles_and_assignments(db, users, roles, events)
        registrations = await seed_registrations(db, users, events, count)
        await seed_access_and_tickets(db, users, events, registrations)
        await seed_supporting_modules(db, users, events, registrations)
        await db.commit()
        return {"users": len(users), "events": len(events), "registrations": len(registrations)}


async def reset_local_database() -> None:
    """Explicitly destructive reset for a dedicated local database only."""
    async with AsyncSessionLocal() as db:
        if get_environment() not in {"development", "test", "local"}:
            raise RuntimeError("Refusing destructive reset outside a local environment.")
        await db.execute(text("TRUNCATE " + ", ".join(f'\"{table.name}\"' for table in reversed(Base.metadata.sorted_tables)) + " RESTART IDENTITY CASCADE"))
        await db.commit()


def get_environment() -> str:
    from app.config import get_settings

    return get_settings().environment.lower()


async def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the canonical local Event Platform demo dataset")
    parser.add_argument("command", choices=("seed", "reset"))
    parser.add_argument("--size", choices=tuple(SIZES), default="medium")
    args = parser.parse_args()
    if args.command == "reset":
        await reset_local_database()
        print("Local database reset complete.")
        return
    counts = await seed_platform(args.size)
    print("Demo seed complete: " + ", ".join(f"{key}={value}" for key, value in counts.items()))


if __name__ == "__main__":
    asyncio.run(main())
