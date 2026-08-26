"""Contracts for guardian-led child profile management."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ChildProfileIn(BaseModel):
    full_name: str
    date_of_birth: date
    relationship_label: str = "guardian"


class ChildProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    date_of_birth: date
    created_at: datetime


class GuardianChildRelationshipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    guardian_user_id: uuid.UUID
    child_id: uuid.UUID
    relationship_label: str
    is_primary: bool
    consent_at: datetime | None
