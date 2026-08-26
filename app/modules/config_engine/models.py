"""
EventConfiguration and EventFieldSchema — the platform's core promise
made real. Everything that varies per event (fees, eligibility rules,
capacity, form fields) lives here as data, read by a single generic
rule engine in service.py rather than branched on in application code.

`rules` is intentionally a flexible JSON blob rather than dozens of
narrow columns — this is what lets a completely new kind of rule
(something we haven't thought of yet) be added by an Operations Admin
filling out a config screen, not by an engineer adding a column and a
migration. The rule engine only knows the KEYS it currently knows how
to check (min_age, max_age, team_size, required_documents); an unknown
key in the JSON is simply ignored today and can be wired into the
engine later without a schema change.
"""
import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class EventConfiguration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "event_configurations"
    __table_args__ = (UniqueConstraint("event_id", name="uq_event_configuration_event_id"),)

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)

    # e.g. ["individual", "team", "viewer"] — which participation types
    # are even enabled for this event. Nothing else in the system
    # hardcodes this list; it's read from here.
    participation_types: Mapped[list] = mapped_column(JSON, default=list)

    fee_amount: Mapped[float | None] = mapped_column(Numeric(10, 2), default=None)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    capacity: Mapped[int | None] = mapped_column(default=None)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)

    # e.g. {"min_age": 16, "team_size": {"min": 5, "max": 11},
    #       "required_documents": ["aadhaar"]}
    rules: Mapped[dict] = mapped_column(JSON, default=dict)

    # e.g. {"codes": {"EARLYBIRD": {"type": "percentage", "value": 10}}}
    discount_rules: Mapped[dict | None] = mapped_column(JSON, default=None)


class EventFieldSchema(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One row per (event, participation_type). `fields` is the list of
    dynamic form field definitions the mobile app and Console both
    render from — see config_engine/service.py's render_schema().
    """

    __tablename__ = "event_field_schemas"
    __table_args__ = (
        UniqueConstraint("event_id", "participation_type", name="uq_event_field_schema_type"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("events.id"), nullable=False)
    participation_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # e.g. [{"key": "tshirt_size", "label": "T-Shirt Size", "type": "select",
    #        "required": True, "options": ["S", "M", "L", "XL"]}, ...]
    fields: Mapped[list] = mapped_column(JSON, default=list)