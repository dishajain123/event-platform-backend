import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role, user_has_scoped_role, user_scoped_event_ids
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.models import Sponsor, SponsorStatus
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.sponsorships.models import (
    ALLOWED_INQUIRY_TRANSITIONS,
    SponsorshipInquiry,
    SponsorshipInquiryStatus,
)
from app.modules.sponsorships.repository import SponsorshipRepository
from app.modules.sponsorships.models import SponsorshipCategory, SponsorshipPackage


class SponsorshipService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SponsorshipRepository(db)

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
        inquiry.status = new_status
        inquiry.reviewed_by = actor.id
        inquiry.reviewed_at = datetime.now(timezone.utc)
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
        )
        self.db.add(sponsor)
        inquiry.status = SponsorshipInquiryStatus.CONFIRMED
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if "uq_sponsor_event_inquiry" in str(exc.orig):
                raise ConflictError("This inquiry is already assigned to the event.") from exc
            raise
        await self.db.refresh(sponsor)
        return sponsor
