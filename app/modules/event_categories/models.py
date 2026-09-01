"""
MainCategory and SubCategory form the event taxonomy hierarchy.

Events reference these rows by foreign key so the console and future
mobile clients can discover category structure from the backend rather
than hardcoded lists.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import Base, TimestampMixin, UUIDPrimaryKeyMixin, UUIDType


class MainCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "main_categories"
    __table_args__ = (UniqueConstraint("name", name="uq_main_categories_name"),)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    sub_categories: Mapped[list["SubCategory"]] = relationship(
        "SubCategory",
        back_populates="main_category",
        cascade="all, delete-orphan",
    )


class SubCategory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sub_categories"
    __table_args__ = (
        UniqueConstraint("main_category_id", "name", name="uq_sub_categories_main_category_name"),
    )

    main_category_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("main_categories.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    main_category: Mapped["MainCategory"] = relationship("MainCategory", back_populates="sub_categories")
    events: Mapped[list["Event"]] = relationship("Event", back_populates="sub_category")
