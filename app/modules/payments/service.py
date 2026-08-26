"""
Payment initiation, webhook verification, and refund approval logic.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import write_audit_log
from app.integrations.payment_gateway_client import get_payment_gateway_client
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.payments.exceptions import (
    DiscountCodeNotFoundError,
    DuplicatePaymentError,
    InvalidPaymentStateError,
    InvalidRefundStateError,
    PaymentNotFoundError,
    PaymentVerificationFailedError,
    RefundNotFoundError,
)
from app.modules.payments.models import DiscountType, Payment, PaymentStatus, Refund, RefundStatus
from app.modules.payments.repository import DiscountCodeRepository, PaymentRepository, RefundRepository
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.gateway = get_payment_gateway_client()
        self.payments = PaymentRepository(db)
        self.refunds = RefundRepository(db)
        self.discount_codes = DiscountCodeRepository(db)
        self.registrations = RegistrationRepository(db)
        self.events = EventRepository(db)
        self.configs = ConfigEngineService(db)

    async def _get_registration_event_config(self, registration_id: uuid.UUID):
        registration = await self.registrations.get_by_id(registration_id)
        if registration is None:
            raise InvalidPaymentStateError("Registration not found.")
        event = await self.events.get_by_id(registration.event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        config = await self.configs.get_configuration(event.id)
        if config is None:
            raise InvalidPaymentStateError("Event configuration is missing.")
        return registration, event, config

    async def _calculate_amount(
        self, *, base_amount: Decimal, event_id: uuid.UUID, discount_code: str | None
    ) -> tuple[Decimal, str | None]:
        if discount_code is None:
            return base_amount, None

        discount = await self.discount_codes.get_by_code(discount_code, event_id)
        if discount is None or not discount.is_active:
            raise DiscountCodeNotFoundError("Discount code not found or inactive.")

        if discount.discount_type == DiscountType.PERCENTAGE:
            discounted = base_amount - (base_amount * Decimal(discount.value) / Decimal(100))
        else:
            discounted = base_amount - Decimal(discount.value)
        return max(discounted, Decimal("0.00")), discount.code

    async def initiate_payment(
        self, *, registration_id: uuid.UUID, actor: User, discount_code: str | None = None
    ) -> Payment:
        registration, event, config = await self._get_registration_event_config(registration_id)
        if registration.user_id != actor.id:
            raise InvalidPaymentStateError("You cannot initiate payment for this registration.")
        existing = await self.payments.get_by_registration_id(registration_id)
        if existing and existing.status in {PaymentStatus.INITIATED, PaymentStatus.VERIFIED}:
            raise DuplicatePaymentError("A payment already exists for this registration.")
        if config.fee_amount is None:
            raise InvalidPaymentStateError("This event does not require payment.")

        amount, resolved_code = await self._calculate_amount(
            base_amount=Decimal(config.fee_amount), event_id=event.id, discount_code=discount_code
        )
        order = self.gateway.create_order(
            amount=int(amount * 100), currency=config.currency, receipt=str(registration.id)
        )
        payment = await self.payments.create(
            event_id=event.id,
            registration_id=registration.id,
            user_id=actor.id,
            amount=amount,
            currency=config.currency,
            gateway_provider=self.settings.payment_gateway_provider,
            gateway_order_id=order.order_id,
            discount_code=resolved_code,
            status=PaymentStatus.INITIATED,
        )
        await write_audit_log(
            self.db,
            entity_type="payment",
            entity_id=payment.id,
            action="initiated",
            actor_user_id=actor.id,
            after_value={"amount": str(amount), "gateway_order_id": order.order_id},
        )
        await self.db.commit()
        await self.db.refresh(payment)
        return payment

    async def list_payments(self, event_id: uuid.UUID | None = None) -> list[Payment]:
        payments = await self.payments.list_all()
        if event_id is None:
            return payments
        return [payment for payment in payments if payment.event_id == event_id]

    async def handle_webhook(
        self, gateway_order_id: str, gateway_payment_id: str, gateway_signature: str
    ) -> Payment:
        result = await self.db.execute(
            select(Payment).where(Payment.gateway_order_id == gateway_order_id)
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            raise PaymentNotFoundError("Payment not found.")
        if payment.status == PaymentStatus.VERIFIED:
            registration = await self.registrations.get_by_id(payment.registration_id)
            if registration is not None:
                registration.status = RegistrationStatus.CONFIRMED
            from app.modules.tickets.service import TicketService

            await TicketService(self.db).issue_ticket_for_payment(payment)
            await self.db.commit()
            return payment
        if not self.gateway.verify_payment(
            order_id=gateway_order_id, payment_id=gateway_payment_id, signature=gateway_signature
        ):
            payment.status = PaymentStatus.FAILED
            await self.db.commit()
            raise PaymentVerificationFailedError("Payment signature verification failed.")

        payment.gateway_payment_id = gateway_payment_id
        payment.gateway_signature = gateway_signature
        payment.status = PaymentStatus.VERIFIED
        payment.verified_at = datetime.now(timezone.utc)
        payment.captured_at = datetime.now(timezone.utc)
        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is not None:
            registration.status = RegistrationStatus.CONFIRMED
        from app.modules.tickets.service import TicketService

        await TicketService(self.db).issue_ticket_for_payment(payment)
        await write_audit_log(
            self.db,
            entity_type="payment",
            entity_id=payment.id,
            action="verified",
            actor_user_id=None,
            after_value={"gateway_payment_id": gateway_payment_id},
        )
        await self.db.commit()
        await self.db.refresh(payment)
        return payment

    async def request_refund(
        self, *, payment_id: uuid.UUID, actor: User, amount: Decimal | None, reason: str | None
    ) -> Refund:
        payment = await self.payments.get_by_id(payment_id)
        if payment is None:
            raise PaymentNotFoundError("Payment not found.")
        if payment.status != PaymentStatus.VERIFIED:
            raise InvalidPaymentStateError("Only verified payments can be refunded.")
        refund_amount = amount if amount is not None else Decimal(payment.amount)
        if refund_amount <= 0:
            raise InvalidRefundStateError("Refund amount must be greater than zero.")
        if refund_amount > Decimal(payment.amount):
            raise InvalidRefundStateError("Refund amount cannot exceed the original payment.")
        refund = await self.refunds.create(
            payment_id=payment.id,
            requested_by=actor.id,
            amount=refund_amount,
            reason=reason,
            status=RefundStatus.PENDING_ADMIN_APPROVAL,
        )
        await write_audit_log(
            self.db,
            entity_type="refund",
            entity_id=refund.id,
            action="requested",
            actor_user_id=actor.id,
            after_value={"amount": str(refund_amount)},
        )
        await self.db.commit()
        await self.db.refresh(refund)
        return refund

    async def approve_refund(self, refund_id: uuid.UUID, actor: User, reason: str | None = None) -> Refund:
        refund = await self.refunds.get_by_id(refund_id)
        if refund is None:
            raise RefundNotFoundError("Refund not found.")
        if refund.status != RefundStatus.PENDING_ADMIN_APPROVAL:
            raise InvalidRefundStateError("Refund is not awaiting admin approval.")
        payment = await self.payments.get_by_id(refund.payment_id)
        if payment is None:
            raise PaymentNotFoundError("Payment not found.")
        if payment.gateway_payment_id is None:
            raise InvalidRefundStateError("Verified payment is missing the gateway payment id.")
        refund.status = RefundStatus.PROCESSING
        refund.approved_by = actor.id
        refund.approved_at = datetime.now(timezone.utc)
        gateway_refund = self.gateway.initiate_refund(
            payment_id=payment.gateway_payment_id, amount=int(Decimal(refund.amount) * 100)
        )
        refund.gateway_refund_id = gateway_refund.refund_id
        refund.status = RefundStatus.PROCESSED
        refund.processed_at = datetime.now(timezone.utc)
        payment.status = PaymentStatus.REFUNDED
        await write_audit_log(
            self.db,
            entity_type="refund",
            entity_id=refund.id,
            action="approved",
            actor_user_id=actor.id,
            after_value={"gateway_refund_id": gateway_refund.refund_id, "reason": reason},
        )
        await self.db.commit()
        await self.db.refresh(refund)
        return refund
