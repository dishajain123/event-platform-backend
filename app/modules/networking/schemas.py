import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.modules.networking.models import ConnectionIntent, ConnectionStatus, NetworkingReportStatus, NetworkingVisibility

class NetworkingConfigIn(BaseModel):
    enabled: bool
    matchmaking_enabled: bool = True
    allowed_participant_types: list[str] | None = None
class NetworkingConfigOut(NetworkingConfigIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
class ProfileIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    organization: str | None = Field(default=None, max_length=255)
    designation: str | None = Field(default=None, max_length=255)
    interests: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=30)
    bio: str | None = Field(default=None, max_length=2000)
    visibility: NetworkingVisibility = NetworkingVisibility.HIDDEN
    share_contact: bool = False
class ProfileOut(ProfileIn):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
class ParticipantOut(ProfileOut):
    score: int | None = None
    explanation: list[str] = []
class ConnectionCreateIn(BaseModel):
    participant_id: uuid.UUID
    intent: ConnectionIntent = ConnectionIntent.CONNECT
class ConnectionActionIn(BaseModel):
    status: ConnectionStatus
class ConnectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    participant_low_id: uuid.UUID
    participant_high_id: uuid.UUID
    requested_by: uuid.UUID
    intent: ConnectionIntent
    status: ConnectionStatus
    created_at: datetime
    responded_at: datetime | None
class ReportIn(BaseModel):
    reported_user_id: uuid.UUID
    reason: str = Field(min_length=1, max_length=2000)
class ReportActionIn(BaseModel):
    status: NetworkingReportStatus
    resolution_notes: str | None = Field(default=None, max_length=2000)
class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    reporter_id: uuid.UUID
    reported_user_id: uuid.UUID
    reason: str
    status: NetworkingReportStatus
    reviewed_by: uuid.UUID | None
    resolution_notes: str | None
    created_at: datetime
class NetworkingMetricsOut(BaseModel):
    opt_in_count: int
    discoverable_count: int
    connection_requests: int
    accepted_connections: int
    rejected_requests: int
    blocked_users: int
    open_reports: int
    recommendations_dismissed: int = 0


class ActivityOut(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    activity_type: str
    title: str
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: str
