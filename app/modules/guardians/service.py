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
        # BUG FIX (found in audit): this used to create a brand-new
        # ChildProfile row FIRST, then check whether the guardian already
        # had a relationship to that same (just-created) child.id — which
        # can never be true, since the id didn't exist a moment earlier.
        # DuplicateGuardianRelationshipError could never actually fire,
        # and nothing stopped a guardian from creating unlimited duplicate
        # child profiles for the same real child (e.g. a double-tap
        # submit, or repeatedly using "add child" for the same kid),
        # fragmenting that child's registration/attendance history across
        # separate profiles. There's no stronger identity signal available
        # for a child who doesn't have their own account, so this checks
        # for an existing profile already linked to this guardian with the
        # same name and date of birth BEFORE creating anything.
        existing_children = await self.guardians.list_children_for_guardian(guardian_user_id)
        if any(
            child.full_name == full_name and child.date_of_birth == date_of_birth
            for child in existing_children
        ):
            raise DuplicateGuardianRelationshipError("This guardian-child relationship already exists.")

        child = await self.guardians.create_child(
            full_name=full_name, date_of_birth=date_of_birth
        )
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