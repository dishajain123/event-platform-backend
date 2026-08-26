"""Pydantic contracts for the registration lifecycle."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.registrations.models import RegistrationStatus


class RegistrationParticipantIn(BaseModel):
    full_name: str
    date_of_birth: date | None = None
    is_captain: bool = False


class RegistrationParticipantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    registration_id: uuid.UUID
    user_id: uuid.UUID | None
    full_name: str
    date_of_birth: date | None
    is_captain: bool


class RegistrationCreateIn(BaseModel):
    participation_type: str
    child_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    date_of_birth: date | None = None
    documents_provided: list[str] = Field(default_factory=list)
    answers: dict = Field(default_factory=dict)
    participants: list[RegistrationParticipantIn] = Field(default_factory=list)
    team_member_count: int | None = None


class RegistrationDecisionIn(BaseModel):
    reason: str | None = None


class RegistrationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    child_id: uuid.UUID | None
    team_id: uuid.UUID | None
    participation_type: str
    status: RegistrationStatus
    submitted_at: datetime | None
    approved_by: uuid.UUID | None
    rejected_by: uuid.UUID | None
    rejection_reason: str | None
    checked_in_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
    participants: list[RegistrationParticipantOut] = Field(default_factory=list)
