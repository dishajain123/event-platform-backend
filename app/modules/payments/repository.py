import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.payments.models import DiscountCode, Payment, Refund


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

    async def list_all(self) -> list[Refund]:
        result = await self.db.execute(select(Refund))
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
