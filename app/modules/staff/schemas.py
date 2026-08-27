"""Contracts for staff assignments and assignment history."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.rbac.models import RoleName
from app.modules.staff.models import StaffAssignmentStatus


class StaffAssignmentCreateIn(BaseModel):
    invitee_mobile: str
    role_name: RoleName  # drives actual permissions once accepted — must be one of the 4 scoped roles
    role_label: str  # display-only label shown in Console/app UI, independent of role_name
    full_name: str | None = None
    venue_id: uuid.UUID | None = None


class StaffAssignmentReassignIn(BaseModel):
    invitee_mobile: str | None = None
    role_name: RoleName | None = None
    role_label: str | None = None
    full_name: str | None = None
    venue_id: uuid.UUID | None = None


class StaffAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    venue_id: uuid.UUID | None
    user_id: uuid.UUID | None
    invitee_mobile: str
    full_name: str | None
    role_name: RoleName | None
    role_label: str
    status: StaffAssignmentStatus
    invited_by: uuid.UUID
    accepted_by: uuid.UUID | None
    revoked_by: uuid.UUID | None
    accepted_at: datetime | None
    revoked_at: datetime | None
    superseded_by_id: uuid.UUID | None
    linked_role_assignment_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class StaffAssignmentHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    assignment_id: uuid.UUID
    action: str
    actor_user_id: uuid.UUID | None
    before_value: dict | None
    after_value: dict | None
    notes: str | None
    created_at: datetime
    updated_at: datetime