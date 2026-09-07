import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

from app.modules.certificates.models import CertificateStatus, CertificateType


class CertificateTemplateIn(BaseModel):
    certificate_type: CertificateType
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    issuer_name: str = Field(min_length=1, max_length=255)
    criteria: dict = Field(default_factory=dict)
    mutually_exclusive: bool = False
    is_active: bool = True


class CertificateTemplateOut(CertificateTemplateIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CertificateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    template_id: uuid.UUID
    registration_id: uuid.UUID
    participant_id: uuid.UUID | None
    user_id: uuid.UUID
    certificate_number: str
    status: CertificateStatus
    artifact_url: str | None
    verification_token: str
    created_at: datetime
    updated_at: datetime


class CertificateDetailOut(CertificateOut):
    event_name: str
    certificate_type: str
    title: str
    description: str | None
    issuer_name: str
    criteria: dict


class PublicCertificateOut(BaseModel):
    certificate_number: str
    event_name: str
    certificate_type: str
    title: str
    issuer_name: str
    status: CertificateStatus
    issued_at: datetime


class BadgeDefinitionIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    icon_reference: str | None = None
    criteria: dict = Field(default_factory=dict)
    is_active: bool = True


class BadgeDefinitionOut(BadgeDefinitionIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class BadgeAwardOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    badge_id: uuid.UUID
    registration_id: uuid.UUID
    participant_id: uuid.UUID | None
    user_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime


class BadgePage(BaseModel):
    items: list[BadgeAwardOut]
    total: int
    page: int
    page_size: int


class CertificatePage(BaseModel):
    items: list[CertificateOut]
    total: int
    page: int
    page_size: int


class EligibleParticipantOut(BaseModel):
    registration_id: uuid.UUID
    participant_id: uuid.UUID | None
    user_id: uuid.UUID
    full_name: str
    eligible: bool
    reason: str


class EligibleParticipantPage(BaseModel):
    items: list[EligibleParticipantOut]
    total: int
    page: int
    page_size: int
