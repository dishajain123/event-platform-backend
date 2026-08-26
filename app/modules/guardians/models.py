"""
Guardian and child profiles for under-age registrations.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class ChildProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "child_profiles"

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date(), nullable=False)

    relationships: Mapped[list["GuardianChildRelationship"]] = relationship(
        back_populates="child", cascade="all, delete-orphan"
    )


class GuardianChildRelationship(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "guardian_child_relationships"
    __table_args__ = (
        UniqueConstraint("guardian_user_id", "child_id", name="uq_guardian_child_relationship"),
    )

    guardian_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id"), nullable=False
    )
    child_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("child_profiles.id"), nullable=False)
    relationship_label: Mapped[str] = mapped_column(String(100), nullable=False)
    is_primary: Mapped[bool] = mapped_column(default=True)
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    child: Mapped["ChildProfile"] = relationship(back_populates="relationships")
