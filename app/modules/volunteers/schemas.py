import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.volunteers.models import VolunteerApplicationStatus, VolunteerApplicationType


class VolunteerApplicationCreateIn(BaseModel):
    event_id: uuid.UUID
    application_type: VolunteerApplicationType = VolunteerApplicationType.VOLUNTEER
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=5, max_length=32)
    email: str | None = None
    skills_experience: str | None = None
    availability: str | None = None
    preferred_responsibility: str | None = None
    message: str | None = None


class VolunteerApplicationStatusIn(BaseModel):
    status: VolunteerApplicationStatus


class VolunteerApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    application_type: VolunteerApplicationType
    full_name: str
    phone: str
    email: str | None
    skills_experience: str | None
    availability: str | None
    preferred_responsibility: str | None
    message: str | None
    status: VolunteerApplicationStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    activated_staff_assignment_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
