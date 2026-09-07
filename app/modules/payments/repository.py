import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import DiscountCode, Payment, PaymentWebhookInbox, Refund


class PaymentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Payment:
        payment = Payment(**kwargs)
        self.db.add(payment)
        await self.db.flush()
        return payment

    async def get_by_id(self, payment_id: uuid.UUID) -> Payment | None:
        return await self.db.get(Payment, payment_id)

    async def get_by_registration_id(self, registration_id: uuid.UUID) -> Payment | None:
        result = await self.db.execute(
            select(Payment).where(Payment.registration_id == registration_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Payment]:
        result = await self.db.execute(select(Payment))
        return list(result.scalars().all())

    async def page_all(
        self, *, event_id: uuid.UUID | None, page: int, page_size: int,
        search: str | None = None, status=None,
    ) -> tuple[list[Payment], int]:
        filters = []
        if event_id is not None:
            filters.append(Payment.event_id == event_id)
        if search:
            filters.append(
                (Payment.gateway_order_id.ilike(f"%{search}%"))
                | (Payment.gateway_payment_id.ilike(f"%{search}%"))
            )
        if status is not None:
            filters.append(Payment.status == status)
        total = int((await self.db.execute(select(func.count()).select_from(Payment).where(*filters))).scalar_one())
        result = await self.db.execute(
            select(Payment).where(*filters).order_by(Payment.created_at.desc(), Payment.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total


class RefundRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Refund:
        refund = Refund(**kwargs)
        self.db.add(refund)
        await self.db.flush()
        return refund

    async def get_by_id(self, refund_id: uuid.UUID) -> Refund | None:
        return await self.db.get(Refund, refund_id)

    async def get_by_gateway_refund_id(self, gateway_refund_id: str) -> Refund | None:
        result = await self.db.execute(
            select(Refund).where(Refund.gateway_refund_id == gateway_refund_id)
        )
        return result.scalar_one_or_none()

    async def get_latest_for_payment(self, payment_id: uuid.UUID) -> Refund | None:
        result = await self.db.execute(
            select(Refund)
            .where(Refund.payment_id == payment_id)
            .order_by(Refund.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Refund]:
        result = await self.db.execute(select(Refund))
        return list(result.scalars().all())

    async def list_for_event(self, event_id: uuid.UUID) -> list[Refund]:
        """
        Joins through Payment since Refund has no event_id of its own —
        used by the Console's Refunds queue to filter to one event.
        """
        result = await self.db.execute(
            select(Refund).join(Payment, Refund.payment_id == Payment.id).where(Payment.event_id == event_id)
        )
        return list(result.scalars().all())

    async def page_all(
        self, *, event_id: uuid.UUID | None, page: int, page_size: int,
        search: str | None = None, status=None,
    ) -> tuple[list[Refund], int]:
        filters = []
        query = select(Refund).join(Payment, Refund.payment_id == Payment.id)
        count_query = select(func.count()).select_from(Refund).join(Payment, Refund.payment_id == Payment.id)
        if event_id is not None:
            filters.append(Payment.event_id == event_id)
        if search:
            filters.append(Refund.gateway_refund_id.ilike(f"%{search}%"))
        if status is not None:
            filters.append(Refund.status == status)
        total = int((await self.db.execute(count_query.where(*filters))).scalar_one())
        result = await self.db.execute(
            query.where(*filters).order_by(Refund.created_at.desc(), Refund.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total


class PaymentWebhookInboxRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_event_id(self, provider_event_id: str) -> PaymentWebhookInbox | None:
        result = await self.db.execute(
            select(PaymentWebhookInbox).where(
                PaymentWebhookInbox.provider_event_id == provider_event_id
            )
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs) -> PaymentWebhookInbox:
        row = PaymentWebhookInbox(**kwargs)
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_failed(self, limit: int = 100) -> list[PaymentWebhookInbox]:
        result = await self.db.execute(
            select(PaymentWebhookInbox)
            .where(PaymentWebhookInbox.processing_status == "failed")
            .order_by(PaymentWebhookInbox.received_at)
            .limit(limit)
        )
        return list(result.scalars().all())


class DiscountCodeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> DiscountCode:
        discount_code = DiscountCode(**kwargs)
        self.db.add(discount_code)
        await self.db.flush()
        return discount_code

    async def get_by_code(self, code: str, event_id: uuid.UUID | None = None) -> DiscountCode | None:
        query = select(DiscountCode).where(DiscountCode.code == code)
        if event_id is not None:
            query = query.where((DiscountCode.event_id == event_id) | (DiscountCode.event_id.is_(None)))
        result = await self.db.execute(query)
        return result.scalar_one_or_none()
