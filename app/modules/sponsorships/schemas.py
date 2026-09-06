import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.events.models import SponsorStatus
from app.modules.sponsorships.models import SponsorshipInquiryStatus


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
