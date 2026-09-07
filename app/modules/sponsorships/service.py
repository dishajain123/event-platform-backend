import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.core.audit import write_audit_log
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.models import Sponsor, SponsorStatus
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.sponsorships.models import (
    ALLOWED_INQUIRY_TRANSITIONS,
    SponsorshipInquiry,
    SponsorshipInquiryStatus,
    SponsorshipDeliverable,
    SponsorshipDeliverableStatus,
    ALLOWED_LEAD_STATUS_TRANSITIONS,
    SponsorConsentStatus,
    SponsorEngagement,
    SponsorEngagementType,
    SponsorLeadStatus,
)
from app.modules.sponsorships.repository import SponsorshipRepository
from app.modules.sponsorships.models import SponsorshipCategory, SponsorshipPackage
from app.modules.networking.models import NetworkingProfile, NetworkingVisibility
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES, Registration
from sqlalchemy import func, select


class SponsorshipService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SponsorshipRepository(db)

    async def _can_access_sponsor(self, actor: User, sponsor: Sponsor) -> bool:
        if await self._global_manage(actor) or await self._event_manage(actor, sponsor.event_id):
            return True
        if sponsor.inquiry_id is None:
            return False
        owner_id = await self.db.scalar(
            select(SponsorshipInquiry.user_id).where(SponsorshipInquiry.id == sponsor.inquiry_id)
        )
        return owner_id == actor.id

    async def _engagement_sponsor(self, actor: User, sponsor_id: uuid.UUID) -> Sponsor:
        sponsor = await self.repo.get_sponsor(sponsor_id)
        if sponsor is None:
            raise PermissionDeniedError("You do not have access to this sponsorship.")
        await self.db.refresh(sponsor)
        if not await self._can_access_sponsor(actor, sponsor):
            raise PermissionDeniedError("You do not have access to this sponsorship.")
        if sponsor.status not in {SponsorStatus.CONFIRMED, SponsorStatus.ACTIVE}:
            raise ValidationError("Engagement is unavailable for this sponsorship.")
        return sponsor

    async def _visible_participant(self, event_id: uuid.UUID, participant_id: uuid.UUID):
        registration = await self.db.scalar(
            select(Registration).where(
                Registration.event_id == event_id,
                Registration.user_id == participant_id,
                Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)),
            )
        )
        profile = await self.db.scalar(
            select(NetworkingProfile).where(
                NetworkingProfile.event_id == event_id,
                NetworkingProfile.user_id == participant_id,
                NetworkingProfile.visibility == NetworkingVisibility.VISIBLE,
            )
        )
        if registration is None or profile is None:
            raise ValidationError("Participant is not eligible for sponsor engagement.")
        return profile

    @staticmethod
    def _engagement_out(engagement: SponsorEngagement, profile=None):
        return {
            **{field: getattr(engagement, field) for field in (
                "id", "sponsor_id", "event_id", "participant_id", "captured_by", "captured_at",
                "engagement_type", "note", "consent_status", "consent_at", "consent_source", "lead_status",
            )},
            "participant_display_name": getattr(profile, "display_name", None),
            "participant_organization": getattr(profile, "organization", None),
            "participant_designation": getattr(profile, "designation", None),
        }

    async def capture_engagement(self, actor: User, event_id: uuid.UUID, payload: dict):
        sponsor = await self._engagement_sponsor(actor, payload["sponsor_id"])
        if sponsor.event_id != event_id:
            raise PermissionDeniedError("This sponsorship is not assigned to the event.")
        profile = await self._visible_participant(event_id, payload["participant_id"])
        if payload["participant_id"] == actor.id:
            raise ValidationError("A sponsor cannot capture itself as a participant.")
        if payload["engagement_type"] == SponsorEngagementType.LEAD_CAPTURE and not payload.get("consent_given"):
            raise ValidationError("Explicit participant consent is required for lead capture.")
        if payload.get("consent_given") and not payload.get("consent_source"):
            raise ValidationError("Consent source is required when consent is given.")
        if await self.repo.active_engagement_exists(
            sponsor_id=sponsor.id,
            event_id=event_id,
            participant_id=payload["participant_id"],
            engagement_type=payload["engagement_type"],
        ):
            raise ConflictError("This participant already has an engagement for this sponsor and type.")
        engagement = SponsorEngagement(
            sponsor_id=sponsor.id,
            event_id=event_id,
            participant_id=payload["participant_id"],
            captured_by=actor.id,
            captured_at=datetime.now(timezone.utc),
            engagement_type=payload["engagement_type"],
            note=payload.get("note"),
            consent_status=SponsorConsentStatus.GIVEN if payload.get("consent_given") else SponsorConsentStatus.NOT_GIVEN,
            consent_at=datetime.now(timezone.utc) if payload.get("consent_given") else None,
            consent_source=payload.get("consent_source"),
            lead_status=SponsorLeadStatus.CAPTURED,
        )
        self.db.add(engagement)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            if "uq_sponsor_engagement_identity" in str(exc.orig) or "UNIQUE constraint" in str(exc.orig):
                raise ConflictError("This participant already has an engagement for this sponsor and type.") from exc
            raise
        await write_audit_log(self.db, entity_type="sponsor_engagement", entity_id=engagement.id, action="captured", actor_user_id=actor.id, after_value={"event_id": str(event_id), "sponsor_id": str(sponsor.id), "engagement_type": engagement.engagement_type.value, "consent_status": engagement.consent_status.value})
        await self.db.commit()
        await self.db.refresh(engagement)
        return self._engagement_out(engagement, profile)

    async def page_engagements(self, actor: User, event_id: uuid.UUID, *, sponsor_id: uuid.UUID, page=1, page_size=25, status=None, engagement_type=None, consent_status=None, search=None):
        sponsor = await self._engagement_sponsor(actor, sponsor_id)
        if sponsor.event_id != event_id:
            raise PermissionDeniedError("This sponsorship is not assigned to the event.")
        rows, total = await self.repo.page_engagements(event_id=event_id, sponsor_id=sponsor_id, page=page, page_size=page_size, status=status, engagement_type=engagement_type, consent_status=consent_status, search=search)
        return [self._engagement_out(engagement, profile) for engagement, profile in rows], total

    async def get_engagement(self, actor: User, engagement_id: uuid.UUID):
        engagement = await self.repo.get_engagement(engagement_id)
        if engagement is None:
            raise NotFoundError("Sponsor engagement not found.")
        sponsor = await self._engagement_sponsor(actor, engagement.sponsor_id)
        profile = await self.db.scalar(select(NetworkingProfile).where(NetworkingProfile.event_id == engagement.event_id, NetworkingProfile.user_id == engagement.participant_id, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE))
        return self._engagement_out(engagement, profile)

    async def update_lead_status(self, actor: User, engagement_id: uuid.UUID, new_status: SponsorLeadStatus):
        engagement = await self.repo.get_engagement(engagement_id)
        if engagement is None:
            raise NotFoundError("Sponsor engagement not found.")
        await self._engagement_sponsor(actor, engagement.sponsor_id)
        if new_status not in ALLOWED_LEAD_STATUS_TRANSITIONS[engagement.lead_status]:
            raise ValidationError(f"Cannot move lead from {engagement.lead_status} to {new_status}.")
        before = engagement.lead_status.value
        engagement.lead_status = new_status
        if new_status == SponsorLeadStatus.UNSUBSCRIBED:
            engagement.consent_status = SponsorConsentStatus.WITHDRAWN
            engagement.consent_at = datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="sponsor_engagement", entity_id=engagement.id, action="status_changed", actor_user_id=actor.id, before_value={"status": before}, after_value={"status": new_status.value})
        await self.db.commit()
        return await self.get_engagement(actor, engagement.id)

    async def update_consent(self, actor: User, engagement_id: uuid.UUID, consent_given: bool, consent_source: str | None):
        engagement = await self.repo.get_engagement(engagement_id)
        if engagement is None:
            raise NotFoundError("Sponsor engagement not found.")
        if not (not consent_given and actor.id == engagement.participant_id):
            await self._engagement_sponsor(actor, engagement.sponsor_id)
        if consent_given and not consent_source:
            raise ValidationError("Consent source is required when consent is given.")
        engagement.consent_status = SponsorConsentStatus.GIVEN if consent_given else SponsorConsentStatus.WITHDRAWN
        engagement.consent_at = datetime.now(timezone.utc)
        engagement.consent_source = consent_source
        if not consent_given and engagement.lead_status != SponsorLeadStatus.UNSUBSCRIBED:
            engagement.lead_status = SponsorLeadStatus.UNSUBSCRIBED
        await write_audit_log(self.db, entity_type="sponsor_engagement", entity_id=engagement.id, action="consent_changed", actor_user_id=actor.id, after_value={"consent_status": engagement.consent_status.value})
        await self.db.commit()
        return await self.get_engagement(actor, engagement.id)

    async def engagement_metrics(self, actor: User, event_id: uuid.UUID, sponsor_id: uuid.UUID):
        sponsor = await self._engagement_sponsor(actor, sponsor_id)
        if sponsor.event_id != event_id:
            raise PermissionDeniedError("This sponsorship is not assigned to the event.")
        rows = await self.db.scalars(select(SponsorEngagement).where(SponsorEngagement.event_id == event_id, SponsorEngagement.sponsor_id == sponsor_id))
        engagements = list(rows.all())
        total = len(engagements)
        leads_only = [item for item in engagements if item.engagement_type == SponsorEngagementType.LEAD_CAPTURE]
        counts = {status.value: sum(item.lead_status == status for item in leads_only) for status in SponsorLeadStatus}
        by_type = {kind.value: sum(item.engagement_type == kind for item in engagements) for kind in SponsorEngagementType}
        by_date: dict[str, int] = {}
        for item in engagements:
            key = item.captured_at.date().isoformat()
            by_date[key] = by_date.get(key, 0) + 1
        leads = len(leads_only)
        qualified = counts[SponsorLeadStatus.QUALIFIED] + counts[SponsorLeadStatus.CONTACTED] + counts[SponsorLeadStatus.CONVERTED]
        return {
            "event_id": event_id, "sponsor_id": sponsor_id,
            "total_leads": leads, "qualified_leads": qualified,
            "contacted_leads": counts[SponsorLeadStatus.CONTACTED] + counts[SponsorLeadStatus.CONVERTED],
            "converted_leads": counts[SponsorLeadStatus.CONVERTED],
            "dismissed_leads": counts[SponsorLeadStatus.DISMISSED], "unsubscribed_leads": counts[SponsorLeadStatus.UNSUBSCRIBED],
            "total_engagements": total, "unique_participants_engaged": len({item.participant_id for item in engagements}),
            "conversion_rate": round(counts[SponsorLeadStatus.CONVERTED] / leads * 100, 2) if leads else 0.0,
            "qualification_rate": round(qualified / leads * 100, 2) if leads else 0.0,
            "by_type": by_type, "by_date": dict(sorted(by_date.items())),
        }

    async def _global_manage(self, actor: User) -> bool:
        return await user_has_global_role(self.db, actor.id, {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN})

    async def create_category(self, **fields):
        category = SponsorshipCategory(**fields)
        self.db.add(category)
        await self.db.commit()
        await self.db.refresh(category)
        return category

    async def create_package(self, **fields):
        if await self.repo.get_category(fields["category_id"]) is None:
            raise ValidationError("Sponsorship category not found.")
        package = SponsorshipPackage(**fields)
        self.db.add(package)
        await self.db.commit()
        return await self.repo.get_package(package.id)

    async def _event_manage(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(
            self.db, actor.id, {RoleName.EVENT_MANAGER}, event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def _get_inquiry(self, inquiry_id: uuid.UUID) -> SponsorshipInquiry:
        inquiry = await self.repo.get_inquiry(inquiry_id)
        if inquiry is None:
            raise NotFoundError("Sponsorship inquiry not found.")
        return inquiry

    async def _can_manage_inquiry(self, actor: User, inquiry: SponsorshipInquiry) -> bool:
        if await self._global_manage(actor):
            return True
        event_ids = {link.event_id for link in inquiry.events}
        assigned = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        return bool(event_ids & assigned)

    async def create_inquiry(self, actor: User, payload: dict) -> SponsorshipInquiry:
        category_id = payload.pop("category_id", None)
        package_id = payload.pop("package_id", None)
        event_ids = list(dict.fromkeys(payload.pop("event_ids", [])))
        category = None
        if category_id is not None:
            category = await self.repo.get_category(category_id, active_only=True)
        if category_id is not None and category is None:
            raise ValidationError("Sponsorship category not found.")
        package = None
        if package_id is not None:
            package = await self.repo.get_package(package_id, active_only=True)
        if package_id is not None and package is None:
            raise ValidationError("Sponsorship package not found.")
        if package is not None and package.category_id != category_id:
            raise ValidationError("The sponsorship package does not belong to the selected category.")
        events = await self.repo.list_public_events(event_ids)
        if len(events) != len(event_ids):
            raise ValidationError("One or more selected events are not available for sponsorship.")
        duplicate = await self.repo.list_inquiries(user_id=actor.id, status=SponsorshipInquiryStatus.NEW)
        if any({link.event_id for link in inquiry.events} == set(event_ids) and inquiry.company_name == payload["company_name"] for inquiry in duplicate):
            raise ConflictError("A matching sponsorship inquiry is already open.")
        inquiry = await self.repo.create_inquiry(user_id=actor.id, category_id=category_id, package_id=package_id, **payload)
        for event_id in event_ids:
            await self.repo.add_inquiry_event(inquiry.id, event_id)
        await write_audit_log(self.db, entity_type="sponsorship_inquiry", entity_id=inquiry.id, action="created", actor_user_id=actor.id, after_value={"status": inquiry.status.value, "event_ids": [str(event_id) for event_id in event_ids]})
        await self.db.commit()
        return await self._get_inquiry(inquiry.id)

    async def list_my_inquiries(self, actor: User):
        return await self.repo.list_inquiries(user_id=actor.id)

    async def list_manageable_inquiries(self, actor: User, event_id=None, status=None):
        if await self._global_manage(actor):
            return await self.repo.list_inquiries(
                event_ids={event_id} if event_id else None, status=status
            )
        event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        if event_id is not None:
            if event_id not in event_ids:
                raise PermissionDeniedError("You don't have permission to view sponsorship for this event.")
            event_ids = {event_id}
        return await self.repo.list_inquiries(event_ids=event_ids, status=status)

    async def page_manageable_inquiries(self, actor: User, event_id=None, status=None, search=None, *, page=1, page_size=25):
        if await self._global_manage(actor):
            event_ids = {event_id} if event_id else None
        else:
            event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
            if event_id is not None:
                if event_id not in event_ids:
                    raise PermissionDeniedError("You don't have permission to view sponsorship for this event.")
                event_ids = {event_id}
        return await self.repo.page_inquiries(event_ids=event_ids, status=status, search=search, page=page, page_size=page_size)

    async def list_manageable_sponsors(self, actor: User, event_id: uuid.UUID | None = None):
        if await self._global_manage(actor):
            event_ids = {event_id} if event_id else None
        else:
            event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
            if event_id is not None:
                if event_id not in event_ids:
                    raise PermissionDeniedError("You don't have permission to view sponsors for this event.")
                event_ids = {event_id}
        return await self.repo.list_confirmed_sponsors_for_events(event_ids)

    async def _event_ids_for_manager(self, actor: User, event_id: uuid.UUID | None = None):
        event_ids = await user_scoped_event_ids(self.db, actor.id, {RoleName.EVENT_MANAGER})
        if event_id is not None:
            if event_id not in event_ids:
                raise PermissionDeniedError("You don't have permission to view sponsorship for this event.")
            return {event_id}
        return event_ids

    async def get_visible_inquiry(self, actor: User, inquiry_id: uuid.UUID):
        inquiry = await self._get_inquiry(inquiry_id)
        if inquiry.user_id != actor.id and not await self._can_manage_inquiry(actor, inquiry):
            raise PermissionDeniedError("You cannot access this sponsorship inquiry.")
        return inquiry

    async def update_status(self, actor: User, inquiry_id: uuid.UUID, new_status: SponsorshipInquiryStatus):
        inquiry = await self._get_inquiry(inquiry_id)
        if not await self._can_manage_inquiry(actor, inquiry):
            raise PermissionDeniedError("You cannot manage this sponsorship inquiry.")
        if new_status == SponsorshipInquiryStatus.CONFIRMED:
            raise ValidationError("Confirm an inquiry by assigning it to an event.")
        if new_status not in ALLOWED_INQUIRY_TRANSITIONS[inquiry.status]:
            raise ValidationError(f"Cannot move inquiry from {inquiry.status} to {new_status}.")
        before_status = inquiry.status.value
        inquiry.status = new_status
        inquiry.reviewed_by = actor.id
        inquiry.reviewed_at = datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="sponsorship_inquiry", entity_id=inquiry.id, action="status_changed", actor_user_id=actor.id, before_value={"status": before_status}, after_value={"status": new_status.value})
        await self.db.commit()
        return await self._get_inquiry(inquiry.id)

    async def assign_sponsor(self, actor: User, inquiry_id: uuid.UUID, payload: dict) -> Sponsor:
        inquiry = await self._get_inquiry(inquiry_id)
        event_id = payload.pop("event_id")
        if not await self._event_manage(actor, event_id):
            raise PermissionDeniedError("You cannot manage sponsors for this event.")
        if event_id not in {link.event_id for link in inquiry.events}:
            raise ValidationError("The event is not linked to this sponsorship inquiry.")
        if inquiry.status != SponsorshipInquiryStatus.APPROVED:
            raise ValidationError("Only an approved inquiry can be confirmed for an event.")
        existing = await self.repo.list_confirmed_sponsors(event_id)
        if any(s.inquiry_id == inquiry.id for s in existing):
            raise ConflictError("This inquiry is already assigned to the event.")
        sponsor = Sponsor(
            event_id=event_id,
            inquiry_id=inquiry.id,
            name=inquiry.company_name,
            tier=payload.pop("tier", None),
            logo_url=payload.pop("logo_url", None),
            status=SponsorStatus.CONFIRMED,
            category=payload.pop("category", None),
            description=payload.pop("description", inquiry.business_details),
            offer_details=payload.pop("offer_details", inquiry.offer_details),
            benefits=payload.pop("benefits", []),
            website_url=payload.pop("website_url", None),
            contact_email=payload.pop("contact_email", inquiry.email),
            committed_value=payload.pop("committed_value", None),
        )
        self.db.add(sponsor)
        inquiry.status = SponsorshipInquiryStatus.CONFIRMED
        try:
            await self.db.flush()
            await write_audit_log(self.db, entity_type="sponsor", entity_id=sponsor.id, action="created", actor_user_id=actor.id, after_value={"event_id": str(event_id), "inquiry_id": str(inquiry.id), "status": sponsor.status.value, "committed_value": str(sponsor.committed_value) if sponsor.committed_value is not None else None})
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if "uq_sponsor_event_inquiry" in str(exc.orig):
                raise ConflictError("This inquiry is already assigned to the event.") from exc
            raise
        await self.db.refresh(sponsor)
        return sponsor

    async def _get_sponsor_for_actor(self, actor: User, sponsor_id: uuid.UUID) -> Sponsor:
        sponsor = await self.repo.get_sponsor(sponsor_id)
        if sponsor is None or not await self._event_manage(actor, sponsor.event_id):
            raise PermissionDeniedError("You do not have access to this sponsorship.")
        return sponsor

    async def update_sponsor_status(self, actor: User, sponsor_id: uuid.UUID, status: SponsorStatus) -> Sponsor:
        sponsor = await self._get_sponsor_for_actor(actor, sponsor_id)
        allowed = {
            SponsorStatus.CONFIRMED: {SponsorStatus.ACTIVE, SponsorStatus.CANCELLED},
            SponsorStatus.ACTIVE: {SponsorStatus.COMPLETED, SponsorStatus.CANCELLED},
            SponsorStatus.COMPLETED: {SponsorStatus.ACTIVE},
            SponsorStatus.CANCELLED: {SponsorStatus.CONFIRMED},
            SponsorStatus.INACTIVE: {SponsorStatus.ACTIVE, SponsorStatus.CANCELLED},
        }
        if status not in allowed.get(sponsor.status, set()):
            raise ValidationError(f"Cannot move sponsorship from {sponsor.status} to {status}.")
        before = sponsor.status.value
        sponsor.status = status
        await write_audit_log(self.db, entity_type="sponsor", entity_id=sponsor.id, action="status_changed", actor_user_id=actor.id, before_value={"status": before, "event_id": str(sponsor.event_id)}, after_value={"status": status.value, "event_id": str(sponsor.event_id)})
        await self.db.commit()
        await self.db.refresh(sponsor)
        return sponsor

    async def update_sponsor_financials(self, actor: User, sponsor_id: uuid.UUID, committed_value):
        sponsor = await self._get_sponsor_for_actor(actor, sponsor_id)
        before = sponsor.committed_value
        sponsor.committed_value = committed_value
        await write_audit_log(self.db, entity_type="sponsor", entity_id=sponsor.id, action="financials_changed", actor_user_id=actor.id, before_value={"committed_value": str(before) if before is not None else None, "event_id": str(sponsor.event_id)}, after_value={"committed_value": str(committed_value) if committed_value is not None else None, "event_id": str(sponsor.event_id)})
        await self.db.commit()
        await self.db.refresh(sponsor)
        return sponsor

    async def create_deliverable(self, actor: User, sponsor_id: uuid.UUID, payload: dict) -> SponsorshipDeliverable:
        sponsor = await self._get_sponsor_for_actor(actor, sponsor_id)
        deliverable = SponsorshipDeliverable(sponsor_id=sponsor.id, event_id=sponsor.event_id, **payload)
        self.db.add(deliverable)
        await self.db.flush()
        await write_audit_log(self.db, entity_type="sponsorship_deliverable", entity_id=deliverable.id, action="created", actor_user_id=actor.id, after_value={"sponsor_id": str(sponsor.id), "event_id": str(sponsor.event_id), "type": deliverable.deliverable_type})
        await self.db.commit()
        await self.db.refresh(deliverable)
        return deliverable

    async def list_deliverables(self, actor: User, sponsor_id: uuid.UUID, *, status=None, search=None):
        await self._get_sponsor_for_actor(actor, sponsor_id)
        return await self.repo.list_deliverables(sponsor_id, status=status, search=search)

    async def page_deliverables(self, actor: User, sponsor_id: uuid.UUID, *, status=None, search=None, page=1, page_size=25):
        await self._get_sponsor_for_actor(actor, sponsor_id)
        return await self.repo.page_deliverables(sponsor_id, status=status, search=search, page=page, page_size=page_size)

    async def update_deliverable(self, actor: User, deliverable_id: uuid.UUID, payload: dict) -> SponsorshipDeliverable:
        deliverable = await self.repo.get_deliverable(deliverable_id)
        if deliverable is None:
            raise NotFoundError("Sponsorship deliverable not found.")
        await self._get_sponsor_for_actor(actor, deliverable.sponsor_id)
        target = payload.pop("status", None)
        if target is not None:
            allowed = {
                SponsorshipDeliverableStatus.PENDING: {SponsorshipDeliverableStatus.IN_PROGRESS, SponsorshipDeliverableStatus.CANCELLED},
                SponsorshipDeliverableStatus.IN_PROGRESS: {SponsorshipDeliverableStatus.COMPLETED, SponsorshipDeliverableStatus.CANCELLED, SponsorshipDeliverableStatus.PENDING},
                SponsorshipDeliverableStatus.COMPLETED: {SponsorshipDeliverableStatus.IN_PROGRESS},
                SponsorshipDeliverableStatus.CANCELLED: {SponsorshipDeliverableStatus.PENDING},
            }
            if target not in allowed.get(deliverable.status, set()):
                raise ValidationError(f"Cannot move deliverable from {deliverable.status} to {target}.")
            before = deliverable.status.value
            deliverable.status = target
            if target == SponsorshipDeliverableStatus.COMPLETED:
                deliverable.completed_at = datetime.now(timezone.utc)
            elif target != SponsorshipDeliverableStatus.COMPLETED:
                deliverable.completed_at = None
            await write_audit_log(self.db, entity_type="sponsorship_deliverable", entity_id=deliverable.id, action="status_changed", actor_user_id=actor.id, before_value={"status": before}, after_value={"status": target.value, "event_id": str(deliverable.event_id)})
        for key, value in payload.items():
            setattr(deliverable, key, value)
        await self.db.commit()
        await self.db.refresh(deliverable)
        return deliverable

    async def get_metrics(self, actor: User, event_id: uuid.UUID):
        if not await self._event_manage(actor, event_id):
            raise PermissionDeniedError("You do not have access to sponsorship metrics for this event.")
        data = await self.repo.metrics(event_id)
        from app.modules.sponsorships.schemas import SponsorshipMetricsOut
        return SponsorshipMetricsOut(event_id=event_id, confirmed_value=data["confirmed_value"], paid_value=data["paid_value"], value_by_category=[{"category": row[0], "committed_value": row[1], "sponsors": int(row[2])} for row in data["categories"]], **{key: data[key] for key in ("total_sponsors", "active_sponsorships", "completed_sponsorships", "total_deliverables", "completed_deliverables", "pending_deliverables", "overdue_deliverables")}, fulfillment_percentage=round(data["completed_deliverables"] / data["total_deliverables"] * 100, 1) if data["total_deliverables"] else None)

    async def sponsor_summary(self, actor: User, sponsor_id: uuid.UUID):
        sponsor = await self._get_sponsor_for_actor(actor, sponsor_id)
        items = await self.repo.list_deliverables(sponsor.id)
        now = datetime.now(timezone.utc)
        completed = sum(item.status == SponsorshipDeliverableStatus.COMPLETED for item in items)
        pending = sum(item.status in {SponsorshipDeliverableStatus.PENDING, SponsorshipDeliverableStatus.IN_PROGRESS} for item in items)
        overdue = sum(item.status in {SponsorshipDeliverableStatus.PENDING, SponsorshipDeliverableStatus.IN_PROGRESS} and item.due_date is not None and item.due_date < now for item in items)
        from app.modules.sponsorships.schemas import SponsorSummaryOut
        return SponsorSummaryOut(sponsor_id=sponsor.id, event_id=sponsor.event_id, sponsor_name=sponsor.name, category=sponsor.category, committed_value=sponsor.committed_value, paid_value=sponsor.paid_value, total_deliverables=len(items), completed_deliverables=completed, pending_deliverables=pending, overdue_deliverables=overdue, fulfillment_percentage=round(completed / len(items) * 100, 1) if items else None)
