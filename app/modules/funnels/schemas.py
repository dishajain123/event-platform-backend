"""Contracts for the generic funnel engine."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.modules.funnels.models import CompetitionStatus, EntryStatus, MatchResultStatus, MatchStatus, StageStatus, StageType


class CompetitionStageIn(BaseModel):
    name: str
    stage_type: StageType
    order_index: int
    threshold: int | None = None
    stage_metadata: dict | None = None
    competition_id: uuid.UUID | None = None
    advancement_rules: dict | None = None


class CompetitionIn(BaseModel):
    name: str
    description: str | None = None
    competition_type: str = "custom"
    participation_mode: str = "individual"
    max_participants: int | None = None
    registration_deadline: datetime | None = None


class CompetitionUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    competition_type: str | None = None
    participation_mode: str | None = None
    max_participants: int | None = None
    registration_deadline: datetime | None = None


class CompetitionStatusIn(BaseModel):
    status: CompetitionStatus


class CompetitionStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    competition_id: uuid.UUID | None
    name: str
    stage_type: StageType
    order_index: int
    threshold: int | None
    stage_metadata: dict | None
    status: StageStatus
    advancement_rules: dict | None


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    description: str | None
    competition_type: str
    participation_mode: str
    max_participants: int | None
    registration_deadline: datetime | None
    status: CompetitionStatus
    created_at: datetime
    updated_at: datetime


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    competition_id: uuid.UUID | None
    registration_id: uuid.UUID
    current_stage_id: uuid.UUID | None
    status: EntryStatus
    score: Decimal | None
    vote_count: int
    notes: str | None


class MatchIn(BaseModel):
    stage_id: uuid.UUID
    round_number: int = 1
    match_number: int = 1
    entry_a_id: uuid.UUID | None = None
    entry_b_id: uuid.UUID | None = None
    venue_id: uuid.UUID | None = None
    scheduled_start: datetime
    scheduled_end: datetime
    title: str | None = None


class MatchResultIn(BaseModel):
    score_a: int | None = Field(default=None, ge=0)
    score_b: int | None = Field(default=None, ge=0)
    result_status: MatchResultStatus
    winner_entry_id: uuid.UUID | None = None
    notes: str | None = None


class MatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    competition_id: uuid.UUID
    event_id: uuid.UUID
    stage_id: uuid.UUID
    round_number: int
    match_number: int
    entry_a_id: uuid.UUID | None
    entry_b_id: uuid.UUID | None
    winner_entry_id: uuid.UUID | None
    venue_id: uuid.UUID | None
    schedule_id: uuid.UUID | None
    scheduled_start: datetime
    scheduled_end: datetime
    status: MatchStatus
    result_status: MatchResultStatus
    score_a: int | None
    score_b: int | None
    result_notes: str | None
    recorded_by: uuid.UUID | None
    result_recorded_at: datetime | None
    created_at: datetime
    updated_at: datetime


class StandingsOut(BaseModel):
    entry_id: uuid.UUID
    position: int
    played: int
    wins: int
    losses: int
    draws: int
    points: int
    score_for: int
    score_against: int
    difference: int


class StageDecisionIn(BaseModel):
    decision: str
    score: Decimal | None = None
    notes: str | None = None


class VoteIn(BaseModel):
    pass
