import uuid

from pydantic import BaseModel, ConfigDict


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contact_email: str | None


class OrganizationIn(BaseModel):
    name: str
    contact_email: str | None = None