from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select

from app.exceptions import ConflictError, PermissionDeniedError, ValidationError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.models import EventStatus
from app.modules.events.service import EventService
from app.modules.identity.models import User
from app.modules.rbac.models import Role, RoleAssignment, RoleName
from app.modules.networking.models import EventNetworkingConfig, NetworkingProfile, NetworkingVisibility
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.sponsorships.models import SponsorEngagementType, SponsorLeadStatus, SponsorshipDeliverableStatus, SponsorshipInquiryStatus
from app.modules.sponsorships.service import SponsorshipService


async def _role(db, user, role_name, event_id=None):
    role = (await db.execute(select(Role).where(Role.name == role_name))).scalar_one()
    db.add(RoleAssignment(user_id=user.id, role_id=role.id, event_id=event_id))
    await db.flush()


async def _public_event(db, creator):
    service = EventService(db)
    event = await service.create_event(
        created_by=creator.id,
        name="Sponsorship Event",
        description=None,
        category="community",
        start_date=datetime.now(timezone.utc) + timedelta(days=5),
        end_date=datetime.now(timezone.utc) + timedelta(days=6),
        organization_id=None,
    )
    await ConfigEngineService(db).upsert_configuration(
        event.id,
        participation_types=["viewer"],
        fee_amount=None,
        currency="INR",
        capacity=10,
        approval_required=False,
        rules={},
        discount_rules=None,
    )
    event = await service.transition_status(event.id, EventStatus.CONFIGURED, creator.id)
    return await service.publish(event.id, creator.id)


@pytest.mark.asyncio
async def test_inquiry_owner_operations_and_event_manager_scope(db_session):
    creator = User(mobile_number="+919700000001")
    applicant = User(mobile_number="+919700000002")
    operations = User(mobile_number="+919700000003")
    manager = User(mobile_number="+919700000004")
    outsider = User(mobile_number="+919700000005")
    db_session.add_all([creator, applicant, operations, manager, outsider])
    await db_session.flush()
    event = await _public_event(db_session, creator)
    await _role(db_session, operations, RoleName.OPERATIONS_ADMIN)
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    service = SponsorshipService(db_session)

    category = await service.create_category(name="Community", description=None, is_active=True, sort_order=0)
    inquiry = await service.create_inquiry(
        applicant,
        {
            "company_name": "Example Partner",
            "contact_person": "Applicant",
            "phone": "+919700000002",
            "email": "applicant@example.com",
            "business_details": "Local business",
            "category_id": category.id,
            "event_ids": [event.id],
            "offer_details": "Equipment",
            "message": "Interested in supporting the event",
        },
    )
    assert inquiry.user_id == applicant.id
    assert (await service.list_my_inquiries(applicant))[0].id == inquiry.id
    with pytest.raises(PermissionDeniedError):
        await service.get_visible_inquiry(outsider, inquiry.id)

    await service.update_status(operations, inquiry.id, SponsorshipInquiryStatus.APPROVED)
    with pytest.raises(PermissionDeniedError):
        await service.assign_sponsor(manager, inquiry.id, {"event_id": uuid.uuid4()})

    sponsor = await service.assign_sponsor(manager, inquiry.id, {"event_id": event.id, "tier": "partner"})
    assert sponsor.event_id == event.id
    assert (await EventService(db_session).list_sponsors(event.id))[0].name == "Example Partner"
    assert (await service.list_manageable_sponsors(manager, event.id))[0].id == sponsor.id
    with pytest.raises(PermissionDeniedError):
        await service.list_manageable_sponsors(outsider, event.id)
    with pytest.raises(ValidationError):
        await service.assign_sponsor(manager, inquiry.id, {"event_id": event.id})
    with pytest.raises(ValidationError):
        await service.update_status(operations, inquiry.id, SponsorshipInquiryStatus.APPROVED)

    db_session.add(EventNetworkingConfig(event_id=event.id, enabled=True, matchmaking_enabled=True))
    db_session.add(Registration(event_id=event.id, user_id=manager.id, participation_type="participant", status=RegistrationStatus.CONFIRMED))
    db_session.add(NetworkingProfile(event_id=event.id, user_id=manager.id, display_name="Event Manager", visibility=NetworkingVisibility.VISIBLE))
    await db_session.commit()
    engagement = await service.capture_engagement(applicant, event.id, {
        "sponsor_id": sponsor.id,
        "participant_id": manager.id,
        "engagement_type": SponsorEngagementType.LEAD_CAPTURE,
        "consent_given": True,
        "consent_source": "booth_form",
        "note": "Interested in the sponsor offering",
    })
    assert engagement["consent_status"].value == "given"
    with pytest.raises(ConflictError):
        await service.capture_engagement(applicant, event.id, {
            "sponsor_id": sponsor.id,
            "participant_id": manager.id,
            "engagement_type": SponsorEngagementType.LEAD_CAPTURE,
            "consent_given": True,
            "consent_source": "booth_form",
        })
    updated = await service.update_lead_status(applicant, engagement["id"], SponsorLeadStatus.QUALIFIED)
    assert updated["lead_status"].value == "qualified"
    withdrawn = await service.update_consent(manager, engagement["id"], False, None)
    assert withdrawn["consent_status"].value == "withdrawn"
    metrics = await service.engagement_metrics(applicant, event.id, sponsor.id)
    assert metrics["total_leads"] == 1 and metrics["unsubscribed_leads"] == 1
    with pytest.raises(PermissionDeniedError):
        await service.get_engagement(outsider, engagement["id"])


