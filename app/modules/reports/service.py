"""
Shapes the raw aggregation queries from repository.py into the
schemas Operations and Finance dashboards consume. No permission
checks live here — those are enforced in router.py, since "can this
caller see platform-wide numbers vs. just their own event" is a
routing concern, not a data-shaping one.
"""
import uuid
from decimal import Decimal
from datetime import datetime, timezone

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
)
from app.modules.events.models import EventStatus
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
            is_full = capacity is not None and capacity > 0 and active_count >= capacity

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
            if event.status == EventStatus.REGISTRATION_OPEN:
                registration_open_events += 1
            if event.status == EventStatus.REGISTRATION_CLOSED:
                registration_closed_events += 1
            if event.start_date > now and event.status not in {EventStatus.ARCHIVED, EventStatus.COMPLETED}:
                upcoming_events += 1
            if is_full:
                events_at_full_capacity += 1

            registration_status = "full" if is_full else ("open" if event.status == EventStatus.REGISTRATION_OPEN else "closed")

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
