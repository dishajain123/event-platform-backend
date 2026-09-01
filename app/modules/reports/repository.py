"""
Pure aggregation queries — every method here is a read-only SELECT
across other modules' tables. No business rules live here; this is
purely "what does the data currently say," used by reports/service.py
to shape it into the schemas Console dashboards consume.
"""
import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.config_engine.models import EventConfiguration
from app.modules.events.models import Event, EventStatus
from app.modules.payments.models import Payment, PaymentStatus, Refund, RefundStatus
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES, Registration
from app.modules.tickets.models import CheckIn


class ReportRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_event(self, event_id: uuid.UUID) -> Event | None:
        result = await self.db.execute(
            select(Event)
            .options(
                selectinload(Event.main_category),
                selectinload(Event.sub_category),
                selectinload(Event.organizer),
                selectinload(Event.configuration),
            )
            .where(Event.id == event_id)
        )
        return result.scalar_one_or_none()

    async def list_events(self) -> list[Event]:
        result = await self.db.execute(
            select(Event).options(
                selectinload(Event.main_category),
                selectinload(Event.sub_category),
                selectinload(Event.organizer),
                selectinload(Event.configuration),
            )
        )
        return list(result.scalars().all())

    async def get_event_capacity(self, event_id: uuid.UUID) -> int | None:
        result = await self.db.execute(
            select(EventConfiguration.capacity).where(EventConfiguration.event_id == event_id)
        )
        return result.scalar_one_or_none()

    async def get_registration_counts_by_status(self, event_id: uuid.UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(Registration.status, func.count())
            .where(Registration.event_id == event_id)
            .group_by(Registration.status)
        )
        return {status.value: count for status, count in result.all()}

    async def get_active_registration_count(self, event_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Registration)
            .where(
                Registration.event_id == event_id,
                Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)),
            )
        )
        return int(result.scalar_one())

    async def get_checkin_counts(self, event_id: uuid.UUID) -> tuple[int, int]:
        total_result = await self.db.execute(
            select(func.count()).select_from(CheckIn).where(CheckIn.event_id == event_id)
        )
        unique_result = await self.db.execute(
            select(func.count(func.distinct(CheckIn.ticket_id))).where(CheckIn.event_id == event_id)
        )
        return int(total_result.scalar_one()), int(unique_result.scalar_one())

    async def get_payment_aggregates(self, event_id: uuid.UUID) -> dict:
        verified = await self.db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0), func.count())
            .where(Payment.event_id == event_id, Payment.status == PaymentStatus.VERIFIED)
        )
        verified_sum, verified_count = verified.one()

        pending = await self.db.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.event_id == event_id, Payment.status == PaymentStatus.INITIATED)
        )
        failed = await self.db.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.event_id == event_id, Payment.status == PaymentStatus.FAILED)
        )
        return {
            "verified_sum": Decimal(str(verified_sum)),
            "verified_count": int(verified_count),
            "pending_count": int(pending.scalar_one()),
            "failed_count": int(failed.scalar_one()),
        }

    async def get_refund_aggregates(self, event_id: uuid.UUID) -> dict:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0), func.count())
            .select_from(Refund)
            .join(Payment, Refund.payment_id == Payment.id)
            .where(Payment.event_id == event_id, Refund.status == RefundStatus.PROCESSED)
        )
        refunded_sum, refund_count = result.one()
        return {"refunded_sum": Decimal(str(refunded_sum)), "refund_count": int(refund_count)}
