import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.incidents.models import IncidentSeverity, IncidentStatus


class IncidentCreateIn(BaseModel):
    event_id: uuid.UUID
    category: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=10000)
    severity: IncidentSeverity = IncidentSeverity.MEDIUM
    assigned_user_id: uuid.UUID | None = None


class IncidentUpdateIn(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=80)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=10000)
    severity: IncidentSeverity | None = None
    status: IncidentStatus | None = None
    assigned_user_id: uuid.UUID | None = None
    resolution_notes: str | None = Field(default=None, max_length=10000)


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    reporter_user_id: uuid.UUID
    assigned_user_id: uuid.UUID | None
    category: str
    title: str
    description: str
    status: IncidentStatus
    severity: IncidentSeverity
    resolution_notes: str | None
    acknowledged_at: datetime | None
    in_progress_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    cancelled_at: datetime | None
    escalation_count: int
    created_at: datetime
    updated_at: datetime

