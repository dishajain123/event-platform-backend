import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.event_categories.exceptions import (
    CategoryInUseError,
    CategoryNameConflictError,
    InvalidCategoryRelationshipError,
    MainCategoryNotFoundError,
    SubCategoryNotFoundError,
)
from app.modules.event_categories.models import MainCategory, SubCategory
from app.modules.event_categories.repository import MainCategoryRepository, SubCategoryRepository
from app.modules.events.models import Event


class EventCategoryService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.main_categories = MainCategoryRepository(db)
        self.sub_categories = SubCategoryRepository(db)

    async def _ensure_main_category_name_is_unique(self, name: str, *, exclude_id: uuid.UUID | None = None) -> None:
        stmt = select(MainCategory.id).where(MainCategory.name == name)
        if exclude_id is not None:
            stmt = stmt.where(MainCategory.id != exclude_id)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise CategoryNameConflictError("A main category with that name already exists.")

    async def _ensure_sub_category_name_is_unique(
        self,
        *,
        main_category_id: uuid.UUID,
        name: str,
        exclude_id: uuid.UUID | None = None,
    ) -> None:
        stmt = select(SubCategory.id).where(
            SubCategory.main_category_id == main_category_id,
            SubCategory.name == name,
        )
        if exclude_id is not None:
            stmt = stmt.where(SubCategory.id != exclude_id)
        result = await self.db.execute(stmt)
        if result.scalar_one_or_none() is not None:
            raise CategoryNameConflictError("A sub category with that name already exists under this main category.")

    async def _main_category_in_use(self, main_category_id: uuid.UUID) -> bool:
        sub_count_stmt = select(func.count(SubCategory.id)).where(SubCategory.main_category_id == main_category_id)
        event_count_stmt = select(func.count(Event.id)).where(Event.main_category_id == main_category_id)
        sub_count = (await self.db.execute(sub_count_stmt)).scalar_one()
        event_count = (await self.db.execute(event_count_stmt)).scalar_one()
        return bool(sub_count or event_count)

    async def _sub_category_in_use(self, sub_category_id: uuid.UUID) -> bool:
        stmt = select(func.count(Event.id)).where(Event.sub_category_id == sub_category_id)
        count = (await self.db.execute(stmt)).scalar_one()
        return bool(count)

    async def get_main_category_or_raise(self, main_category_id: uuid.UUID) -> MainCategory:
        category = await self.main_categories.get_by_id(main_category_id, include_sub_categories=True)
        if category is None:
            raise MainCategoryNotFoundError("Main category not found.")
        return category

    async def get_sub_category_or_raise(self, sub_category_id: uuid.UUID) -> SubCategory:
        category = await self.sub_categories.get_by_id(sub_category_id)
        if category is None:
            raise SubCategoryNotFoundError("Sub category not found.")
        return category

    async def list_main_categories(self) -> list[MainCategory]:
        return await self.main_categories.list_all(include_sub_categories=True)

    async def list_sub_categories(self, main_category_id: uuid.UUID | None = None) -> list[SubCategory]:
        if main_category_id is not None:
            await self.get_main_category_or_raise(main_category_id)
        return await self.sub_categories.list_all(main_category_id=main_category_id)

    async def create_main_category(self, actor_user_id: uuid.UUID, **fields) -> MainCategory:
        await self._ensure_main_category_name_is_unique(fields["name"])
        category = await self.main_categories.create(**fields)
        await write_audit_log(
            self.db,
            entity_type="main_category",
            entity_id=category.id,
            action="created",
            actor_user_id=actor_user_id,
            after_value={"name": category.name, "is_active": category.is_active},
        )
        await self.db.commit()
        reloaded = await self.main_categories.get_by_id(category.id, include_sub_categories=True)
        return reloaded or category

    async def update_main_category(self, main_category_id: uuid.UUID, actor_user_id: uuid.UUID, **fields) -> MainCategory:
        category = await self.get_main_category_or_raise(main_category_id)
        before = {"name": category.name, "description": category.description, "is_active": category.is_active}
        if "name" in fields and fields["name"] is not None:
            await self._ensure_main_category_name_is_unique(fields["name"], exclude_id=category.id)
        for key, value in fields.items():
            if value is not None:
                setattr(category, key, value)
        await write_audit_log(
            self.db,
            entity_type="main_category",
            entity_id=category.id,
            action="updated",
            actor_user_id=actor_user_id,
            before_value=before,
            after_value={k: v for k, v in fields.items() if v is not None},
        )
        await self.db.commit()
        reloaded = await self.main_categories.get_by_id(category.id, include_sub_categories=True)
        return reloaded or category

    async def delete_main_category(self, main_category_id: uuid.UUID, actor_user_id: uuid.UUID) -> None:
        category = await self.get_main_category_or_raise(main_category_id)
        if await self._main_category_in_use(main_category_id):
            raise CategoryInUseError("This main category still has sub categories or events assigned to it.")
        await self.main_categories.delete(category)
        await write_audit_log(
            self.db,
            entity_type="main_category",
            entity_id=main_category_id,
            action="deleted",
            actor_user_id=actor_user_id,
            before_value={"name": category.name},
        )
        await self.db.commit()

    async def create_sub_category(self, actor_user_id: uuid.UUID, **fields) -> SubCategory:
        main_category_id = fields["main_category_id"]
        await self.get_main_category_or_raise(main_category_id)
        await self._ensure_sub_category_name_is_unique(main_category_id=main_category_id, name=fields["name"])
        category = await self.sub_categories.create(**fields)
        await write_audit_log(
            self.db,
            entity_type="sub_category",
            entity_id=category.id,
            action="created",
            actor_user_id=actor_user_id,
            after_value={"name": category.name, "main_category_id": str(category.main_category_id)},
        )
        await self.db.commit()
        await self.db.refresh(category)
        return category

    async def update_sub_category(self, sub_category_id: uuid.UUID, actor_user_id: uuid.UUID, **fields) -> SubCategory:
        category = await self.get_sub_category_or_raise(sub_category_id)
        before = {
            "name": category.name,
            "description": category.description,
            "is_active": category.is_active,
            "main_category_id": str(category.main_category_id),
        }
        new_main_category_id = fields.get("main_category_id", category.main_category_id)
        if new_main_category_id != category.main_category_id:
            await self.get_main_category_or_raise(new_main_category_id)
            if await self._sub_category_in_use(category.id):
                raise InvalidCategoryRelationshipError(
                    "Move the events off this sub category before reassigning it to another main category."
                )
        if "name" in fields and fields["name"] is not None:
            await self._ensure_sub_category_name_is_unique(
                main_category_id=new_main_category_id,
                name=fields["name"],
                exclude_id=category.id,
            )
        for key, value in fields.items():
            if value is not None:
                setattr(category, key, value)
        await write_audit_log(
            self.db,
            entity_type="sub_category",
            entity_id=category.id,
            action="updated",
            actor_user_id=actor_user_id,
            before_value=before,
            after_value={k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in fields.items() if v is not None},
        )
        await self.db.commit()
        await self.db.refresh(category)
        return category

    async def delete_sub_category(self, sub_category_id: uuid.UUID, actor_user_id: uuid.UUID) -> None:
        category = await self.get_sub_category_or_raise(sub_category_id)
        if await self._sub_category_in_use(sub_category_id):
            raise CategoryInUseError("This sub category is already assigned to one or more events.")
        await self.sub_categories.delete(category)
        await write_audit_log(
            self.db,
            entity_type="sub_category",
            entity_id=sub_category_id,
            action="deleted",
            actor_user_id=actor_user_id,
            before_value={"name": category.name},
        )
        await self.db.commit()