@pytest.mark.asyncio
async def test_inquiry_rejects_inactive_or_mismatched_package(db_session):
    applicant = User(mobile_number="+919700000006")
    db_session.add(applicant)
    await db_session.flush()
    service = SponsorshipService(db_session)
    inactive = await service.create_category(name="Inactive", description=None, is_active=False, sort_order=0)
    active = await service.create_category(name="Active", description=None, is_active=True, sort_order=1)
    package = await service.create_package(
        category_id=active.id,
        name="Active Package",
        description=None,
        benefits=[],
        minimum_offer=None,
        is_active=True,
    )
    payload = {
        "company_name": "Example Partner",
        "contact_person": "Applicant",
        "phone": "+919700000006",
        "email": "applicant2@example.com",
        "category_id": inactive.id,
        "event_ids": [],
    }
    with pytest.raises(ValidationError):
        await service.create_inquiry(applicant, payload)
    payload["category_id"] = inactive.id
    payload["package_id"] = package.id
    with pytest.raises(ValidationError):
        await service.create_inquiry(applicant, payload)


@pytest.mark.asyncio
async def test_sponsor_fulfillment_metrics_and_scope(db_session):
    creator = User(mobile_number="+919700000031")
    applicant = User(mobile_number="+919700000032")
    manager = User(mobile_number="+919700000033")
    outsider = User(mobile_number="+919700000034")
    db_session.add_all([creator, applicant, manager, outsider])
    await db_session.flush()
    event = await _public_event(db_session, creator)
    await _role(db_session, manager, RoleName.EVENT_MANAGER, event.id)
    service = SponsorshipService(db_session)
    inquiry = await service.create_inquiry(applicant, {"company_name": "Metrics Partner", "contact_person": "Owner", "phone": "+919700000032", "email": "metrics@example.com", "event_ids": [event.id], "category_id": None})
    await service.update_status(manager, inquiry.id, SponsorshipInquiryStatus.APPROVED)
    sponsor = await service.assign_sponsor(manager, inquiry.id, {"event_id": event.id, "tier": "gold", "category": "Branding", "committed_value": 12500})
    first = await service.create_deliverable(manager, sponsor.id, {"deliverable_type": "logo", "description": "Logo on stage", "due_date": datetime.now(timezone.utc) - timedelta(days=1)})
    second = await service.create_deliverable(manager, sponsor.id, {"deliverable_type": "passes", "description": "Complimentary passes", "quantity": 10})
    metrics = await service.get_metrics(manager, event.id)
    assert metrics.total_sponsors == 1
    assert metrics.confirmed_value == 12500
    assert metrics.paid_value is None
    assert metrics.total_deliverables == 2
    assert metrics.pending_deliverables == 2
    assert metrics.overdue_deliverables == 1
    assert metrics.fulfillment_percentage == 0.0
    with pytest.raises(PermissionDeniedError):
        await service.get_metrics(outsider, event.id)
    await service.update_deliverable(manager, first.id, {"status": SponsorshipDeliverableStatus.IN_PROGRESS})
    await service.update_deliverable(manager, first.id, {"status": SponsorshipDeliverableStatus.COMPLETED, "completion_notes": "Installed"})
    summary = await service.sponsor_summary(manager, sponsor.id)
    assert summary.completed_deliverables == 1
    assert summary.overdue_deliverables == 0
    assert summary.fulfillment_percentage == 50.0
