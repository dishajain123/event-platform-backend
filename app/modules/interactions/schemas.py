import uuid
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.modules.interactions.models import PollChoiceMode, PollResultVisibility, PollStatus, QuestionStatus


class PollOptionIn(BaseModel):
    label: str = Field(min_length=1, max_length=255)


class PollCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    starts_at: datetime
    ends_at: datetime
    choice_mode: PollChoiceMode = PollChoiceMode.SINGLE
    anonymous: bool = False
    max_selections: int | None = Field(default=None, ge=1, le=50)
    allow_vote_change: bool = False
    result_visibility: PollResultVisibility = PollResultVisibility.AFTER_CLOSE
    options: list[PollOptionIn] = Field(min_length=2, max_length=50)


class PollStatusIn(BaseModel):
    status: PollStatus


class PollOptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    label: str
    sort_order: int


class PollOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    title: str
    description: str | None
    starts_at: datetime
    ends_at: datetime
    choice_mode: PollChoiceMode
    anonymous: bool
    max_selections: int | None
    allow_vote_change: bool
    result_visibility: PollResultVisibility
    status: PollStatus
    options: list[PollOptionOut] = []


class VoteIn(BaseModel):
    option_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class VoteOut(BaseModel):
    poll_id: uuid.UUID
    option_ids: list[uuid.UUID]
    submitted_at: datetime


class PollResultOut(BaseModel):
    option_id: uuid.UUID
    label: str
    votes: int
    percentage: float


class QuestionCreateIn(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    anonymous: bool = False
    display_name: str | None = Field(default=None, max_length=255)


class QuestionModerateIn(BaseModel):
    status: QuestionStatus


class QuestionAnswerIn(BaseModel):
    answer_text: str = Field(min_length=1, max_length=4000)


class QuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    event_id: uuid.UUID
    question: str
    display_name: str | None
    status: QuestionStatus
    answer_text: str | None
    answered_at: datetime | None
    created_at: datetime
    upvotes: int = 0
    user_upvoted: bool = False


class InteractionMetricsOut(BaseModel):
    active_polls: int
    poll_responses: int
    questions_submitted: int
    questions_approved: int
    questions_answered: int
    question_upvotes: int
