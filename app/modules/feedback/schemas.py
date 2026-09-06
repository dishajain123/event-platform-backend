"""API contracts for event feedback."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.feedback.models import FeedbackCategory


class FeedbackCategoryOut(BaseModel):
    code: FeedbackCategory
    label: str


class FeedbackCreateIn(BaseModel):
    event_id: uuid.UUID
    category: FeedbackCategory
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackUpdateIn(BaseModel):
    category: FeedbackCategory | None = None
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    event_name: str | None = None
    user_id: uuid.UUID
    user_name: str | None = None
    category: FeedbackCategory
    category_label: str
    rating: int
    comment: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackCategorySummary(BaseModel):
    category: FeedbackCategory
    response_count: int
    average_rating: float


class FeedbackSummaryOut(BaseModel):
    response_count: int
    overall_rating: float | None
    category_summaries: list[FeedbackCategorySummary]
    rating_distribution: dict[int, int]
