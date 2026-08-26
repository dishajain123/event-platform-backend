import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.tickets.models import CheckIn, Ticket


class TicketRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Ticket:
        ticket = Ticket(**kwargs)
        self.db.add(ticket)
        await self.db.flush()
        return ticket

    async def get_by_id(self, ticket_id: uuid.UUID) -> Ticket | None:
        return await self.db.get(Ticket, ticket_id)

    async def get_by_code(self, ticket_code: str) -> Ticket | None:
        result = await self.db.execute(select(Ticket).where(Ticket.ticket_code == ticket_code))
        return result.scalar_one_or_none()

    async def get_by_registration_id(self, registration_id: uuid.UUID) -> Ticket | None:
        result = await self.db.execute(
            select(Ticket).where(Ticket.registration_id == registration_id)
        )
        return result.scalar_one_or_none()

    async def list_for_user(self, user_id: uuid.UUID) -> list[Ticket]:
        result = await self.db.execute(select(Ticket).where(Ticket.user_id == user_id))
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Ticket]:
        result = await self.db.execute(select(Ticket).where(Ticket.event_id == event_id))
        return list(result.scalars().all())


class CheckInRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> CheckIn:
        check_in = CheckIn(**kwargs)
        self.db.add(check_in)
        await self.db.flush()
        return check_in

    async def get_by_ticket_id(self, ticket_id: uuid.UUID) -> CheckIn | None:
        result = await self.db.execute(select(CheckIn).where(CheckIn.ticket_id == ticket_id))
        return result.scalar_one_or_none()

    async def list_for_event(self, event_id: uuid.UUID, venue_id: uuid.UUID | None = None) -> list[CheckIn]:
        query = select(CheckIn).where(CheckIn.event_id == event_id)
        if venue_id is not None:
            query = query.where(CheckIn.venue_id == venue_id)
        result = await self.db.execute(query)
        return list(result.scalars().all())
