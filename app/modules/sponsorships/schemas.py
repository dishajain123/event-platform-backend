import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.pagination import Page
from app.modules.events.models import SponsorStatus
from app.modules.sponsorships.models import (
    SponsorConsentStatus,
    SponsorEngagementType,
    SponsorLeadStatus,
    SponsorshipDeliverableStatus,
    SponsorshipInquiryStatus,
)


class SponsorshipCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    is_active: bool = True
    sort_order: int = 0


class SponsorshipCategoryOut(SponsorshipCategoryIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class SponsorshipPackageIn(BaseModel):
    category_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    benefits: list[str] = Field(default_factory=list)
    minimum_offer: Decimal | None = None
    is_active: bool = True


class SponsorshipPackageOut(SponsorshipPackageIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    category: SponsorshipCategoryOut | None = None
    created_at: datetime
    updated_at: datetime


class SponsorshipInquiryCreateIn(BaseModel):
    company_name: str = Field(min_length=1, max_length=255)
    contact_person: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=5, max_length=32)
    email: str
    business_details: str | None = None
    category_id: uuid.UUID | None = None
    package_id: uuid.UUID | None = None
    event_ids: list[uuid.UUID] = Field(default_factory=list)
    offer_details: str | None = None
    message: str | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("Enter a valid email address.")
        return value.strip().lower()


class SponsorshipInquiryStatusIn(BaseModel):
    status: SponsorshipInquiryStatus


class SponsorshipAssignIn(BaseModel):
    event_id: uuid.UUID
    tier: str | None = None
    category: str | None = None
    description: str | None = None
    offer_details: str | None = None
    benefits: list[str] = Field(default_factory=list)
    website_url: str | None = None
    contact_email: str | None = None
    committed_value: Decimal | None = Field(default=None, ge=0)


class SponsorshipInquiryEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_id: uuid.UUID


class SponsorshipInquiryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    user_id: uuid.UUID
    company_name: str
    contact_person: str
    phone: str
    email: str
    business_details: str | None
    category_id: uuid.UUID | None
    package_id: uuid.UUID | None
    offer_details: str | None
    message: str | None
    status: SponsorshipInquiryStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    event_ids: list[uuid.UUID] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class EventSponsorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    tier: str | None
    logo_url: str | None
    status: SponsorStatus
    category: str | None
    description: str | None
    offer_details: str | None
    benefits: list[str] | None
    website_url: str | None
    contact_email: str | None
    inquiry_id: uuid.UUID | None
    committed_value: Decimal | None
    paid_value: Decimal | None


class SponsorStatusIn(BaseModel):
    status: SponsorStatus


class SponsorFinancialUpdateIn(BaseModel):
    committed_value: Decimal | None = Field(default=None, ge=0)


class SponsorshipDeliverableIn(BaseModel):
    deliverable_type: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1)
    quantity: int | None = Field(default=None, ge=1)
    due_date: datetime | None = None
    evidence: dict | None = None


class SponsorshipDeliverableUpdateIn(BaseModel):
    deliverable_type: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1)
    quantity: int | None = Field(default=None, ge=1)
    due_date: datetime | None = None
    status: SponsorshipDeliverableStatus | None = None
    completion_notes: str | None = None
    evidence: dict | None = None


class SponsorshipDeliverableOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sponsor_id: uuid.UUID
    event_id: uuid.UUID
    deliverable_type: str
    description: str
    quantity: int | None
    due_date: datetime | None
    status: SponsorshipDeliverableStatus
    completed_at: datetime | None
    completion_notes: str | None
    evidence: dict | None
    created_at: datetime
    updated_at: datetime


class SponsorshipDeliverablePage(BaseModel):
    items: list[SponsorshipDeliverableOut]
    total: int
    page: int
    page_size: int


class SponsorshipMetricsOut(BaseModel):
    event_id: uuid.UUID
    total_sponsors: int
    confirmed_value: Decimal
    paid_value: Decimal | None
    active_sponsorships: int
    completed_sponsorships: int
    total_deliverables: int
    completed_deliverables: int
    pending_deliverables: int
    overdue_deliverables: int
    fulfillment_percentage: float | None
    value_by_category: list[dict]


class SponsorSummaryOut(BaseModel):
    sponsor_id: uuid.UUID
    event_id: uuid.UUID
    sponsor_name: str
    category: str | None
    committed_value: Decimal | None
    paid_value: Decimal | None
    total_deliverables: int
    completed_deliverables: int
    pending_deliverables: int
    overdue_deliverables: int
    fulfillment_percentage: float | None


class SponsorEngagementCreateIn(BaseModel):
    sponsor_id: uuid.UUID
    participant_id: uuid.UUID
    engagement_type: SponsorEngagementType
    consent_given: bool = False
    consent_source: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=2000)


class SponsorLeadStatusIn(BaseModel):
    status: SponsorLeadStatus


class SponsorConsentIn(BaseModel):
    consent_given: bool
    consent_source: str | None = Field(default=None, max_length=80)


class SponsorEngagementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    sponsor_id: uuid.UUID
    event_id: uuid.UUID
    participant_id: uuid.UUID
    captured_by: uuid.UUID
    captured_at: datetime
    engagement_type: SponsorEngagementType
    note: str | None
    consent_status: SponsorConsentStatus
    consent_at: datetime | None
    consent_source: str | None
    lead_status: SponsorLeadStatus
    participant_display_name: str | None = None
    participant_organization: str | None = None
    participant_designation: str | None = None


class SponsorEngagementPage(Page[SponsorEngagementOut]):
    pass


class SponsorEngagementMetricsOut(BaseModel):
    event_id: uuid.UUID
    sponsor_id: uuid.UUID
    total_leads: int
    qualified_leads: int
    contacted_leads: int
    converted_leads: int
    dismissed_leads: int
    unsubscribed_leads: int
    total_engagements: int
    unique_participants_engaged: int
    conversion_rate: float
    qualification_rate: float
    by_type: dict[str, int]
    by_date: dict[str, int]
