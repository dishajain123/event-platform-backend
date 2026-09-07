import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.waitlists.models import WaitlistStatus


class WaitlistJoinIn(BaseModel):
    participation_type: str = Field(min_length=1, max_length=50)
    child_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None


class WaitlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    child_id: uuid.UUID | None
    team_id: uuid.UUID | None
    participation_type: str
    status: WaitlistStatus
    joined_at: datetime
    position: int | None = None
    promoted_at: datetime | None
    promotion_expires_at: datetime | None
    left_at: datetime | None
    expired_at: datetime | None
    created_at: datetime
    updated_at: datetime


class WaitlistPage(BaseModel):
    items: list[WaitlistOut]
    total: int
    page: int
    page_size: int
