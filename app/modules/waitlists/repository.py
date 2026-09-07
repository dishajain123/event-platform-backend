import uuid
from datetime import datetime

from sqlalchemy import distinct, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity.models import User
from app.modules.waitlists.models import ACTIVE_WAITLIST_STATUSES, WaitlistEntry, WaitlistStatus


class WaitlistRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **fields) -> WaitlistEntry:
        entry = WaitlistEntry(**fields)
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get(self, entry_id: uuid.UUID) -> WaitlistEntry | None:
        return await self.db.get(WaitlistEntry, entry_id)

    async def find_active(self, *, event_id, user_id, child_id, team_id, participation_type):
        result = await self.db.execute(select(WaitlistEntry).where(
            WaitlistEntry.event_id == event_id,
            WaitlistEntry.user_id == user_id,
            WaitlistEntry.child_id == child_id,
            WaitlistEntry.team_id == team_id,
            WaitlistEntry.participation_type == participation_type,
            WaitlistEntry.status.in_(ACTIVE_WAITLIST_STATUSES),
        ))
        return result.scalar_one_or_none()

    async def count_waiting_before(self, entry: WaitlistEntry) -> int:
        return await self.db.scalar(select(func.count(WaitlistEntry.id)).where(
            WaitlistEntry.event_id == entry.event_id,
            WaitlistEntry.participation_type == entry.participation_type,
            WaitlistEntry.status == WaitlistStatus.WAITING,
            or_(WaitlistEntry.joined_at < entry.joined_at,
                (WaitlistEntry.joined_at == entry.joined_at) & (WaitlistEntry.id < entry.id)),
        )) or 0

    async def waiting_page(self, *, event_ids, event_id=None, user_id=None, status=None, participation_type=None, search=None, page=1, page_size=25):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(WaitlistEntry.event_id.in_(event_ids))
        if event_id is not None:
            filters.append(WaitlistEntry.event_id == event_id)
        if user_id is not None:
            filters.append(WaitlistEntry.user_id == user_id)
        if status is not None:
            filters.append(WaitlistEntry.status == status)
        if participation_type is not None:
            filters.append(WaitlistEntry.participation_type == participation_type)
        stmt = select(WaitlistEntry)
        count_stmt = select(func.count(WaitlistEntry.id))
        if search:
            term = f"%{search.strip()}%"
            stmt = stmt.join(User, User.id == WaitlistEntry.user_id)
            count_stmt = count_stmt.select_from(WaitlistEntry).join(User, User.id == WaitlistEntry.user_id)
            filters.append(or_(User.name.ilike(term), User.mobile_number.ilike(term)))
        total = await self.db.scalar(count_stmt.where(*filters)) or 0
        result = await self.db.execute(stmt.where(*filters).order_by(WaitlistEntry.joined_at.asc(), WaitlistEntry.id.asc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

    async def next_waiting(self, event_id, participation_type):
        result = await self.db.execute(select(WaitlistEntry).where(
            WaitlistEntry.event_id == event_id,
            WaitlistEntry.participation_type == participation_type,
            WaitlistEntry.status == WaitlistStatus.WAITING,
        ).order_by(WaitlistEntry.joined_at.asc(), WaitlistEntry.id.asc()).limit(1).with_for_update())
        return result.scalar_one_or_none()

    async def expired_promotions(self, now: datetime):
        result = await self.db.execute(select(WaitlistEntry).where(
            WaitlistEntry.status == WaitlistStatus.PROMOTED,
            WaitlistEntry.promotion_expires_at.is_not(None),
            WaitlistEntry.promotion_expires_at <= now,
        ).with_for_update())
        return list(result.scalars().all())

    async def event_ids_with_waiting(self):
        result = await self.db.execute(
            select(distinct(WaitlistEntry.event_id)).where(WaitlistEntry.status == WaitlistStatus.WAITING)
        )
        return list(result.scalars().all())
