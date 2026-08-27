"""
Shapes the raw aggregation queries from repository.py into the
schemas Operations and Finance dashboards consume. No permission
checks live here — those are enforced in router.py, since "can this
caller see platform-wide numbers vs. just their own event" is a
routing concern, not a data-shaping one.
"""
import uuid
from decimal import Decimal

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