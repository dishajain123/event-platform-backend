import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.config_engine.models import EventConfiguration
from app.modules.events.models import Event
from app.modules.feedback.models import EventFeedback
from app.modules.networking.models import ConnectionStatus, NetworkingConnection
from app.modules.payments.models import Payment, PaymentStatus, Refund, RefundStatus
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.sponsorships.models import SponsorEngagement
from app.modules.tickets.models import CheckIn, Ticket, TicketStatus
from app.modules.waitlists.models import WaitlistEntry, WaitlistStatus


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _event(self, event_id):
        event = await self.db.get(Event, event_id)
        if event is None:
            from app.exceptions import NotFoundError
            raise NotFoundError("Event not found.")
        return event

    async def overview(self, event_id: uuid.UUID, *, start: datetime | None = None, end: datetime | None = None, include_financial: bool = False):
        event = await self._event(event_id)
        registration_filters = [Registration.event_id == event_id]
        payment_filters = [Payment.event_id == event_id]
        checkin_filters = [CheckIn.event_id == event_id]
        engagement_filters = [SponsorEngagement.event_id == event_id]
        if start:
            registration_filters.append(Registration.created_at >= start)
            payment_filters.append(Payment.created_at >= start)
            checkin_filters.append(CheckIn.created_at >= start)
            engagement_filters.append(SponsorEngagement.captured_at >= start)
        if end:
            registration_filters.append(Registration.created_at < end)
            payment_filters.append(Payment.created_at < end)
            checkin_filters.append(CheckIn.created_at < end)
            engagement_filters.append(SponsorEngagement.captured_at < end)

        registration_rows = await self.db.execute(select(Registration.status, func.count()).where(*registration_filters).group_by(Registration.status))
        registrations = {status.value: int(count) for status, count in registration_rows.all()}
        total_registrations = sum(registrations.values())
        confirmed = sum(registrations.get(status.value, 0) for status in (RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED))
        cancelled = registrations.get(RegistrationStatus.CANCELLED.value, 0)
        pending = total_registrations - confirmed - cancelled

        payment_rows = await self.db.execute(select(Payment.status, func.count(), func.coalesce(func.sum(Payment.amount), 0)).where(*payment_filters).group_by(Payment.status))
        payment_counts: dict[str, int] = {}
        payment_amounts: dict[str, Decimal] = {}
        for status, count, amount in payment_rows.all():
            payment_counts[status.value] = int(count)
            payment_amounts[status.value] = Decimal(str(amount or 0))
        refund_rows = await self.db.execute(select(Refund.status, func.count(), func.coalesce(func.sum(Refund.amount), 0)).join(Payment, Refund.payment_id == Payment.id).where(Payment.event_id == event_id).group_by(Refund.status))
        refunds = {status.value: {"count": int(count), "amount": Decimal(str(amount or 0))} for status, count, amount in refund_rows.all()}
        processed_refund = refunds.get(RefundStatus.PROCESSED.value, {"count": 0, "amount": Decimal("0" )})
        verified = payment_amounts.get(PaymentStatus.VERIFIED.value, Decimal("0"))
        pending_amount = payment_amounts.get(PaymentStatus.INITIATED.value, Decimal("0"))

        capacity = await self.db.scalar(select(EventConfiguration.capacity).where(EventConfiguration.event_id == event_id))
        active_capacity = await self.db.scalar(select(func.count()).select_from(Registration).where(Registration.event_id == event_id, Registration.status.in_((RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED)))) or 0
        waitlist = await self.db.execute(select(WaitlistEntry.status, func.count()).where(WaitlistEntry.event_id == event_id).group_by(WaitlistEntry.status))
        waitlists = {status.value: int(count) for status, count in waitlist.all()}
        ticket_rows = await self.db.execute(select(Ticket.status, func.count()).where(Ticket.event_id == event_id).group_by(Ticket.status))
        tickets = {status.value: int(count) for status, count in ticket_rows.all()}
        checkins = int(await self.db.scalar(select(func.count()).select_from(CheckIn).where(*checkin_filters)) or 0)
        feedback_count = int(await self.db.scalar(select(func.count()).select_from(EventFeedback).where(EventFeedback.event_id == event_id)) or 0)
        feedback_avg = await self.db.scalar(select(func.avg(EventFeedback.rating)).where(EventFeedback.event_id == event_id))
        networking = int(await self.db.scalar(select(func.count()).select_from(NetworkingConnection).where(NetworkingConnection.event_id == event_id, NetworkingConnection.status == ConnectionStatus.ACCEPTED)) or 0)
        engagement_count = int(await self.db.scalar(select(func.count()).select_from(SponsorEngagement).where(*engagement_filters)) or 0)

        result = {
            "event_id": event.id, "event_name": event.name,
            "registrations": {"total": total_registrations, "confirmed": confirmed, "cancelled": cancelled, "pending": max(pending, 0), "conversion_rate": round(confirmed / total_registrations * 100, 2) if total_registrations else 0.0},
            "capacity": {"total": capacity, "used": int(active_capacity), "available": max(int(capacity) - int(active_capacity), 0) if capacity is not None else None, "utilization_rate": round(active_capacity / capacity * 100, 2) if capacity else None},
            "waitlist": waitlists,
            "tickets": {**tickets, "issuance_rate": round(sum(tickets.values()) / confirmed * 100, 2) if confirmed else 0.0},
            "attendance": {"check_ins": checkins, "attendance_rate": round(checkins / confirmed * 100, 2) if confirmed else 0.0, "no_shows": max(confirmed - checkins, 0)},
            "feedback": {"submitted": feedback_count, "response_rate": round(feedback_count / confirmed * 100, 2) if confirmed else 0.0, "average_rating": float(feedback_avg) if feedback_avg is not None else None},
            "engagement": {"networking_connections": networking, "sponsor_engagements": engagement_count},
            "funnel": {"registered": total_registrations, "confirmed": confirmed, "ticket_issued": sum(tickets.values()), "checked_in": checkins, "feedback": feedback_count},
            "breakdowns": {"registration_status": registrations, "payment_status": payment_counts, "ticket_status": tickets, "waitlist_status": waitlists},
        }
        if include_financial:
            result["revenue"] = {"gross": verified, "successful_payments": payment_counts.get(PaymentStatus.VERIFIED.value, 0), "failed_payments": payment_counts.get(PaymentStatus.FAILED.value, 0), "pending_amount": pending_amount, "refunded_amount": processed_refund["amount"], "refund_count": processed_refund["count"], "net_collected": verified - processed_refund["amount"], "refund_rate": round(processed_refund["count"] / payment_counts.get(PaymentStatus.VERIFIED.value, 1) * 100, 2) if payment_counts.get(PaymentStatus.VERIFIED.value) else 0.0, "average_transaction_value": verified / payment_counts[PaymentStatus.VERIFIED.value] if payment_counts.get(PaymentStatus.VERIFIED.value) else Decimal("0"), "reconciliation_attention": int(await self.db.scalar(select(func.count()).select_from(Payment).where(Payment.event_id == event_id, Payment.reconciliation_status.in_(("failed", "mismatch", "pending", "unknown")))) or 0), "refunds": refunds}
        return result

    async def timeseries(self, event_id: uuid.UUID, *, start: datetime | None = None, end: datetime | None = None):
        await self._event(event_id)
        start = start or datetime.now(timezone.utc) - timedelta(days=30)
        end = end or datetime.now(timezone.utc) + timedelta(seconds=1)
        async def grouped(model, timestamp, filters):
            rows = await self.db.execute(select(func.date(timestamp), func.count()).where(*filters, timestamp >= start, timestamp < end).group_by(func.date(timestamp)).order_by(func.date(timestamp).asc()))
            return [{"date": str(day), "count": int(count)} for day, count in rows.all()]
        refund_rows = await self.db.execute(select(func.date(Refund.created_at), func.count()).join(Payment, Refund.payment_id == Payment.id).where(Payment.event_id == event_id, Refund.status == RefundStatus.PROCESSED, Refund.created_at >= start, Refund.created_at < end).group_by(func.date(Refund.created_at)).order_by(func.date(Refund.created_at).asc()))
        return {"event_id": event_id, "start": start, "end": end, "registrations": await grouped(Registration, Registration.created_at, [Registration.event_id == event_id]), "payments": await grouped(Payment, Payment.created_at, [Payment.event_id == event_id, Payment.status == PaymentStatus.VERIFIED]), "refunds": [{"date": str(day), "count": int(count)} for day, count in refund_rows.all()], "check_ins": await grouped(CheckIn, CheckIn.created_at, [CheckIn.event_id == event_id]), "feedback": await grouped(EventFeedback, EventFeedback.created_at, [EventFeedback.event_id == event_id]), "sponsor_engagements": await grouped(SponsorEngagement, SponsorEngagement.captured_at, [SponsorEngagement.event_id == event_id]), "networking": await grouped(NetworkingConnection, NetworkingConnection.created_at, [NetworkingConnection.event_id == event_id, NetworkingConnection.status == ConnectionStatus.ACCEPTED])}

    async def comparison(self, event_id: uuid.UUID, *, start: datetime | None = None, end: datetime | None = None, include_financial: bool = False):
        end = end or datetime.now(timezone.utc)
        start = start or end - timedelta(days=30)
        duration = end - start
        previous = await self.overview(event_id, start=start - duration, end=start, include_financial=include_financial)
        current = await self.overview(event_id, start=start, end=end, include_financial=include_financial)
        def growth(group: str, key: str):
            current_value = float(current[group].get(key, 0) or 0)
            previous_value = float(previous[group].get(key, 0) or 0)
            return {"current": current_value, "previous": previous_value, "change_pct": round((current_value - previous_value) / previous_value * 100, 2) if previous_value else None}
        result = {"event_id": event_id, "start": start, "end": end, "previous_start": start - duration, "previous_end": start, "registrations": growth("registrations", "total"), "attendance": growth("attendance", "check_ins"), "engagement": growth("engagement", "sponsor_engagements")}
        if include_financial:
            result["revenue"] = growth("revenue", "net_collected")
        return result
