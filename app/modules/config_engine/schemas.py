"""Pydantic contracts for event configuration and validation payloads."""
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ValidationErrorItem(BaseModel):
    field: str
    message: str


class ValidationResultOut(BaseModel):
    is_eligible: bool
    errors: list[ValidationErrorItem] = Field(default_factory=list)


class ConfigurableFieldIn(BaseModel):
    key: str
    label: str
    type: str
    required: bool = False
    options: list[str] | None = None


class ConfigurableFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    label: str
    type: str
    required: bool
    options: list[str] | None


class EventConfigurationIn(BaseModel):
    participation_types: list[str] = Field(default_factory=list)
    fee_amount: Decimal | None = None
    currency: str = "INR"
    capacity: int | None = None
    approval_required: bool = False
    details: dict = Field(default_factory=dict)
    rules: dict = Field(default_factory=dict)
    discount_rules: dict | None = None


class EventConfigurationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    participation_types: list[str]
    fee_amount: Decimal | None
    currency: str
    capacity: int | None
    approval_required: bool
    details: dict
    rules: dict
    discount_rules: dict | None


class EventFieldSchemaIn(BaseModel):
    participation_type: str
    fields: list[ConfigurableFieldIn] = Field(default_factory=list)


class EventFieldSchemaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_id: uuid.UUID
    participation_type: str
    fields: list[dict]


class ValidateRegistrationIn(BaseModel):
    participation_type: str
    date_of_birth: date | None = None
    team_member_count: int | None = None
    documents_provided: list[str] = Field(default_factory=list)
    answers: dict = Field(default_factory=dict)
