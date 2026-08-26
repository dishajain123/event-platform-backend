"""
Configuration endpoints. GET endpoints are shared (mobile renders the
registration form from them; Console displays current settings from
the same data). PUT endpoints are Console-only, with the scoped
Event Manager exception described in the platform's account model —
an Event Manager can configure their own event, nothing else.
"""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_scoped_role
from app.modules.config_engine.schemas import (
    EventConfigurationIn,
    EventConfigurationOut,
    EventFieldSchemaIn,
    EventFieldSchemaOut,
    ValidateRegistrationIn,
    ValidationResultOut,
)
from app.modules.config_engine.service import ConfigEngineService
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/events/{event_id}", tags=["config_engine"])


def get_config_engine_service(db: AsyncSession = Depends(get_db)) -> ConfigEngineService:
    return ConfigEngineService(db)


# Both the Operations Admin (any event) and a scoped Event Manager (their
# own event only) can reach the configuration write endpoints — this is
# the exact "scoped Console login" behavior described in the platform's
# account model.
_can_configure = require_scoped_role(
    RoleName.EVENT_MANAGER,
    allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
)


@router.get("/configuration", response_model=EventConfigurationOut | None)
async def get_configuration(
    event_id: str,
    current_user: User = Depends(get_current_user),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """Called by: both — mobile uses it to render the registration form."""
    return await service.get_configuration(uuid.UUID(event_id))


@router.put("/configuration", response_model=EventConfigurationOut)
async def upsert_configuration(
    event_id: str,
    payload: EventConfigurationIn,
    current_user: User = Depends(_can_configure),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """Called by: console (Operations Admin, or scoped Event Manager for their own event)."""
    return await service.upsert_configuration(uuid.UUID(event_id), **payload.model_dump())


@router.get("/field-schema/{participation_type}", response_model=EventFieldSchemaOut | None)
async def get_field_schema(
    event_id: str,
    participation_type: str,
    current_user: User = Depends(get_current_user),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """Called by: both."""
    return await service.get_field_schema(uuid.UUID(event_id), participation_type)


@router.get("/field-schema", response_model=EventFieldSchemaOut | None)
async def get_field_schema_by_query(
    event_id: str,
    participation_type: str = Query(..., description="Participation type to load the schema for"),
    current_user: User = Depends(get_current_user),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """Alias for the documented GET /events/{id}/field-schema endpoint shape."""
    return await service.get_field_schema(uuid.UUID(event_id), participation_type)


@router.put(
    "/field-schema",
    response_model=EventFieldSchemaOut,
    status_code=status.HTTP_200_OK,
)
async def upsert_field_schema(
    event_id: str,
    payload: EventFieldSchemaIn,
    current_user: User = Depends(_can_configure),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """Called by: console (Operations Admin, or scoped Event Manager for their own event)."""
    fields_as_dicts = [f.model_dump() for f in payload.fields]
    return await service.upsert_field_schema(
        uuid.UUID(event_id), payload.participation_type, fields_as_dicts
    )


@router.post("/configuration/validate", response_model=ValidationResultOut)
async def validate_registration_payload(
    event_id: str,
    payload: ValidateRegistrationIn,
    current_user: User = Depends(get_current_user),
    service: ConfigEngineService = Depends(get_config_engine_service),
):
    """
    Called by: both — mobile uses this to pre-check a registration before
    submitting (better UX than a rejected submission); Console's
    Configuration Builder uses it to preview the effect of a rule change.
    """
    is_eligible, errors = await service.validate_registration(
        uuid.UUID(event_id),
        payload.participation_type,
        payload.date_of_birth,
        payload.team_member_count,
        payload.documents_provided,
        payload.answers,
    )
    return ValidationResultOut(is_eligible=is_eligible, errors=errors)
