"""Response contracts for Operations and Finance dashboards."""
import uuid
from decimal import Decimal

from pydantic import BaseModel


class RegistrationStatusBreakdown(BaseModel):
    status: str
    count: int


class EventOperationsReportOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    total_registrations: int
    active_registrations: int
    registrations_by_status: list[RegistrationStatusBreakdown]
    capacity: int | None
    capacity_used: int
    capacity_utilization_pct: float | None
    total_check_ins: int
    unique_tickets_checked_in: int


class PlatformOperationsReportOut(BaseModel):
    total_events: int
    published_events: int
    total_registrations_across_events: int
    total_check_ins_across_events: int
    events: list[EventOperationsReportOut]


class EventFinancialReportOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    total_revenue: Decimal
    verified_payment_count: int
    pending_payment_count: int
    failed_payment_count: int
    total_refunded: Decimal
    refund_count: int
    net_revenue: Decimal


class PlatformFinancialReportOut(BaseModel):
    total_revenue_across_events: Decimal
    total_refunded_across_events: Decimal
    net_revenue_across_events: Decimal
    events: list[EventFinancialReportOut]


class EventSummaryReportOut(BaseModel):
    """
    The scoped version an Event Manager can see for their own event —
    operational numbers plus a simple revenue-collected figure, but not
    the full financial breakdown (failed payments, refund detail) that
    stays Finance-only per the platform's role permission matrix.
    """

    event_id: uuid.UUID
    event_name: str
    total_registrations: int
    active_registrations: int
    registrations_by_status: list[RegistrationStatusBreakdown]
    capacity: int | None
    capacity_used: int
    capacity_utilization_pct: float | None
    total_check_ins: int
    revenue_collected: Decimal