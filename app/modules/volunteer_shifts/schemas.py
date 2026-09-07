import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.modules.volunteer_shifts.models import (
    VolunteerAssignmentStatus,
    VolunteerAttendanceStatus,
    VolunteerShiftStatus,
)


class ShiftCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    starts_at: datetime
    ends_at: datetime
    required_count: int = Field(ge=1, le=100000)
    required_role: str | None = Field(default=None, max_length=120)
    status: VolunteerShiftStatus = VolunteerShiftStatus.DRAFT

    @model_validator(mode="after")
    def valid_range(self):
        if self.starts_at >= self.ends_at:
            raise ValueError("starts_at must be before ends_at")
        return self


class ShiftUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    location: str | None = Field(default=None, max_length=255)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    required_count: int | None = Field(default=None, ge=1, le=100000)
    required_role: str | None = Field(default=None, max_length=120)
    status: VolunteerShiftStatus | None = None


class AssignmentStatusIn(BaseModel):
    status: VolunteerAssignmentStatus


class EligibleVolunteerOut(BaseModel):
    user_id: uuid.UUID
    application_id: uuid.UUID
    full_name: str
    preferred_responsibility: str | None


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    required_count: int
    required_role: str | None
    status: VolunteerShiftStatus
    assigned_count: int = 0
    available_count: int = 0
    created_at: datetime
    updated_at: datetime


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    shift_id: uuid.UUID
    user_id: uuid.UUID
    volunteer_application_id: uuid.UUID | None
    status: VolunteerAssignmentStatus
    requested_by: uuid.UUID
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    check_in_at: datetime | None
    check_out_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    shift_id: uuid.UUID
    assignment_id: uuid.UUID
    user_id: uuid.UUID
    status: VolunteerAttendanceStatus
    first_check_in_at: datetime | None
    final_check_out_at: datetime | None
    worked_seconds: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class AssignmentWithAttendanceOut(AssignmentOut):
    attendance: AttendanceOut | None = None


class AssignmentDetailOut(AssignmentOut):
    shift: ShiftOut
    attendance: AttendanceOut | None = None
