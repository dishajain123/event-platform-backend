"""Contracts for the generic funnel engine."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.modules.funnels.models import EntryStatus, StageType


class CompetitionStageIn(BaseModel):
    name: str
    stage_type: StageType
    order_index: int
    threshold: int | None = None
    stage_metadata: dict | None = None


class CompetitionStageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    name: str
    stage_type: StageType
    order_index: int
    threshold: int | None
    stage_metadata: dict | None


class EntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    registration_id: uuid.UUID
    current_stage_id: uuid.UUID | None
    status: EntryStatus
    score: Decimal | None
    vote_count: int
    notes: str | None


class StageDecisionIn(BaseModel):
    decision: str
    score: Decimal | None = None
    notes: str | None = None


class VoteIn(BaseModel):
    pass
