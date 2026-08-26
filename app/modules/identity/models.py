"""
User and IdentityDocument — every person with an account, and their
optional identity proof (Aadhaar/PAN/DL/Passport/other).
"""
import uuid
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class DocumentType(StrEnum):
    AADHAAR = "aadhaar"
    PAN = "pan"
    DRIVING_LICENCE = "driving_licence"
    PASSPORT = "passport"
    OTHER = "other"


class VerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    mobile_number: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), default=None)
    email: Mapped[str | None] = mapped_column(String(255), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    identity_documents: Mapped[list["IdentityDocument"]] = relationship(
        back_populates="user",
        foreign_keys="IdentityDocument.user_id",
        cascade="all, delete-orphan",
    )
    role_assignments: Mapped[list["RoleAssignment"]] = relationship(
        back_populates="user",
        foreign_keys="RoleAssignment.user_id",
        cascade="all, delete-orphan",
    )


class IdentityDocument(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "identity_documents"

    user_id: Mapped[uuid.UUID] = mapped_column(UUIDType, ForeignKey("users.id"), nullable=False)
    document_type: Mapped[DocumentType] = mapped_column(Enum(DocumentType), nullable=False)
    document_number_encrypted: Mapped[str] = mapped_column(String(512), nullable=False)
    verification_status: Mapped[VerificationStatus] = mapped_column(
        Enum(VerificationStatus), default=VerificationStatus.PENDING
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("users.id"), default=None
    )
    verified_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), default=None)

    user: Mapped["User"] = relationship(back_populates="identity_documents", foreign_keys=[user_id])