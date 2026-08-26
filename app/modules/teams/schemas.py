"""Team request and response contracts."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.modules.teams.models import InvitationStatus, TeamStatus


class TeamCreateIn(BaseModel):
    name: str
    captain_date_of_birth: date | None = None


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    captain_user_id: uuid.UUID
    name: str
    status: TeamStatus
    captain_date_of_birth: date | None
    submitted_at: datetime | None
    approved_by: uuid.UUID | None
    rejected_by: uuid.UUID | None
    rejection_reason: str | None


class TeamInvitationIn(BaseModel):
    invitee_mobile: str


class TeamInvitationResponseIn(BaseModel):
    accept: bool = True


class TeamInvitationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: uuid.UUID
    invitee_mobile: str
    token: str
    status: InvitationStatus
    responded_at: datetime | None


class TeamMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    team_id: uuid.UUID
    user_id: uuid.UUID | None
    full_name: str
    date_of_birth: date | None
    is_captain: bool
