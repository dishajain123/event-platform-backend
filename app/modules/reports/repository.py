"""
Pure aggregation queries — every method here is a read-only SELECT
across other modules' tables. No business rules live here; this is
purely "what does the data currently say," used by reports/service.py
to shape it into the schemas Console dashboards consume.
"""
import uuid
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.config_engine.models import EventConfiguration
from app.modules.events.models import Event
from app.modules.payments.models import Payment, PaymentStatus, Refund, RefundStatus
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES, Registration, RegistrationParticipant, RegistrationStatus
from app.modules.identity.models import User
from app.modules.tickets.models import CheckIn
from app.modules.tickets.models import Ticket, TicketStatus
from app.modules.waitlists.models import WaitlistEntry
from app.modules.feedback.models import EventFeedback
from app.modules.notifications.models import Notification, NotificationDeliveryStatus
from app.modules.payments.models import PaymentWebhookInbox
from app.modules.incidents.models import Incident


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

    @staticmethod
    def _scope(column, event_ids):
        return column.in_(event_ids) if event_ids is not None else True

    async def page_dashboard_events(self, *, event_ids, event_id=None, search=None, page=1, page_size=25):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return [], 0
            filters.append(Event.id.in_(event_ids))
        if event_id is not None:
            filters.append(Event.id == event_id)
        if search:
            filters.append(Event.name.ilike(f"%{search.strip()}%"))
        total = await self.db.scalar(select(func.count(Event.id)).where(*filters)) or 0
        result = await self.db.execute(
            select(Event)
            .options(selectinload(Event.configuration))
            .where(*filters)
            .order_by(Event.start_date.asc(), Event.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), int(total)

    async def command_center_aggregates(self, *, event_ids):
        """Fetch all dashboard counters with grouped SQL, never per-event queries."""
        scope = lambda column: self._scope(column, event_ids)
        registrations = await self.db.execute(
            select(Registration.event_id, Registration.status, func.count())
            .where(scope(Registration.event_id)).group_by(Registration.event_id, Registration.status)
        )
        payments = await self.db.execute(
            select(Payment.event_id, Payment.status, func.count())
            .where(scope(Payment.event_id)).group_by(Payment.event_id, Payment.status)
        )
        refunds = await self.db.execute(
            select(Payment.event_id, Refund.status, func.count())
            .join(Payment, Refund.payment_id == Payment.id)
            .where(scope(Payment.event_id)).group_by(Payment.event_id, Refund.status)
        )
        tickets = await self.db.execute(
            select(Ticket.event_id, Ticket.status, func.count())
            .where(scope(Ticket.event_id)).group_by(Ticket.event_id, Ticket.status)
        )
        waitlists = await self.db.execute(
            select(WaitlistEntry.event_id, WaitlistEntry.status, func.count())
            .where(scope(WaitlistEntry.event_id)).group_by(WaitlistEntry.event_id, WaitlistEntry.status)
        )
        feedback = await self.db.execute(
            select(EventFeedback.event_id, func.count())
            .where(scope(EventFeedback.event_id)).group_by(EventFeedback.event_id)
        )
        failed_notifications = await self.db.execute(
            select(Notification.event_id, func.count())
            .where(scope(Notification.event_id), Notification.delivery_status == NotificationDeliveryStatus.FAILED)
            .group_by(Notification.event_id)
        )
        reconciliation = await self.db.execute(
            select(Payment.event_id, func.count())
            .where(scope(Payment.event_id), Payment.reconciliation_status.in_(("failed", "mismatch", "pending", "unknown")))
            .group_by(Payment.event_id)
        )
        incidents = await self.db.execute(
            select(Incident.event_id, Incident.status, Incident.severity, func.count())
            .where(scope(Incident.event_id))
            .group_by(Incident.event_id, Incident.status, Incident.severity)
        )
        failed_webhooks = await self.db.scalar(
            select(func.count()).select_from(PaymentWebhookInbox).where(PaymentWebhookInbox.processing_status == "failed")
        ) or 0

        def grouped(rows):
            output = {}
            for event_id, key, count in rows:
                output.setdefault(event_id, {})[key.value if hasattr(key, "value") else str(key)] = int(count)
            return output

        def simple(rows):
            return {event_id: int(count) for event_id, count in rows}

        incident_counts = {}
        for event_id, status, severity, count in incidents.all():
            bucket = incident_counts.setdefault(event_id, {"open": 0, "critical": 0, "high": 0})
            if status.value in {"open", "acknowledged", "in_progress"}:
                bucket["open"] += int(count)
                if severity.value == "critical":
                    bucket["critical"] += int(count)
                if severity.value == "high":
                    bucket["high"] += int(count)

        return {
            "registrations": grouped(registrations.all()),
            "payments": grouped(payments.all()),
            "refunds": grouped(refunds.all()),
            "tickets": grouped(tickets.all()),
            "waitlists": grouped(waitlists.all()),
            "feedback": simple(feedback.all()),
            "failed_notifications": simple(failed_notifications.all()),
            "reconciliation": simple(reconciliation.all()),
            "incidents": incident_counts,
            "failed_webhooks": int(failed_webhooks),
        }

    async def recent_incidents(self, *, event_ids, limit: int = 20):
        filters = []
        if event_ids is not None:
            if not event_ids:
                return []
            filters.append(Incident.event_id.in_(event_ids))
        result = await self.db.execute(
            select(Incident).where(*filters)
            .order_by(Incident.created_at.desc(), Incident.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    def _attendance_registration_filter():
        return Registration.status.in_((
            RegistrationStatus.CONFIRMED,
            RegistrationStatus.CHECKED_IN,
            RegistrationStatus.REFUND_FAILED,
        ))

    @staticmethod
    def _valid_ticket_filter():
        return Ticket.status.in_((
            TicketStatus.ACTIVE,
            TicketStatus.ISSUED,
            TicketStatus.USED,
            TicketStatus.CHECKED_IN,
        ))

    async def attendance_status_counts(self, event_id: uuid.UUID) -> dict[str, int]:
        result = await self.db.execute(
            select(Registration.status, func.count())
            .where(Registration.event_id == event_id)
            .group_by(Registration.status)
        )
        return {status.value: int(count) for status, count in result.all()}

    async def attendance_ticket_counts(self, event_id: uuid.UUID) -> tuple[int, int]:
        result = await self.db.execute(
            select(
                func.coalesce(func.sum(case((Ticket.status.in_((TicketStatus.ACTIVE, TicketStatus.ISSUED)), 1), else_=0)), 0),
                func.coalesce(func.sum(case((self._valid_ticket_filter(), 1), else_=0)), 0),
            )
            .select_from(Ticket)
            .join(Registration, Registration.id == Ticket.registration_id)
            .where(Ticket.event_id == event_id, self._attendance_registration_filter())
        )
        active, valid = result.one()
        return int(active), int(valid)

    async def attendance_checkin_metrics(self, event_id: uuid.UUID) -> dict:
        eligible = self._attendance_registration_filter()
        valid_ticket = self._valid_ticket_filter()
        base = (
            select(CheckIn)
            .join(Ticket, Ticket.id == CheckIn.ticket_id)
            .join(Registration, Registration.id == Ticket.registration_id)
            .where(CheckIn.event_id == event_id, eligible, valid_ticket)
        ).subquery()
        aggregate = await self.db.execute(
            select(
                func.count(base.c.id),
                func.count(func.distinct(base.c.ticket_id)),
                func.min(base.c.created_at),
                func.max(base.c.created_at),
                func.coalesce(func.sum(case((base.c.entry_number > 1, 1), else_=0)), 0),
            )
        )
        total_entries, unique_tickets, first_checkin, last_checkin, reentries = aggregate.one()
        return {
            "total_entries": int(total_entries),
            "checked_in_participants": int(unique_tickets),
            "first_check_in": first_checkin,
            "last_check_in": last_checkin,
            "reentry_count": int(reentries),
        }

    async def attendance_breakdowns(self, event_id: uuid.UUID) -> tuple[list[tuple], list[tuple]]:
        eligible = self._attendance_registration_filter()
        valid_ticket = self._valid_ticket_filter()
        base = (
            select(CheckIn.id, CheckIn.ticket_id, CheckIn.created_at, Ticket.access_type)
            .join(Ticket, Ticket.id == CheckIn.ticket_id)
            .join(Registration, Registration.id == Ticket.registration_id)
            .where(CheckIn.event_id == event_id, eligible, valid_ticket)
        ).subquery()
        access = await self.db.execute(
            select(base.c.access_type, func.count(), func.count(func.distinct(base.c.ticket_id)))
            .group_by(base.c.access_type)
            .order_by(base.c.access_type.asc())
        )
        # DATE() gives a portable day bucket in PostgreSQL and SQLite and is
        # intentionally deterministic for historical reporting.
        buckets = await self.db.execute(
            select(func.date(base.c.created_at), func.count())
            .group_by(func.date(base.c.created_at))
            .order_by(func.date(base.c.created_at).asc())
        )
        return list(access.all()), list(buckets.all())

    async def page_attendance_participants(self, event_id: uuid.UUID, *, page=1, page_size=25, search=None, attendance=None):
        eligible = self._attendance_registration_filter()
        valid_ticket = self._valid_ticket_filter()
        checkin_count = (
            select(func.count(CheckIn.id))
            .join(Ticket, Ticket.id == CheckIn.ticket_id)
            .where(Ticket.registration_id == Registration.id, CheckIn.event_id == event_id, valid_ticket)
            .correlate(Registration)
            .scalar_subquery()
        )
        first_checkin = (
            select(func.min(CheckIn.created_at))
            .join(Ticket, Ticket.id == CheckIn.ticket_id)
            .where(Ticket.registration_id == Registration.id, CheckIn.event_id == event_id, valid_ticket)
            .correlate(Registration)
            .scalar_subquery()
        )
        last_checkin = (
            select(func.max(CheckIn.created_at))
            .join(Ticket, Ticket.id == CheckIn.ticket_id)
            .where(Ticket.registration_id == Registration.id, CheckIn.event_id == event_id, valid_ticket)
            .correlate(Registration)
            .scalar_subquery()
        )
        participant_name = func.coalesce(func.max(RegistrationParticipant.full_name), User.name, User.mobile_number)
        filters = [Registration.event_id == event_id, eligible]
        if search:
            term = f"%{search.strip()}%"
            filters.append(or_(User.name.ilike(term), User.mobile_number.ilike(term), RegistrationParticipant.full_name.ilike(term)))
        if attendance == "no_show":
            filters.append(checkin_count == 0)
        elif attendance == "attended":
            filters.append(checkin_count > 0)
        total = await self.db.scalar(
            select(func.count(Registration.id))
            .select_from(Registration)
            .join(User, User.id == Registration.user_id)
            .outerjoin(RegistrationParticipant, RegistrationParticipant.registration_id == Registration.id)
            .where(*filters)
            .distinct()
        ) or 0
        result = await self.db.execute(
            select(
                Registration.id, Registration.event_id, Registration.user_id, Registration.status,
                participant_name, Ticket.access_type, checkin_count, first_checkin, last_checkin,
            )
            .select_from(Registration)
            .join(User, User.id == Registration.user_id)
            .outerjoin(RegistrationParticipant, RegistrationParticipant.registration_id == Registration.id)
            .outerjoin(Ticket, and_(Ticket.registration_id == Registration.id, self._valid_ticket_filter()))
            .where(*filters)
            .group_by(Registration.id, Registration.event_id, Registration.user_id, Registration.status, User.name, User.mobile_number, Ticket.access_type)
            .order_by(Registration.created_at.desc(), Registration.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), int(total)

    async def page_attendance_history(self, user_id: uuid.UUID, *, page=1, page_size=25):
        eligible = self._attendance_registration_filter()
        valid_ticket = self._valid_ticket_filter()
        filters = [Registration.user_id == user_id]
        total = await self.db.scalar(
            select(func.count(Registration.id)).where(*filters)
        ) or 0
        result = await self.db.execute(
            select(
                Event.id, Event.name, Registration.id, Registration.status,
                func.count(CheckIn.id), func.max(CheckIn.created_at),
            )
            .select_from(Registration)
            .join(Event, Event.id == Registration.event_id)
            .outerjoin(Ticket, and_(Ticket.registration_id == Registration.id, valid_ticket))
            .outerjoin(CheckIn, and_(CheckIn.ticket_id == Ticket.id, CheckIn.event_id == Registration.event_id))
            .where(*filters)
            .group_by(Event.id, Event.name, Registration.id, Registration.status, Registration.created_at)
            .order_by(Registration.created_at.desc(), Registration.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.all()), int(total)
