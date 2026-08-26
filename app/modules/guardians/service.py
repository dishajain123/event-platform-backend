"""
Guardian-led child profile and authorization helpers.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.guardians.exceptions import (
    ChildProfileNotFoundError,
    DuplicateGuardianRelationshipError,
    GuardianAuthorizationError,
)
from app.modules.guardians.models import ChildProfile
from app.modules.guardians.repository import GuardianRepository


class GuardianService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.guardians = GuardianRepository(db)

    async def create_child(
        self, guardian_user_id: uuid.UUID, full_name: str, date_of_birth, relationship_label: str
    ) -> ChildProfile:
        child = await self.guardians.create_child(
            full_name=full_name, date_of_birth=date_of_birth
        )
        existing_relationship = await self.guardians.get_relationship(guardian_user_id, child.id)
        if existing_relationship is not None:
            raise DuplicateGuardianRelationshipError("This guardian-child relationship already exists.")
        await self.guardians.add_relationship(
            guardian_user_id=guardian_user_id,
            child_id=child.id,
            relationship_label=relationship_label,
            is_primary=True,
            consent_at=datetime.now(timezone.utc),
        )
        await write_audit_log(
            self.db,
            entity_type="child_profile",
            entity_id=child.id,
            action="created",
            actor_user_id=guardian_user_id,
            after_value={"full_name": full_name, "date_of_birth": str(date_of_birth)},
        )
        await self.db.commit()
        await self.db.refresh(child)
        return child

    async def list_children(self, guardian_user_id: uuid.UUID) -> list[ChildProfile]:
        return await self.guardians.list_children_for_guardian(guardian_user_id)

    async def ensure_guardian_can_register_for_child(
        self, guardian_user_id: uuid.UUID, child_id: uuid.UUID
    ) -> None:
        child = await self.guardians.get_child(child_id)
        if child is None:
            raise ChildProfileNotFoundError("Child profile not found.")
        relationship = await self.guardians.get_relationship(guardian_user_id, child_id)
        if relationship is None:
            raise GuardianAuthorizationError("You are not authorized to register this child.")
