"""
Shapes the raw aggregation queries from repository.py into the
schemas Operations and Finance dashboards consume. No permission
checks live here — those are enforced in router.py, since "can this
caller see platform-wide numbers vs. just their own event" is a
routing concern, not a data-shaping one.
"""
import uuid
from decimal import Decimal
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.exceptions import ReportEventNotFoundError
from app.modules.reports.repository import ReportRepository
from app.modules.reports.schemas import (
    EventFinancialReportOut,
    EventOperationsReportOut,
    EventSummaryReportOut,
    PlatformFinancialReportOut,
    PlatformOperationsReportOut,
    RegistrationStatusBreakdown,
    OperationsAlertOut,
    OperationsCommandCenterOut,
    OperationsEventSummaryOut,
    OperationsTotalsOut,
    OperationsIncidentSummaryOut,
    AttendanceAccessBreakdownOut,
    AttendanceParticipantPageOut,
    AttendanceParticipantOut,
    AttendanceHistoryOut,
    AttendanceHistoryPageOut,
    AttendanceTimeBucketOut,
    EventAttendanceReportOut,
)
from app.modules.events.models import EventStatus
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES
from app.modules.registrations.models import RegistrationStatus
from app.modules.payments.models import PaymentStatus, RefundStatus
from app.modules.tickets.models import TicketStatus
from app.modules.waitlists.models import WaitlistStatus
from app.modules.config_engine.registration_state import (
    calculate_registration_availability,
    parse_registration_end_at,
)
from app.modules.events.schemas import (
    EventDashboardItemOut,
    EventManagerOverviewOut,
    EventOperationsOverviewOut,
)


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ReportRepository(db)

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.repo.get_event(event_id)
        if event is None:
            raise ReportEventNotFoundError("Event not found.")
        return event

    async def _build_operations_report(self, event) -> EventOperationsReportOut:
        counts_by_status = await self.repo.get_registration_counts_by_status(event.id)
        active_count = await self.repo.get_active_registration_count(event.id)
        capacity = await self.repo.get_event_capacity(event.id)
        total_checkins, unique_checkins = await self.repo.get_checkin_counts(event.id)

        utilization = None
        if capacity is not None and capacity > 0:
            utilization = round((active_count / capacity) * 100, 1)

        return EventOperationsReportOut(
            event_id=event.id,
            event_name=event.name,
            total_registrations=sum(counts_by_status.values()),
            active_registrations=active_count,
            registrations_by_status=[
                RegistrationStatusBreakdown(status=status, count=count)
                for status, count in sorted(counts_by_status.items())
            ],
            capacity=capacity,
            capacity_used=active_count,
            capacity_utilization_pct=utilization,
            total_check_ins=total_checkins,
            unique_tickets_checked_in=unique_checkins,
        )

    async def get_event_operations_report(self, event_id: uuid.UUID) -> EventOperationsReportOut:
        event = await self._get_event_or_raise(event_id)
        return await self._build_operations_report(event)

    async def get_platform_operations_report(self) -> PlatformOperationsReportOut:
        events = await self.repo.list_events()
        event_reports = [await self._build_operations_report(event) for event in events]
        return PlatformOperationsReportOut(
            total_events=len(events),
            published_events=len([e for e in events if e.status.value != "draft"]),
            total_registrations_across_events=sum(r.total_registrations for r in event_reports),
            total_check_ins_across_events=sum(r.total_check_ins for r in event_reports),
            events=event_reports,
        )

    async def get_platform_operations_overview(self) -> EventOperationsOverviewOut:
        events = await self.repo.list_events()
        now = datetime.now(timezone.utc)

        event_rows: list[EventDashboardItemOut] = []
        manager_totals: dict[uuid.UUID | None, dict[str, object]] = {}

        total_registrations = 0
        active_registrations = 0
        upcoming_events = 0
        active_events = 0
        completed_events = 0
        draft_events = 0
        unpublished_events = 0
        registration_open_events = 0
        registration_closed_events = 0
        events_at_full_capacity = 0

        for event in events:
            counts_by_status = await self.repo.get_registration_counts_by_status(event.id)
            event_total = sum(counts_by_status.values())
            active_count = await self.repo.get_active_registration_count(event.id)
            capacity = await self.repo.get_event_capacity(event.id)
            availability = calculate_registration_availability(
                event_status=event.status,
                capacity=capacity,
                registered_count=active_count,
                registration_end_at=parse_registration_end_at(event.configuration.details if event.configuration else None),
            )
            is_full = availability.value == "full"

            total_registrations += event_total
            active_registrations += active_count

            if event.status in {EventStatus.DRAFT, EventStatus.CONFIGURED}:
                draft_events += 1
                unpublished_events += 1
            elif event.status == EventStatus.ARCHIVED:
                unpublished_events += 0

            if event.status in {EventStatus.REGISTRATION_OPEN, EventStatus.LIVE}:
                active_events += 1
            if event.status == EventStatus.COMPLETED:
                completed_events += 1
            if availability.value in {"open", "limited"}:
                registration_open_events += 1
            if availability.value == "closed":
                registration_closed_events += 1
            if event.start_date > now and event.status not in {EventStatus.ARCHIVED, EventStatus.COMPLETED}:
                upcoming_events += 1
            if is_full:
                events_at_full_capacity += 1

            registration_status = availability.value

            event_rows.append(
                EventDashboardItemOut(
                    event_id=event.id,
                    event_name=event.name,
                    organizer_user_id=event.organizer_user_id,
                    organizer_name=event.organizer.name if event.organizer else None,
                    organizer_mobile_number=event.organizer.mobile_number if event.organizer else None,
                    main_category=event.main_category.name if event.main_category else event.category,
                    sub_category=event.sub_category.name if event.sub_category else None,
                    status=event.status,
                    start_date=event.start_date,
                    end_date=event.end_date,
                    total_registrations=event_total,
                    active_registrations=active_count,
                    capacity=capacity,
                    registration_status=registration_status,
                    is_full=is_full,
                )
            )

            manager_key = event.organizer_user_id
            manager_bucket = manager_totals.setdefault(
                manager_key,
                {
                    "user_id": manager_key,
                    "name": event.organizer.name if event.organizer else None,
                    "mobile_number": event.organizer.mobile_number if event.organizer else None,
                    "total_events": 0,
                    "upcoming_events": 0,
                    "active_events": 0,
                    "completed_events": 0,
                },
            )
            manager_bucket["total_events"] = int(manager_bucket["total_events"]) + 1
            if event.start_date > now and event.status not in {EventStatus.ARCHIVED, EventStatus.COMPLETED}:
                manager_bucket["upcoming_events"] = int(manager_bucket["upcoming_events"]) + 1
            if event.status in {EventStatus.REGISTRATION_OPEN, EventStatus.LIVE}:
                manager_bucket["active_events"] = int(manager_bucket["active_events"]) + 1
            if event.status == EventStatus.COMPLETED:
                manager_bucket["completed_events"] = int(manager_bucket["completed_events"]) + 1

        manager_rows = [
            EventManagerOverviewOut(
                user_id=manager_data["user_id"],
                name=manager_data["name"],
                mobile_number=manager_data["mobile_number"],
                total_events=int(manager_data["total_events"]),
                upcoming_events=int(manager_data["upcoming_events"]),
                active_events=int(manager_data["active_events"]),
                completed_events=int(manager_data["completed_events"]),
            )
            for manager_data in manager_totals.values()
        ]
        manager_rows.sort(key=lambda row: (row.total_events, row.name or ""), reverse=True)

        return EventOperationsOverviewOut(
            total_events=len(events),
            upcoming_events=upcoming_events,
            active_events=active_events,
            completed_events=completed_events,
            draft_events=draft_events,
            unpublished_events=unpublished_events,
            registration_open_events=registration_open_events,
            registration_closed_events=registration_closed_events,
            events_at_full_capacity=events_at_full_capacity,
            total_registrations=total_registrations,
            active_registrations=active_registrations,
            event_manager_overview=manager_rows,
            events=event_rows,
        )

    async def _build_financial_report(self, event) -> EventFinancialReportOut:
        payments = await self.repo.get_payment_aggregates(event.id)
        refunds = await self.repo.get_refund_aggregates(event.id)
        net_revenue = payments["verified_sum"] - refunds["refunded_sum"]

        return EventFinancialReportOut(
            event_id=event.id,
            event_name=event.name,
            total_revenue=payments["verified_sum"],
            verified_payment_count=payments["verified_count"],
            pending_payment_count=payments["pending_count"],
            failed_payment_count=payments["failed_count"],
            total_refunded=refunds["refunded_sum"],
            refund_count=refunds["refund_count"],
            net_revenue=net_revenue,
        )

    async def get_event_financial_report(self, event_id: uuid.UUID) -> EventFinancialReportOut:
        event = await self._get_event_or_raise(event_id)
        return await self._build_financial_report(event)

    async def get_platform_financial_report(self) -> PlatformFinancialReportOut:
        events = await self.repo.list_events()
        event_reports = [await self._build_financial_report(event) for event in events]
        total_revenue = sum((r.total_revenue for r in event_reports), Decimal("0"))
        total_refunded = sum((r.total_refunded for r in event_reports), Decimal("0"))
        return PlatformFinancialReportOut(
            total_revenue_across_events=total_revenue,
            total_refunded_across_events=total_refunded,
            net_revenue_across_events=total_revenue - total_refunded,
            events=event_reports,
        )

    async def get_event_summary_for_manager(self, event_id: uuid.UUID) -> EventSummaryReportOut:
        """The scoped version an Event Manager can see — operational
        numbers plus a simple revenue-collected figure, no refund/failed
        payment detail (that stays Finance-only)."""
        event = await self._get_event_or_raise(event_id)
        ops = await self._build_operations_report(event)
        payments = await self.repo.get_payment_aggregates(event.id)

        return EventSummaryReportOut(
            event_id=ops.event_id,
            event_name=ops.event_name,
            total_registrations=ops.total_registrations,
            active_registrations=ops.active_registrations,
            registrations_by_status=ops.registrations_by_status,
            capacity=ops.capacity,
            capacity_used=ops.capacity_used,
            capacity_utilization_pct=ops.capacity_utilization_pct,
            total_check_ins=ops.total_check_ins,
            revenue_collected=payments["verified_sum"],
        )

    async def get_command_center(self, *, event_ids, event_id=None, search=None, page=1, page_size=25):
        if event_id is not None and event_ids is not None and event_id not in event_ids:
            from app.exceptions import PermissionDeniedError
            raise PermissionDeniedError("You don't have permission to view this event.")
        events, total = await self.repo.page_dashboard_events(
            event_ids=event_ids, event_id=event_id, search=search, page=page, page_size=page_size
        )
        scope_ids = {event_id} if event_id is not None else event_ids
        aggregates = await self.repo.command_center_aggregates(event_ids=scope_ids)
        recent_incidents = await self.repo.recent_incidents(event_ids=scope_ids)
        failed_webhooks = aggregates["failed_webhooks"] if event_id is None and event_ids is None else 0
        alerts = []
        items = []
        now = datetime.now(timezone.utc)

        def counts(bucket, current_id):
            return {key: int(value) for key, value in aggregates[bucket].get(current_id, {}).items()}

        status_defaults = {
            "registrations": [status.value for status in RegistrationStatus],
            "waitlists": [status.value for status in WaitlistStatus],
            "payments": [status.value for status in PaymentStatus],
            "refunds": [status.value for status in RefundStatus],
            "tickets": [status.value for status in TicketStatus],
        }

        def normalized(bucket, current_id):
            target = {key: 0 for key in status_defaults[bucket]}
            target.update(counts(bucket, current_id))
            return target

        for event in events:
            registrations = normalized("registrations", event.id)
            waitlist = normalized("waitlists", event.id)
            payments = normalized("payments", event.id)
            refunds = normalized("refunds", event.id)
            tickets = normalized("tickets", event.id)
            tickets["remaining"] = tickets.get("issued", 0)
            config = event.configuration
            capacity = config.capacity if config else None
            capacity_used = sum(registrations.get(status.value, 0) for status in ACTIVE_REGISTRATION_STATUSES)
            registration_end = parse_registration_end_at(config.details if config else None)
            availability = calculate_registration_availability(
                event_status=event.status, capacity=capacity, registered_count=capacity_used,
                registration_end_at=registration_end, now=now,
            )
            event_alerts = []
            def add(code, severity, title, count=0, target=None):
                alert = OperationsAlertOut(code=code, severity=severity, title=title, event_id=event.id, count=count, target_path=target)
                event_alerts.append(alert)
                alerts.append(alert)
            if availability.value == "full":
                add("capacity_full", "critical", "Event is at full capacity", target=f"/ops/events/{event.id}/registrations")
            elif availability.value == "limited":
                add("capacity_near_full", "warning", "Event has limited capacity remaining", target=f"/ops/events/{event.id}/registrations")
            if registration_end and registration_end > now and registration_end - now <= timedelta(hours=48):
                add("deadline_approaching", "warning", "Registration deadline is approaching", target=f"/ops/events/{event.id}/configure")
            failed_payments = payments.get("failed", 0)
            pending_refunds = sum(refunds.get(status, 0) for status in ("draft", "pending_admin_approval", "approved", "processing"))
            failed_refunds = refunds.get("failed", 0)
            if failed_payments:
                add("payment_failures", "warning", "Payment failures require attention", failed_payments, f"/ops/events/{event.id}/registrations")
            if pending_refunds:
                add("refunds_pending", "warning", "Refunds are awaiting processing", pending_refunds, f"/ops/events/{event.id}/registrations")
            if failed_refunds:
                add("refunds_failed", "critical", "Refund failures require attention", failed_refunds, f"/ops/events/{event.id}/registrations")
            failed_notifications = aggregates["failed_notifications"].get(event.id, 0)
            if failed_notifications:
                add("notification_failures", "warning", "Notification deliveries failed", failed_notifications, "/ops/communication")
            reconciliation_attention = aggregates["reconciliation"].get(event.id, 0)
            if reconciliation_attention:
                add("payment_reconciliation", "critical", "Payment reconciliation requires attention", reconciliation_attention, "/finance/reconciliation")
            incident_counts = aggregates["incidents"].get(event.id, {"open": 0, "critical": 0, "high": 0})
            if incident_counts["critical"]:
                add("critical_incidents", "critical", "Critical incidents require attention", incident_counts["critical"], f"/ops/incidents?event_id={event.id}")
            elif incident_counts["high"]:
                add("high_incidents", "warning", "High-severity incidents require attention", incident_counts["high"], f"/ops/incidents?event_id={event.id}")
            waiting = waitlist.get("waiting", 0)
            if waiting:
                add("waitlist_attention", "info", "Participants are waiting for promotion", waiting, f"/ops/events/{event.id}/waitlist")
            available = capacity - capacity_used if capacity is not None else None
            utilization = round(capacity_used / capacity * 100, 1) if capacity else None
            items.append(OperationsEventSummaryOut(
                event_id=event.id, event_name=event.name, event_status=event.status.value,
                registration_status=availability.value, capacity=capacity, capacity_used=capacity_used,
                capacity_available=available, capacity_utilization_pct=utilization,
                registrations=registrations, waitlist=waitlist, payments=payments, refunds=refunds,
                tickets=tickets, feedback_submitted=aggregates["feedback"].get(event.id, 0),
                failed_notifications=failed_notifications, reconciliation_attention=reconciliation_attention,
                open_incidents=incident_counts["open"], critical_incidents=incident_counts["critical"],
                alerts=event_alerts,
            ))

        def total_bucket(bucket):
            result = {key: 0 for key in status_defaults[bucket]}
            for values in aggregates[bucket].values():
                for key, value in values.items():
                    result[key] = result.get(key, 0) + value
            return result

        totals = OperationsTotalsOut(
            registrations=total_bucket("registrations"), waitlist=total_bucket("waitlists"),
            payments=total_bucket("payments"), refunds=total_bucket("refunds"), tickets=total_bucket("tickets"),
            feedback_submitted=sum(aggregates["feedback"].values()),
            failed_notifications=sum(aggregates["failed_notifications"].values()),
            reconciliation_attention=sum(aggregates["reconciliation"].values()) + failed_webhooks,
            open_incidents=sum(values.get("open", 0) for values in aggregates["incidents"].values()),
            critical_incidents=sum(values.get("critical", 0) for values in aggregates["incidents"].values()),
        )
        if failed_webhooks:
            alerts.append(OperationsAlertOut(code="webhook_failures", severity="critical", title="Payment webhooks failed and need finance reconciliation", count=failed_webhooks))
        return OperationsCommandCenterOut(
            generated_at=now, event_id=event_id, items=items, total=total,
            page=page, page_size=page_size, totals=totals, alerts=alerts,
            recent_incidents=[OperationsIncidentSummaryOut(id=i.id, event_id=i.event_id, title=i.title, category=i.category, status=i.status.value, severity=i.severity.value, created_at=i.created_at) for i in recent_incidents],
        )

    async def get_event_attendance_report(self, event_id: uuid.UUID) -> EventAttendanceReportOut:
        event = await self._get_event_or_raise(event_id)
        status_counts = await self.repo.attendance_status_counts(event_id)
        eligible = sum(status_counts.get(status.value, 0) for status in (
            RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.REFUND_FAILED,
        ))
        active_tickets, valid_tickets = await self.repo.attendance_ticket_counts(event_id)
        checkins = await self.repo.attendance_checkin_metrics(event_id)
        access_rows, time_rows = await self.repo.attendance_breakdowns(event_id)
        capacity = await self.repo.get_event_capacity(event_id)
        checked_in = checkins["checked_in_participants"]
        peak = max(time_rows, key=lambda row: (int(row[1]), str(row[0])), default=None)
        return EventAttendanceReportOut(
            event_id=event.id, event_name=event.name,
            total_registrations=sum(status_counts.values()),
            confirmed_registrations=status_counts.get(RegistrationStatus.CONFIRMED.value, 0),
            cancelled_registrations=status_counts.get(RegistrationStatus.CANCELLED.value, 0),
            refund_related_registrations=sum(status_counts.get(status.value, 0) for status in (RegistrationStatus.REFUND_PENDING, RegistrationStatus.REFUND_FAILED)),
            eligible_registrations=eligible, active_tickets=active_tickets, valid_tickets=valid_tickets,
            checked_in_participants=checked_in, no_shows=max(eligible - checked_in, 0),
            attendance_rate_pct=round(checked_in / eligible * 100, 1) if eligible else None,
            capacity=capacity,
            capacity_utilization_pct=round(eligible / capacity * 100, 1) if capacity else None,
            total_entries=checkins["total_entries"], reentry_count=checkins["reentry_count"],
            first_check_in=checkins["first_check_in"], last_check_in=checkins["last_check_in"],
            peak_entry_period=str(peak[0]) if peak else None, peak_entry_count=int(peak[1]) if peak else 0,
            by_access_type=[AttendanceAccessBreakdownOut(access_type=str(row[0] or "general"), entries=int(row[1]), unique_attendees=int(row[2])) for row in access_rows],
            checkins_over_time=[AttendanceTimeBucketOut(bucket=str(row[0]), entries=int(row[1])) for row in time_rows],
        )

    async def page_event_attendance_participants(self, event_id: uuid.UUID, *, page=1, page_size=25, search=None, attendance=None) -> AttendanceParticipantPageOut:
        rows, total = await self.repo.page_attendance_participants(event_id, page=page, page_size=page_size, search=search, attendance=attendance)
        items = [AttendanceParticipantOut(
            registration_id=registration_id, event_id=row_event_id, user_id=user_id,
            participant_name=name, registration_status=status.value if hasattr(status, "value") else str(status),
            access_type=access_type, attendance_status="attended" if entry_count else "no_show",
            first_check_in=first_checkin, last_check_in=last_checkin, entry_count=int(entry_count),
        ) for registration_id, row_event_id, user_id, status, name, access_type, entry_count, first_checkin, last_checkin in rows]
        return AttendanceParticipantPageOut(items=items, total=total, page=page, page_size=page_size)

    async def page_my_attendance_history(self, user_id: uuid.UUID, *, page=1, page_size=25) -> AttendanceHistoryPageOut:
        rows, total = await self.repo.page_attendance_history(user_id, page=page, page_size=page_size)
        items = [AttendanceHistoryOut(
            event_id=event_id, event_name=event_name, registration_id=registration_id,
            registration_status=status.value if hasattr(status, "value") else str(status),
            attended=check_in_count > 0, check_in_count=int(check_in_count), last_attended_at=last_attended_at,
        ) for event_id, event_name, registration_id, status, check_in_count, last_attended_at in rows]
        return AttendanceHistoryPageOut(items=items, total=total, page=page, page_size=page_size)
