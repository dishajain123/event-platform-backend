"""Response contracts for Operations and Finance dashboards."""
import uuid
from decimal import Decimal
from datetime import datetime

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


class AttendanceAccessBreakdownOut(BaseModel):
    access_type: str
    entries: int
    unique_attendees: int


class AttendanceTimeBucketOut(BaseModel):
    bucket: str
    entries: int


class AttendanceParticipantOut(BaseModel):
    registration_id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    participant_name: str | None
    registration_status: str
    access_type: str | None
    attendance_status: str
    first_check_in: datetime | None
    last_check_in: datetime | None
    entry_count: int


class AttendanceParticipantPageOut(BaseModel):
    items: list[AttendanceParticipantOut]
    total: int
    page: int
    page_size: int


class AttendanceHistoryOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    registration_id: uuid.UUID
    registration_status: str
    attended: bool
    check_in_count: int
    last_attended_at: datetime | None


class AttendanceHistoryPageOut(BaseModel):
    items: list[AttendanceHistoryOut]
    total: int
    page: int
    page_size: int


class EventAttendanceReportOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    total_registrations: int
    confirmed_registrations: int
    cancelled_registrations: int
    refund_related_registrations: int
    eligible_registrations: int
    active_tickets: int
    valid_tickets: int
    checked_in_participants: int
    no_shows: int
    attendance_rate_pct: float | None
    capacity: int | None
    capacity_utilization_pct: float | None
    total_entries: int
    reentry_count: int
    first_check_in: datetime | None
    last_check_in: datetime | None
    peak_entry_period: str | None
    peak_entry_count: int
    by_access_type: list[AttendanceAccessBreakdownOut]
    checkins_over_time: list[AttendanceTimeBucketOut]


class AnalyticsPointOut(BaseModel):
    date: str
    count: int


class EventAnalyticsOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    registrations: dict
    capacity: dict
    waitlist: dict
    tickets: dict
    attendance: dict
    feedback: dict
    engagement: dict
    funnel: dict
    breakdowns: dict
    revenue: dict | None = None


class EventAnalyticsTimeSeriesOut(BaseModel):
    event_id: uuid.UUID
    start: datetime
    end: datetime
    registrations: list[AnalyticsPointOut]
    payments: list[AnalyticsPointOut]
    refunds: list[AnalyticsPointOut]
    check_ins: list[AnalyticsPointOut]
    feedback: list[AnalyticsPointOut]
    sponsor_engagements: list[AnalyticsPointOut]
    networking: list[AnalyticsPointOut]


class EventAnalyticsComparisonOut(BaseModel):
    event_id: uuid.UUID
    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    registrations: dict
    attendance: dict
    engagement: dict
    revenue: dict | None = None


class OperationsAlertOut(BaseModel):
    code: str
    severity: str
    title: str
    event_id: uuid.UUID | None = None
    count: int = 0
    target_path: str | None = None


class OperationsEventSummaryOut(BaseModel):
    event_id: uuid.UUID
    event_name: str
    event_status: str
    registration_status: str
    capacity: int | None
    capacity_used: int
    capacity_available: int | None
    capacity_utilization_pct: float | None
    registrations: dict[str, int]
    waitlist: dict[str, int]
    payments: dict[str, int]
    refunds: dict[str, int]
    tickets: dict[str, int]
    feedback_submitted: int
    failed_notifications: int
    reconciliation_attention: int
    open_incidents: int
    critical_incidents: int
    alerts: list[OperationsAlertOut]


class OperationsTotalsOut(BaseModel):
    registrations: dict[str, int]
    waitlist: dict[str, int]
    payments: dict[str, int]
    refunds: dict[str, int]
    tickets: dict[str, int]
    feedback_submitted: int
    failed_notifications: int
    reconciliation_attention: int
    open_incidents: int
    critical_incidents: int


class OperationsIncidentSummaryOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    category: str
    status: str
    severity: str
    created_at: datetime


class OperationsCommandCenterOut(BaseModel):
    generated_at: datetime
    event_id: uuid.UUID | None
    items: list[OperationsEventSummaryOut]
    total: int
    page: int
    page_size: int
    totals: OperationsTotalsOut
    alerts: list[OperationsAlertOut]
    recent_incidents: list[OperationsIncidentSummaryOut]
