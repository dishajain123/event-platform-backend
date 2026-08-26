"""
Organization — deliberately minimal in Phase 1. Every Event (Phase 2)
gets a nullable organization_id pointing here. For a single-organizer
deployment this can be left as one seeded row and ignored; it exists so
turning this into a true multi-organizer platform later is a data
migration, not a schema redesign.
"""
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(255), default=None)