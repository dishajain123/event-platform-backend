import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.event_categories.models import MainCategory, SubCategory


class MainCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> MainCategory:
        category = MainCategory(**kwargs)
        self.db.add(category)
        await self.db.flush()
        return category

    async def get_by_id(self, category_id: uuid.UUID, *, include_sub_categories: bool = False) -> MainCategory | None:
        stmt = select(MainCategory).where(MainCategory.id == category_id)
        if include_sub_categories:
            stmt = stmt.options(selectinload(MainCategory.sub_categories))
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, name: str) -> MainCategory | None:
        result = await self.db.execute(select(MainCategory).where(MainCategory.name == name))
        return result.scalar_one_or_none()

    async def list_all(self, *, include_sub_categories: bool = False) -> list[MainCategory]:
        stmt = select(MainCategory).order_by(MainCategory.name.asc())
        if include_sub_categories:
            stmt = stmt.options(selectinload(MainCategory.sub_categories))
        result = await self.db.execute(stmt)
        return list(result.scalars().unique().all())

    async def delete(self, category: MainCategory) -> None:
        await self.db.delete(category)


class SubCategoryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> SubCategory:
        category = SubCategory(**kwargs)
        self.db.add(category)
        await self.db.flush()
        return category

    async def get_by_id(self, category_id: uuid.UUID) -> SubCategory | None:
        result = await self.db.execute(select(SubCategory).where(SubCategory.id == category_id))
        return result.scalar_one_or_none()

    async def get_by_main_and_name(self, main_category_id: uuid.UUID, name: str) -> SubCategory | None:
        result = await self.db.execute(
            select(SubCategory).where(
                SubCategory.main_category_id == main_category_id,
                SubCategory.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, main_category_id: uuid.UUID | None = None) -> list[SubCategory]:
        stmt = select(SubCategory).order_by(SubCategory.name.asc())
        if main_category_id is not None:
            stmt = stmt.where(SubCategory.main_category_id == main_category_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, category: SubCategory) -> None:
        await self.db.delete(category)

