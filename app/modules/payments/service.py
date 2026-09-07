"""
Payment initiation, webhook verification, and refund approval logic.
"""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.audit import write_audit_log
from app.core.concurrency import acquire_advisory_lock
from app.core.concurrency import acquire_event_capacity_lock
from app.integrations.payment_gateway_client import get_payment_gateway_client
from app.modules.config_engine.service import ConfigEngineService
from app.modules.config_engine.registration_state import (
    RegistrationAvailability,
    calculate_registration_availability,
    parse_registration_end_at,
)
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.models import EventStatus
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
from app.modules.payments.models import (
    DiscountType,
    Payment,
    PaymentStatus,
    PaymentWebhookInbox,
    Refund,
    RefundStatus,
    WebhookProcessingStatus,
)
from app.modules.payments.repository import (
    DiscountCodeRepository,
    PaymentRepository,
    PaymentWebhookInboxRepository,
    RefundRepository,
)
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.repository import RegistrationRepository


class PaymentService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        self.gateway = get_payment_gateway_client()
        self.payments = PaymentRepository(db)
        self.refunds = RefundRepository(db)
        self.webhook_inbox = PaymentWebhookInboxRepository(db)
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
        await acquire_advisory_lock(self.db, f"payment_initiation:{registration_id}")
        existing = await self.payments.get_by_registration_id(registration_id)
        if existing and existing.status in {PaymentStatus.INITIATED, PaymentStatus.VERIFIED}:
            raise DuplicatePaymentError("A payment already exists for this registration.")
        if config.fee_amount is None or float(config.fee_amount) <= 0:
            raise InvalidPaymentStateError("This event does not require payment.")
        if registration.status not in {
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.APPROVED,
        }:
            raise InvalidPaymentStateError("Registration is not ready for payment.")

        amount, resolved_code = await self._calculate_amount(
            base_amount=Decimal(config.fee_amount), event_id=event.id, discount_code=discount_code
        )
        order = await asyncio.to_thread(
            self.gateway.create_order,
            amount=int(amount * 100),
            currency=config.currency,
            receipt=str(registration.id),
        )
        if existing is not None:
            payment = existing
            payment.amount = amount
            payment.currency = config.currency
            payment.gateway_provider = self.settings.payment_gateway_provider
            payment.gateway_order_id = order.order_id
            payment.gateway_payment_id = None
            payment.gateway_signature = None
            payment.discount_code = resolved_code
            payment.status = PaymentStatus.INITIATED
            payment.verified_at = None
            payment.captured_at = None
        else:
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

    async def page_payments(self, **filters):
        return await self.payments.page_all(**filters)

    async def handle_webhook(
        self, gateway_order_id: str, gateway_payment_id: str, gateway_signature: str
    ) -> Payment:
        result = await self.db.execute(
            select(Payment).where(Payment.gateway_order_id == gateway_order_id)
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            raise PaymentNotFoundError("Payment not found.")
        if payment.status == PaymentStatus.REFUNDED:
            return payment
        return await self._verify_payment(payment, gateway_payment_id, gateway_signature)

    async def verify_payment_for_actor(
        self,
        gateway_order_id: str,
        gateway_payment_id: str,
        gateway_signature: str,
        actor: User,
    ) -> Payment:
        result = await self.db.execute(
            select(Payment).where(Payment.gateway_order_id == gateway_order_id)
        )
        payment = result.scalar_one_or_none()
        if payment is None or payment.user_id != actor.id:
            raise PaymentVerificationFailedError("Payment does not belong to this account.")
        return await self._verify_payment(payment, gateway_payment_id, gateway_signature)

    async def handle_gateway_webhook(self, body: bytes, signature: str, payload: dict) -> Payment:
        if not self.gateway.verify_webhook_signature(body, signature):
            raise PaymentVerificationFailedError("Webhook signature verification failed.")
        event_name = payload.get("event")
        provider_event_id = payload.get("id") or payload.get("event_id")
        if not provider_event_id or not event_name:
            raise PaymentVerificationFailedError("Webhook is missing provider event identifiers.")
        await acquire_advisory_lock(self.db, f"payment_webhook:{provider_event_id}")
        inbox = await self.webhook_inbox.get_by_event_id(str(provider_event_id))
        if inbox is not None and inbox.processing_status == WebhookProcessingStatus.PROCESSED:
            return await self._payment_for_webhook_payload(payload)
        if inbox is None:
            inbox = await self.webhook_inbox.create(
                provider_event_id=str(provider_event_id),
                provider="razorpay",
                event_type=event_name,
                received_at=datetime.now(timezone.utc),
                payload=payload,
                processing_status=WebhookProcessingStatus.RECEIVED,
            )
            await self.db.commit()
        inbox.processing_status = WebhookProcessingStatus.PROCESSING
        inbox.attempts += 1
        await self.db.commit()
        try:
            payment = await self._process_webhook_payload(payload)
            inbox.processing_status = WebhookProcessingStatus.PROCESSED
            inbox.processed_at = datetime.now(timezone.utc)
            inbox.failure_reason = None
            await self.db.commit()
            return payment
        except Exception as exc:
            await self.db.rollback()
            inbox = await self.webhook_inbox.get_by_event_id(str(provider_event_id))
            if inbox is not None:
                inbox.processing_status = WebhookProcessingStatus.FAILED
                inbox.failure_reason = str(exc)[:1000]
                await self.db.commit()
            raise

    async def _payment_for_webhook_payload(self, payload: dict) -> Payment:
        entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        if not entity:
            entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        payment_id = entity.get("order_id") or entity.get("payment_id")
        result = await self.db.execute(
            select(Payment).where(
                (Payment.gateway_order_id == payment_id) | (Payment.gateway_payment_id == payment_id)
            )
        )
        payment = result.scalar_one_or_none()
        if payment is None:
            raise PaymentNotFoundError("Payment not found.")
        return payment

    async def _process_webhook_payload(self, payload: dict) -> Payment:
        event_name = payload["event"]
        payment_entity = payload.get("payload", {}).get("payment", {}).get("entity", {})
        refund_entity = payload.get("payload", {}).get("refund", {}).get("entity", {})
        if event_name in {"payment.captured", "payment.authorized"}:
            order_id = payment_entity.get("order_id")
            payment_id = payment_entity.get("id")
            if not order_id or not payment_id:
                raise PaymentVerificationFailedError("Webhook is missing payment identifiers.")
            result = await self.db.execute(select(Payment).where(Payment.gateway_order_id == order_id))
            payment = result.scalar_one_or_none()
            if payment is None:
                raise PaymentNotFoundError("Payment not found.")
            if payment.status != PaymentStatus.REFUNDED:
                payment = await self._verify_payment(
                    payment,
                    payment_id,
                    self.gateway.payment_signature(order_id=order_id, payment_id=payment_id),
                    commit=False,
                )
            return payment
        if event_name.startswith("refund."):
            return await self._process_refund_webhook(refund_entity, event_name)
        raise InvalidPaymentStateError("Unsupported payment webhook event.")

    async def _process_refund_webhook(self, entity: dict, event_name: str) -> Payment:
        gateway_refund_id = entity.get("id")
        gateway_payment_id = entity.get("payment_id")
        if not gateway_refund_id or not gateway_payment_id:
            raise PaymentVerificationFailedError("Refund webhook is missing provider identifiers.")
        payment_result = await self.db.execute(
            select(Payment).where(Payment.gateway_payment_id == gateway_payment_id)
        )
        payment = payment_result.scalar_one_or_none()
        if payment is None:
            raise PaymentNotFoundError("Payment not found for refund webhook.")
        refund = await self.refunds.get_by_gateway_refund_id(gateway_refund_id)
        if refund is None:
            refund = await self.refunds.get_latest_for_payment(payment.id)
        if refund is None:
            raise InvalidRefundStateError("Refund webhook does not match a local refund request.")
        provider_amount = entity.get("amount")
        if provider_amount is not None and int(provider_amount) != int(Decimal(refund.amount) * 100):
            refund.reconciliation_error = "Provider refund amount does not match the local refund request."
            raise InvalidRefundStateError(refund.reconciliation_error)
        refund.gateway_refund_id = gateway_refund_id
        if refund.status == RefundStatus.PROCESSED:
            return payment
        if event_name in {"refund.processed"} and entity.get("status") in {None, "processed"}:
            refund.status = RefundStatus.PROCESSED
            refund.processed_at = datetime.now(timezone.utc)
            await self._apply_processed_refund(refund, payment, actor_id=None)
        elif event_name in {"refund.created"} and entity.get("status") in {None, "created", "pending"}:
            refund.status = RefundStatus.PROCESSING
        elif event_name in {"refund.failed", "refund.cancelled"}:
            refund.gateway_refund_id = gateway_refund_id
            refund.status = RefundStatus.FAILED
            refund.failure_reason = entity.get("error_description") or f"Provider event: {event_name}"
            registration = await self.registrations.get_by_id(payment.registration_id)
            if registration is not None and registration.status == RegistrationStatus.REFUND_PENDING:
                registration.status = RegistrationStatus.REFUND_FAILED
        else:
            refund.status = RefundStatus.PROCESSING
        refund.last_reconciled_at = datetime.now(timezone.utc)
        return payment

    async def _apply_processed_refund(
        self, refund: Refund, payment: Payment, actor_id: uuid.UUID | None
    ) -> None:
        """Apply the same terminal refund transition for approval and provider callbacks."""
        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is None:
            raise InvalidPaymentStateError("Registration not found for refund.")
        from app.modules.tickets.models import TicketStatus
        from app.modules.tickets.repository import TicketRepository

        tickets = await TicketRepository(self.db).list_by_registration_id(payment.registration_id)
        payment.status = (
            PaymentStatus.REFUNDED
            if await self._refunded_amount(payment.id) >= Decimal(payment.amount)
            else PaymentStatus.VERIFIED
        )
        if payment.status == PaymentStatus.REFUNDED:
            registration.status = RegistrationStatus.CANCELLED
            registration.cancelled_at = registration.cancelled_at or datetime.now(timezone.utc)
            if actor_id is not None:
                registration.cancelled_by = actor_id
            for ticket in tickets:
                if ticket.status not in {TicketStatus.CANCELLED, TicketStatus.REVOKED}:
                    ticket.status = TicketStatus.CANCELLED
            config = await self.configs.get_configuration(payment.event_id)
            event = await self.events.get_by_id(payment.event_id)
            if event is not None and config is not None and event.status == EventStatus.REGISTRATION_CLOSED:
                registered_count = await self.registrations.count_active_for_event(payment.event_id)
                availability = calculate_registration_availability(
                    event_status=EventStatus.REGISTRATION_OPEN,
                    capacity=config.capacity,
                    registered_count=registered_count,
                    registration_end_at=parse_registration_end_at(config.details),
                )
                if availability in {RegistrationAvailability.OPEN, RegistrationAvailability.LIMITED}:
                    event.status = EventStatus.REGISTRATION_OPEN
            from app.modules.waitlists.service import WaitlistService
            await WaitlistService(self.db).promote_next(payment.event_id, registration.participation_type)
        elif registration.status == RegistrationStatus.REFUND_PENDING:
            registration.status = RegistrationStatus.CONFIRMED

    async def _verify_payment(
        self, payment: Payment, gateway_payment_id: str, gateway_signature: str, *, commit: bool = True
    ) -> Payment:
        await acquire_advisory_lock(self.db, f"payment_verification:{payment.id}")
        await self.db.refresh(payment)
        if payment.status == PaymentStatus.REFUNDED:
            raise InvalidPaymentStateError("A refunded payment cannot confirm a registration.")
        if payment.status == PaymentStatus.VERIFIED:
            return payment
        payment_valid = await asyncio.to_thread(
            self.gateway.verify_payment,
            order_id=payment.gateway_order_id or "",
            payment_id=gateway_payment_id,
            signature=gateway_signature,
            expected_amount=int(Decimal(payment.amount) * 100),
            expected_currency=payment.currency,
        )
        if not payment_valid:
            payment.status = PaymentStatus.FAILED
            payment.reconciliation_status = "failed"
            payment.reconciliation_error = "Payment signature verification failed."
            if commit:
                await self.db.commit()
            raise PaymentVerificationFailedError("Payment signature verification failed.")

        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is None or registration.status in {
            RegistrationStatus.REJECTED,
            RegistrationStatus.CANCELLED,
        }:
            raise InvalidPaymentStateError("This registration is no longer payable.")
        payment.gateway_payment_id = gateway_payment_id
        payment.gateway_signature = gateway_signature
        payment.status = PaymentStatus.VERIFIED
        payment.reconciliation_status = "verified"
        payment.reconciliation_error = None
        payment.verified_at = datetime.now(timezone.utc)
        payment.captured_at = datetime.now(timezone.utc)
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
        if commit:
            await self.db.commit()
            await self.db.refresh(payment)
        return payment

    async def list_webhook_events(self, limit: int = 100) -> list[PaymentWebhookInbox]:
        result = await self.db.execute(
            select(PaymentWebhookInbox)
            .order_by(PaymentWebhookInbox.received_at.desc())
            .limit(max(1, min(limit, 500)))
        )
        return list(result.scalars().all())

    async def reconcile_payment(self, payment_id: uuid.UUID) -> Payment | None:
        await acquire_advisory_lock(self.db, f"payment_reconciliation:{payment_id}")
        payment = await self.payments.get_by_id(payment_id)
        if payment is None:
            return None
        payment.reconciliation_attempts += 1
        payment.last_reconciled_at = datetime.now(timezone.utc)
        try:
            snapshot = await asyncio.to_thread(
                self.gateway.fetch_payment,
                payment_id=payment.gateway_payment_id,
                order_id=payment.gateway_order_id,
            )
            if snapshot is None:
                payment.reconciliation_status = "unknown"
                payment.reconciliation_error = "Provider has not returned a payment state."
            elif snapshot.order_id != payment.gateway_order_id or snapshot.amount != int(Decimal(payment.amount) * 100):
                payment.reconciliation_status = "mismatch"
                payment.reconciliation_error = "Provider payment does not match the local order."
            elif snapshot.status in {"captured", "authorized", "paid"}:
                payment = await self._verify_payment(
                    payment,
                    snapshot.payment_id,
                    self.gateway.payment_signature(
                        order_id=payment.gateway_order_id or "", payment_id=snapshot.payment_id
                    ),
                    commit=False,
                )
                payment.reconciliation_status = "verified"
                payment.reconciliation_error = None
            elif snapshot.status in {"failed", "refunded"}:
                payment.reconciliation_status = snapshot.status
                payment.reconciliation_error = None
                if snapshot.status == "failed":
                    payment.status = PaymentStatus.FAILED
            else:
                payment.reconciliation_status = "pending"
                payment.reconciliation_error = None
            await self.db.commit()
            await self.db.refresh(payment)
            return payment
        except Exception as exc:
            await self.db.rollback()
            payment = await self.payments.get_by_id(payment_id)
            if payment is not None:
                payment.reconciliation_status = "failed"
                payment.reconciliation_error = str(exc)[:1000]
                await self.db.commit()
            raise

    async def reconcile_refund(self, refund_id: uuid.UUID) -> Refund | None:
        await acquire_advisory_lock(self.db, f"refund_reconciliation:{refund_id}")
        refund = await self.refunds.get_by_id(refund_id)
        if refund is None:
            return None
        payment = await self.payments.get_by_id(refund.payment_id)
        if payment is None or not refund.gateway_refund_id:
            return refund
        refund.reconciliation_attempts += 1
        refund.last_reconciled_at = datetime.now(timezone.utc)
        try:
            snapshot = await asyncio.to_thread(
                self.gateway.fetch_refund, refund_id=refund.gateway_refund_id
            )
            if snapshot is None:
                refund.reconciliation_error = "Provider has not returned a refund state."
            elif snapshot.payment_id != payment.gateway_payment_id or snapshot.amount != int(Decimal(refund.amount) * 100):
                refund.reconciliation_error = "Provider refund does not match the local refund request."
            elif snapshot.status in {"processed", "completed"}:
                refund.status = RefundStatus.PROCESSED
                refund.processed_at = refund.processed_at or datetime.now(timezone.utc)
                refund.reconciliation_error = None
                await self._apply_processed_refund(refund, payment, actor_id=None)
            elif snapshot.status in {"failed", "cancelled"}:
                refund.status = RefundStatus.FAILED
                refund.failure_reason = f"Provider refund status: {snapshot.status}"
                refund.reconciliation_error = None
                registration = await self.registrations.get_by_id(payment.registration_id)
                if registration is not None and registration.status == RegistrationStatus.REFUND_PENDING:
                    registration.status = RegistrationStatus.REFUND_FAILED
            await self.db.commit()
            await self.db.refresh(refund)
            return refund
        except Exception as exc:
            await self.db.rollback()
            refund = await self.refunds.get_by_id(refund_id)
            if refund is not None:
                refund.reconciliation_error = str(exc)[:1000]
                await self.db.commit()
            raise

    async def reconcile_stale_payments_once(self, limit: int = 100) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.settings.payment_reconciliation_stale_seconds
        )
        result = await self.db.execute(
            select(Payment.id)
            .where(Payment.status == PaymentStatus.INITIATED, Payment.created_at < cutoff)
            .order_by(Payment.created_at)
            .limit(max(1, min(limit, self.settings.payment_reconciliation_batch_size)))
        )
        payment_ids = [row[0] for row in result.all()]
        count = 0
        for payment_id in payment_ids:
            await self.reconcile_payment(payment_id)
            count += 1
        return count

    async def reconcile_stale_refunds_once(self, limit: int = 100) -> int:
        result = await self.db.execute(
            select(Refund.id)
            .where(Refund.status == RefundStatus.PROCESSING)
            .order_by(Refund.created_at)
            .limit(max(1, min(limit, self.settings.payment_reconciliation_batch_size)))
        )
        count = 0
        for (refund_id,) in result.all():
            await self.reconcile_refund(refund_id)
            count += 1
        return count

    async def retry_failed_webhooks_once(self, limit: int = 100) -> int:
        rows = await self.webhook_inbox.list_failed(limit)
        count = 0
        for inbox in rows:
            await acquire_advisory_lock(self.db, f"payment_webhook:{inbox.provider_event_id}")
            inbox.processing_status = WebhookProcessingStatus.PROCESSING
            inbox.attempts += 1
            inbox.failure_reason = None
            await self.db.commit()
            try:
                await self._process_webhook_payload(inbox.payload)
                inbox.processing_status = WebhookProcessingStatus.PROCESSED
                inbox.processed_at = datetime.now(timezone.utc)
                await self.db.commit()
                count += 1
            except Exception as exc:
                await self.db.rollback()
                inbox = await self.webhook_inbox.get_by_event_id(inbox.provider_event_id)
                if inbox is not None:
                    inbox.processing_status = WebhookProcessingStatus.FAILED
                    inbox.failure_reason = str(exc)[:1000]
                    await self.db.commit()
        return count

    async def list_refunds(self, event_id: uuid.UUID | None = None) -> list[Refund]:
        """
        Closes a real gap: there was previously no way to LIST refund
        requests at all — only create a draft and approve one by ID you
        already somehow knew. This is what the Finance Console's Refunds
        queue actually reads from.
        """
        if event_id is None:
            return await self.refunds.list_all()
        return await self.refunds.list_for_event(event_id)

    async def page_refunds(self, **filters):
        return await self.refunds.page_all(**filters)

    async def _refunded_amount(self, payment_id: uuid.UUID) -> Decimal:
        result = await self.db.execute(
            select(func.coalesce(func.sum(Refund.amount), 0)).where(
                Refund.payment_id == payment_id,
                Refund.status.in_(
                    {
                        RefundStatus.PENDING_ADMIN_APPROVAL,
                        RefundStatus.PROCESSING,
                        RefundStatus.PROCESSED,
                    }
                ),
            )
        )
        return Decimal(result.scalar_one())

    async def request_refund(
        self,
        *,
        payment_id: uuid.UUID,
        actor: User,
        amount: Decimal | None,
        reason: str | None,
        commit: bool = True,
    ) -> Refund:
        await acquire_advisory_lock(self.db, f"refund:{payment_id}")
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
        if await self._refunded_amount(payment.id) + refund_amount > Decimal(payment.amount):
            raise InvalidRefundStateError("Refunds cannot exceed the original payment.")
        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is None:
            raise InvalidPaymentStateError("Registration not found.")
        from app.modules.tickets.models import TicketStatus
        from app.modules.tickets.repository import TicketRepository

        tickets = await TicketRepository(self.db).list_by_registration_id(payment.registration_id)
        if (
            registration.status in {RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}
            or any(ticket.status == TicketStatus.CHECKED_IN for ticket in tickets)
        ) and refund_amount >= Decimal(payment.amount):
            raise InvalidRefundStateError("A checked-in or completed registration cannot be fully refunded.")
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
        if registration.status != RegistrationStatus.CANCELLED:
            registration.status = RegistrationStatus.REFUND_PENDING
        if commit:
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
        await acquire_event_capacity_lock(self.db, payment.event_id)
        await acquire_advisory_lock(self.db, f"refund:{payment.id}")
        await self.db.refresh(payment)
        await self.db.refresh(refund)
        if refund.status != RefundStatus.PENDING_ADMIN_APPROVAL:
            raise InvalidRefundStateError("Refund is not awaiting admin approval.")
        if payment.status != PaymentStatus.VERIFIED:
            raise InvalidPaymentStateError("Only verified payments can be refunded.")
        if payment.gateway_payment_id is None:
            raise InvalidRefundStateError("Verified payment is missing the gateway payment id.")
        registration = await self.registrations.get_by_id(payment.registration_id)
        if registration is None:
            raise InvalidPaymentStateError("Registration not found.")
        from app.modules.tickets.models import TicketStatus
        from app.modules.tickets.repository import TicketRepository

        tickets = await TicketRepository(self.db).list_by_registration_id(payment.registration_id)
        if (
            registration.status in {RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}
            or any(ticket.status == TicketStatus.CHECKED_IN for ticket in tickets)
        ) and Decimal(refund.amount) >= Decimal(payment.amount):
            raise InvalidRefundStateError("A checked-in or completed registration cannot be refunded.")
        refund.status = RefundStatus.PROCESSING
        refund.approved_by = actor.id
        refund.approved_at = datetime.now(timezone.utc)
        try:
            gateway_refund = await asyncio.to_thread(
                self.gateway.initiate_refund,
                payment_id=payment.gateway_payment_id,
                amount=int(Decimal(refund.amount) * 100),
            )
        except Exception as exc:
            refund.status = RefundStatus.FAILED
            refund.failure_reason = str(exc)[:500]
            if registration.status == RegistrationStatus.REFUND_PENDING:
                registration.status = RegistrationStatus.REFUND_FAILED
            await write_audit_log(
                self.db,
                entity_type="refund",
                entity_id=refund.id,
                action="failed",
                actor_user_id=actor.id,
                after_value={"reason": refund.failure_reason},
            )
            await self.db.commit()
            await self.db.refresh(refund)
            return refund
        refund.gateway_refund_id = gateway_refund.refund_id
        refund.status = RefundStatus.PROCESSED
        refund.processed_at = datetime.now(timezone.utc)
        await self._apply_processed_refund(refund, payment, actor_id=actor.id)
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
