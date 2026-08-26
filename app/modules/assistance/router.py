"""Assistance request endpoints."""
import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.modules.assistance.schemas import AssistanceRequestCreateIn, AssistanceRequestDecideIn, AssistanceRequestOut
from app.modules.assistance.service import AssistanceService
from app.modules.identity.models import User

router = APIRouter(prefix="/assistance-requests", tags=["assistance"])


def get_assistance_service(db: AsyncSession = Depends(get_db)) -> AssistanceService:
    return AssistanceService(db)


@router.post("", response_model=AssistanceRequestOut, status_code=status.HTTP_201_CREATED)
async def create_assistance_request(
    payload: AssistanceRequestCreateIn,
    event_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    service: AssistanceService = Depends(get_assistance_service),
):
    request = await service.create_request(
        event_id=uuid.UUID(event_id),
        actor=current_user,
        registration_id=payload.registration_id,
        reason=payload.reason,
        requested_fee_waiver_amount=payload.requested_fee_waiver_amount,
    )
    return AssistanceRequestOut.model_validate(request)


@router.get(
    "",
    response_model=list[AssistanceRequestOut],
)
async def list_assistance_requests(
    event_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    service: AssistanceService = Depends(get_assistance_service),
):
    requests = await service.list_requests(event_id=uuid.UUID(event_id), actor=current_user)
    return [AssistanceRequestOut.model_validate(request) for request in requests]


@router.post("/{request_id}/decide", response_model=AssistanceRequestOut)
async def decide_assistance_request(
    request_id: str,
    payload: AssistanceRequestDecideIn,
    current_user: User = Depends(get_current_user),
    service: AssistanceService = Depends(get_assistance_service),
):
    request = await service.decide_request(
        uuid.UUID(request_id),
        current_user,
        approve=payload.approve,
        decision_reason=payload.decision_reason,
        requested_fee_waiver_amount=payload.requested_fee_waiver_amount,
    )
    return AssistanceRequestOut.model_validate(request)
