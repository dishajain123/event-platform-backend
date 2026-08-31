import uuid

from pydantic import BaseModel, ConfigDict

from app.modules.rbac.models import RoleName


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: RoleName
    description: str | None
    is_scoped: bool


class RoleAssignmentIn(BaseModel):
    user_id: uuid.UUID
    role_name: RoleName
    event_id: uuid.UUID | None = None


class RoleAssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    role_id: uuid.UUID
    event_id: uuid.UUID | None
    status: str


class MyRoleAssignmentOut(BaseModel):
    """
    What the console (or any authenticated client) needs to know about
    its own session's authority: the resolved role NAME (not just a
    role_id it would otherwise have to cross-reference against
    GET /roles itself), and which event it's scoped to, if any.
    """

    role_name: RoleName
    event_id: uuid.UUID | None
    status: str