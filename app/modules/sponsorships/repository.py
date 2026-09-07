import uuid

from datetime import datetime, timezone
from sqlalchemy import Integer, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.events.models import Event, EventStatus, Sponsor, SponsorStatus
from app.modules.sponsorships.models import (
    SponsorshipCategory,
    SponsorshipInquiry,
    SponsorshipInquiryEvent,
    SponsorshipPackage,
    SponsorshipDeliverable,
    SponsorshipDeliverableStatus,
    SponsorEngagement,
    SponsorEngagementType,
    SponsorLeadStatus,
)
from app.modules.networking.models import NetworkingProfile, NetworkingVisibility


class SponsorshipRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_engagement(self, engagement_id: uuid.UUID):
        return await self.db.scalar(select(SponsorEngagement).where(SponsorEngagement.id == engagement_id))

    async def active_engagement_exists(self, *, sponsor_id, event_id, participant_id, engagement_type):
        return await self.db.scalar(
            select(SponsorEngagement.id).where(
                SponsorEngagement.sponsor_id == sponsor_id,
                SponsorEngagement.event_id == event_id,
                SponsorEngagement.participant_id == participant_id,
                SponsorEngagement.engagement_type == engagement_type,
                SponsorEngagement.lead_status.not_in([SponsorLeadStatus.DISMISSED, SponsorLeadStatus.UNSUBSCRIBED]),
            )
        )

    async def page_engagements(self, *, event_id, sponsor_id, page=1, page_size=25, status=None, engagement_type=None, consent_status=None, search=None):
        filters = [SponsorEngagement.event_id == event_id, SponsorEngagement.sponsor_id == sponsor_id]
        if status is not None:
            filters.append(SponsorEngagement.lead_status == status)
        if engagement_type is not None:
            filters.append(SponsorEngagement.engagement_type == engagement_type)
        if consent_status is not None:
            filters.append(SponsorEngagement.consent_status == consent_status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                SponsorEngagement.participant_id.in_(
                    select(NetworkingProfile.user_id).where(
                        NetworkingProfile.event_id == event_id,
                        NetworkingProfile.visibility == NetworkingVisibility.VISIBLE,
                        (NetworkingProfile.display_name.ilike(term) | NetworkingProfile.organization.ilike(term)),
                    )
                )
            )
        total = await self.db.scalar(select(func.count(SponsorEngagement.id)).where(*filters)) or 0
        rows = await self.db.execute(
            select(SponsorEngagement, NetworkingProfile)
            .outerjoin(
                NetworkingProfile,
                (NetworkingProfile.event_id == event_id)
                & (NetworkingProfile.user_id == SponsorEngagement.participant_id)
                & (NetworkingProfile.visibility == NetworkingVisibility.VISIBLE),
            )
            .where(*filters)
            .order_by(SponsorEngagement.captured_at.desc(), SponsorEngagement.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(rows.all()), int(total)

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

    async def get_sponsor(self, sponsor_id: uuid.UUID) -> Sponsor | None:
        result = await self.db.execute(select(Sponsor).where(Sponsor.id == sponsor_id))
        return result.scalar_one_or_none()

    async def page_sponsors(self, *, event_ids=None, status=None, category=None, search=None, page=1, page_size=25):
        if event_ids is not None and not event_ids:
            return [], 0
        filters = []
        if event_ids is not None:
            filters.append(Sponsor.event_id.in_(event_ids))
        if status is not None:
            filters.append(Sponsor.status == status)
        if category:
            filters.append(Sponsor.category.ilike(f"%{category.strip()}%"))
        if search:
            term = f"%{search.strip()}%"
            filters.append(Sponsor.name.ilike(term) | Sponsor.contact_email.ilike(term))
        total = await self.db.scalar(select(func.count(Sponsor.id)).where(*filters)) or 0
        result = await self.db.execute(select(Sponsor).where(*filters).order_by(Sponsor.created_at.desc(), Sponsor.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), int(total)

    async def list_deliverables(self, sponsor_id: uuid.UUID, *, status=None, search=None):
        filters = [SponsorshipDeliverable.sponsor_id == sponsor_id]
        if status is not None:
            filters.append(SponsorshipDeliverable.status == status)
        if search:
            filters.append(SponsorshipDeliverable.description.ilike(f"%{search.strip()}%"))
        result = await self.db.execute(select(SponsorshipDeliverable).where(*filters).order_by(SponsorshipDeliverable.due_date.asc().nullslast(), SponsorshipDeliverable.id.asc()))
        return list(result.scalars().all())

    async def page_deliverables(self, sponsor_id: uuid.UUID, *, status=None, search=None, page=1, page_size=25):
        filters = [SponsorshipDeliverable.sponsor_id == sponsor_id]
        if status is not None:
            filters.append(SponsorshipDeliverable.status == status)
        if search:
            filters.append(SponsorshipDeliverable.description.ilike(f"%{search.strip()}%"))
        total = await self.db.scalar(select(func.count(SponsorshipDeliverable.id)).where(*filters)) or 0
        result = await self.db.execute(
            select(SponsorshipDeliverable)
            .where(*filters)
            .order_by(SponsorshipDeliverable.due_date.asc().nullslast(), SponsorshipDeliverable.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total)

    async def get_deliverable(self, deliverable_id: uuid.UUID) -> SponsorshipDeliverable | None:
        return await self.db.get(SponsorshipDeliverable, deliverable_id)

    async def metrics(self, event_id: uuid.UUID, *, now: datetime | None = None):
        now = now or datetime.now(timezone.utc)
        sponsor_statuses = [SponsorStatus.CONFIRMED, SponsorStatus.ACTIVE, SponsorStatus.COMPLETED]
        sponsor_count, confirmed_value, paid_value = (await self.db.execute(select(func.count(Sponsor.id), func.coalesce(func.sum(Sponsor.committed_value), 0), func.sum(Sponsor.paid_value)).where(Sponsor.event_id == event_id, Sponsor.status.in_(sponsor_statuses)))).one()
        active = await self.db.scalar(select(func.count(Sponsor.id)).where(Sponsor.event_id == event_id, Sponsor.status == SponsorStatus.ACTIVE)) or 0
        completed = await self.db.scalar(select(func.count(Sponsor.id)).where(Sponsor.event_id == event_id, Sponsor.status == SponsorStatus.COMPLETED)) or 0
        total, done, pending, overdue = (await self.db.execute(select(
            func.count(SponsorshipDeliverable.id),
            func.coalesce(func.sum(func.cast(SponsorshipDeliverable.status == SponsorshipDeliverableStatus.COMPLETED, Integer)), 0),
            func.coalesce(func.sum(func.cast(SponsorshipDeliverable.status.in_([SponsorshipDeliverableStatus.PENDING, SponsorshipDeliverableStatus.IN_PROGRESS]), Integer)), 0),
            func.coalesce(func.sum(func.cast((SponsorshipDeliverable.status.in_([SponsorshipDeliverableStatus.PENDING, SponsorshipDeliverableStatus.IN_PROGRESS])) & (SponsorshipDeliverable.due_date < now), Integer)), 0),
        ).where(SponsorshipDeliverable.event_id == event_id))).one()
        categories = await self.db.execute(select(func.coalesce(Sponsor.category, "Uncategorized"), func.coalesce(func.sum(Sponsor.committed_value), 0), func.count(Sponsor.id)).where(Sponsor.event_id == event_id, Sponsor.status.in_(sponsor_statuses)).group_by(Sponsor.category).order_by(func.coalesce(Sponsor.category, "Uncategorized")))
        return {"total_sponsors": int(sponsor_count), "confirmed_value": confirmed_value, "paid_value": paid_value, "active_sponsorships": int(active), "completed_sponsorships": int(completed), "total_deliverables": int(total), "completed_deliverables": int(done), "pending_deliverables": int(pending), "overdue_deliverables": int(overdue), "categories": list(categories.all())}
