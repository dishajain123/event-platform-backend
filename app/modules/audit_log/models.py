"""
AuditLog — an immutable record of every important action. Every other
module calls core.audit.write_audit_log(...) rather than writing here
directly, so the write path is centralized even though the table
"belongs" conceptually to this module.
"""
import uuid

from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "audit_logs"

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUIDType, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, index=True, default=None)
    before_value: Mapped[dict | None] = mapped_column(JSON, default=None)
    after_value: Mapped[dict | None] = mapped_column(JSON, default=None)