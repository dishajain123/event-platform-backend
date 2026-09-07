import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tickets.models import CheckIn, Ticket, TicketTransfer, TicketTransferStatus


class TicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Ticket:
        ticket = Ticket(**kwargs)
        self.db.add(ticket)
        await self.db.flush()
        return ticket

    async def get_by_id(self, ticket_id: uuid.UUID, *, for_update: bool = False) -> Ticket | None:
        if not for_update:
            return await self.db.get(Ticket, ticket_id)
        result = await self.db.execute(select(Ticket).where(Ticket.id == ticket_id).with_for_update())
        return result.scalar_one_or_none()

    async def get_by_code(self, ticket_code: str) -> Ticket | None:
        result = await self.db.execute(select(Ticket).where(Ticket.ticket_code == ticket_code))
        return result.scalar_one_or_none()

    async def get_by_registration_id(self, registration_id: uuid.UUID) -> Ticket | None:
        result = await self.db.execute(
            select(Ticket).where(Ticket.registration_id == registration_id)
        )
        return result.scalar_one_or_none()

    async def list_by_registration_id(self, registration_id: uuid.UUID) -> list[Ticket]:
        result = await self.db.execute(
            select(Ticket).where(Ticket.registration_id == registration_id).order_by(Ticket.created_at, Ticket.id)
        )
        return list(result.scalars().all())

    async def list_by_access_policy(self, event_id: uuid.UUID, access_type: str):
        result = await self.db.execute(select(Ticket).where(Ticket.event_id == event_id, Ticket.access_type == access_type).order_by(Ticket.created_at.desc(), Ticket.id.desc()))
        return list(result.scalars().all())

    async def page_for_event(self, event_id, *, page=1, page_size=25, access_type=None, ticket_status=None, search=None):
        filters = [Ticket.event_id == event_id]
        if access_type:
            filters.append(Ticket.access_type == access_type)
        if ticket_status:
            filters.append(Ticket.status == ticket_status)
        if search:
            filters.append(Ticket.ticket_code.ilike(f"%{search.strip()}%"))
        total = int(await self.db.scalar(select(func.count(Ticket.id)).where(*filters)) or 0)
        result = await self.db.execute(select(Ticket).where(*filters).order_by(Ticket.created_at.desc(), Ticket.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

    async def list_for_user(self, user_id: uuid.UUID) -> list[Ticket]:
        result = await self.db.execute(select(Ticket).where(Ticket.user_id == user_id))
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Ticket]:
        result = await self.db.execute(select(Ticket).where(Ticket.event_id == event_id))
        return list(result.scalars().all())

    async def get_transfer(self, transfer_id: uuid.UUID, *, for_update=False) -> TicketTransfer | None:
        query = select(TicketTransfer).where(TicketTransfer.id == transfer_id)
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def get_pending_transfer(self, ticket_id: uuid.UUID, *, for_update=False) -> TicketTransfer | None:
        query = select(TicketTransfer).where(TicketTransfer.ticket_id == ticket_id, TicketTransfer.status == TicketTransferStatus.PENDING)
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def page_transfers(self, *, event_id=None, recipient_user_id=None, status=None, search=None, page=1, page_size=25):
        filters = []
        if event_id is not None:
            filters.append(TicketTransfer.event_id == event_id)
        if recipient_user_id is not None:
            filters.append(TicketTransfer.to_user_id == recipient_user_id)
        if status is not None:
            filters.append(TicketTransfer.status == status)
        if search:
            term = f"%{search.strip()}%"
            filters.append(
                select(Ticket.id).where(Ticket.id == TicketTransfer.ticket_id, Ticket.ticket_code.ilike(term)).exists()
            )
        base = select(TicketTransfer).where(*filters)
        total = int(await self.db.scalar(select(func.count(TicketTransfer.id)).where(*filters)) or 0)
        result = await self.db.execute(
            base.order_by(TicketTransfer.created_at.desc(), TicketTransfer.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total


class CheckInRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> CheckIn:
        check_in = CheckIn(**kwargs)
        self.db.add(check_in)
        await self.db.flush()
        return check_in

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> CheckIn | None:
        result = await self.db.execute(select(CheckIn).where(CheckIn.ticket_id == ticket_id).order_by(CheckIn.entry_number.desc()))
        return result.scalars().first()

    async def get_by_offline_batch_id(self, offline_batch_id: str) -> CheckIn | None:
        result = await self.db.execute(select(CheckIn).where(CheckIn.offline_batch_id == offline_batch_id))
        return result.scalar_one_or_none()

    async def count_for_ticket(self, ticket_id: uuid.UUID) -> int:
        return int(await self.db.scalar(select(func.count(CheckIn.id)).where(CheckIn.ticket_id == ticket_id)) or 0)

    async def list_for_event(self, event_id: uuid.UUID, venue_id: uuid.UUID | None = None) -> list[CheckIn]:
        query = select(CheckIn).where(CheckIn.event_id == event_id)
        if venue_id is not None:
            query = query.where(CheckIn.venue_id == venue_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def page_for_event(self, event_id: uuid.UUID, venue_id: uuid.UUID | None, *, page: int, page_size: int):
        filters = [CheckIn.event_id == event_id]
        if venue_id is not None:
            filters.append(CheckIn.venue_id == venue_id)
        total = await self.db.scalar(select(func.count(CheckIn.id)).where(*filters)) or 0
        result = await self.db.execute(
            select(CheckIn).where(*filters)
            .order_by(CheckIn.created_at.desc(), CheckIn.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total
