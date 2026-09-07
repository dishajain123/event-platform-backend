import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus, Sponsor, SponsorStatus
from app.modules.sponsorships.models import (
    SponsorshipCategory,
    SponsorshipInquiry,
    SponsorshipInquiryEvent,
    SponsorshipPackage,
)


class SponsorshipRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_categories(self, active_only: bool = True) -> list[SponsorshipCategory]:
        stmt = select(SponsorshipCategory).order_by(SponsorshipCategory.sort_order, SponsorshipCategory.name)
        if active_only:
            stmt = stmt.where(SponsorshipCategory.is_active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_category(self, category_id: uuid.UUID, *, active_only: bool = False) -> SponsorshipCategory | None:
        stmt = select(SponsorshipCategory).where(SponsorshipCategory.id == category_id)
        if active_only:
            stmt = stmt.where(SponsorshipCategory.is_active.is_(True))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def list_packages(self, active_only: bool = True) -> list[SponsorshipPackage]:
        stmt = select(SponsorshipPackage).options(selectinload(SponsorshipPackage.category)).order_by(SponsorshipPackage.name)
        if active_only:
            stmt = stmt.where(SponsorshipPackage.is_active.is_(True))
        return list((await self.db.execute(stmt)).scalars().all())

    async def get_package(self, package_id: uuid.UUID, *, active_only: bool = False) -> SponsorshipPackage | None:
        stmt = select(SponsorshipPackage).options(selectinload(SponsorshipPackage.category)).where(
            SponsorshipPackage.id == package_id
        )
        if active_only:
            stmt = stmt.where(SponsorshipPackage.is_active.is_(True))
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def create_inquiry(self, **fields) -> SponsorshipInquiry:
        inquiry = SponsorshipInquiry(**fields)
        self.db.add(inquiry)
        await self.db.flush()
        return inquiry

    async def add_inquiry_event(self, inquiry_id: uuid.UUID, event_id: uuid.UUID) -> SponsorshipInquiryEvent:
        link = SponsorshipInquiryEvent(inquiry_id=inquiry_id, event_id=event_id)
        self.db.add(link)
        await self.db.flush()
        return link

    def _inquiry_stmt(self):
        return select(SponsorshipInquiry).options(selectinload(SponsorshipInquiry.events))

    async def get_inquiry(self, inquiry_id: uuid.UUID) -> SponsorshipInquiry | None:
        result = await self.db.execute(self._inquiry_stmt().where(SponsorshipInquiry.id == inquiry_id))
        return result.scalar_one_or_none()

    async def list_inquiries(self, *, user_id: uuid.UUID | None = None, event_ids: set[uuid.UUID] | None = None, status=None) -> list[SponsorshipInquiry]:
        stmt = self._inquiry_stmt()
        if user_id is not None:
            stmt = stmt.where(SponsorshipInquiry.user_id == user_id)
        if status is not None:
            stmt = stmt.where(SponsorshipInquiry.status == status)
        if event_ids is not None:
            if not event_ids:
                return []
            stmt = stmt.join(SponsorshipInquiryEvent).where(SponsorshipInquiryEvent.event_id.in_(event_ids)).distinct()
        stmt = stmt.order_by(SponsorshipInquiry.created_at.desc())
        return list((await self.db.execute(stmt)).scalars().unique().all())

    async def page_inquiries(self, *, user_id=None, event_ids=None, status=None, search=None, page=1, page_size=25):
        if event_ids is not None and not event_ids:
            return [], 0
        filters = []
        if user_id is not None:
            filters.append(SponsorshipInquiry.user_id == user_id)
        if status is not None:
            filters.append(SponsorshipInquiry.status == status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(SponsorshipInquiry.company_name.ilike(term) | SponsorshipInquiry.contact_person.ilike(term) | SponsorshipInquiry.email.ilike(term))
        stmt = select(SponsorshipInquiry.id)
        if event_ids is not None:
            stmt = stmt.join(SponsorshipInquiryEvent).where(SponsorshipInquiryEvent.event_id.in_(event_ids)).distinct()
        stmt = stmt.where(*filters)
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = await self.db.scalar(count_stmt) or 0
        ids = await self.db.execute(stmt.order_by(SponsorshipInquiry.created_at.desc(), SponsorshipInquiry.id.desc()).offset((page - 1) * page_size).limit(page_size))
        ordered_ids = list(ids.scalars().all())
        if not ordered_ids:
            return [], total
        result = await self.db.execute(self._inquiry_stmt().where(SponsorshipInquiry.id.in_(ordered_ids)))
        by_id = {item.id: item for item in result.scalars().unique().all()}
        return [by_id[item_id] for item_id in ordered_ids if item_id in by_id], total

    async def list_public_events(self, event_ids: list[uuid.UUID]) -> list[Event]:
        if not event_ids:
            return []
        result = await self.db.execute(
            select(Event).where(
                Event.id.in_(event_ids),
                Event.status.in_(
                    [
                        EventStatus.PUBLISHED,
                        EventStatus.REGISTRATION_OPEN,
                        EventStatus.REGISTRATION_CLOSED,
                        EventStatus.LIVE,
                    ]
                ),
            )
        )
        return list(result.scalars().all())

    async def list_confirmed_sponsors(self, event_id: uuid.UUID) -> list[Sponsor]:
        result = await self.db.execute(
            select(Sponsor)
            .where(Sponsor.event_id == event_id, Sponsor.status.in_([SponsorStatus.CONFIRMED, SponsorStatus.ACTIVE]))
            .order_by(Sponsor.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_confirmed_sponsors_for_events(self, event_ids: set[uuid.UUID] | None) -> list[Sponsor]:
        if event_ids is not None and not event_ids:
            return []
        stmt = select(Sponsor).where(
            Sponsor.status.in_([SponsorStatus.CONFIRMED, SponsorStatus.ACTIVE]),
        )
        if event_ids is not None:
            stmt = stmt.where(Sponsor.event_id.in_(event_ids))
        result = await self.db.execute(stmt.order_by(Sponsor.created_at.desc()))
        return list(result.scalars().all())
