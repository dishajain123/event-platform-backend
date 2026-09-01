import uuid

from pydantic import Field
from pydantic import BaseModel, ConfigDict


class MainCategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class SubCategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    main_category_id: uuid.UUID
    name: str


class MainCategoryCreateIn(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True


class MainCategoryUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SubCategoryCreateIn(BaseModel):
    main_category_id: uuid.UUID
    name: str
    description: str | None = None
    is_active: bool = True


class SubCategoryUpdateIn(BaseModel):
    main_category_id: uuid.UUID | None = None
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None


class SubCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    main_category_id: uuid.UUID
    name: str
    description: str | None
    is_active: bool


class MainCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool
    sub_categories: list[SubCategoryOut] = Field(default_factory=list)
