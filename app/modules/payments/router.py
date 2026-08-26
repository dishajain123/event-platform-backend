"""Payment endpoints."""
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.payments.schemas import (
    PaymentGatewayOrderOut,
    PaymentInitiateIn,
    PaymentOut,
    PaymentWebhookIn,
    RefundApproveIn,
    RefundOut,
    RefundRequestIn,
)
from app.modules.payments.service import PaymentService
from app.modules.rbac.models import RoleName

router = APIRouter(prefix="/payments", tags=["payments"])
refunds_router = APIRouter(tags=["payments"])


def get_payment_service(db: AsyncSession = Depends(get_db)) -> PaymentService:
    return PaymentService(db)


@router.post("/initiate", response_model=PaymentGatewayOrderOut, status_code=status.HTTP_201_CREATED)
async def initiate_payment(
    payload: PaymentInitiateIn,
    current_user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    payment = await service.initiate_payment(
        registration_id=payload.registration_id,
        actor=current_user,
        discount_code=payload.discount_code,
    )
    return PaymentGatewayOrderOut(
        payment_id=payment.id,
        gateway_order_id=payment.gateway_order_id or "",
        amount=payment.amount,
        currency=payment.currency,
        key_id=service.settings.payment_gateway_key_id,
    )


@router.post("/webhook", response_model=PaymentOut)
async def payment_webhook(
    payload: PaymentWebhookIn,
    service: PaymentService = Depends(get_payment_service),
):
    return await service.handle_webhook(
        payload.gateway_order_id, payload.gateway_payment_id, payload.gateway_signature
    )


@router.get("", response_model=list[PaymentOut], dependencies=[Depends(require_role(RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR, RoleName.SUPER_ADMIN))])
async def list_payments(
    event_id: str | None = None,
    service: PaymentService = Depends(get_payment_service),
):
    if event_id is None:
        return await service.list_payments()
    return await service.list_payments(uuid.UUID(event_id))


@refunds_router.post(
    "/refunds",
    response_model=RefundOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(RoleName.FINANCE_OPERATOR, RoleName.SUPER_ADMIN))],
)
async def request_refund(
    payload: RefundRequestIn,
    current_user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    return await service.request_refund(
        payment_id=payload.payment_id,
        actor=current_user,
        amount=payload.amount,
        reason=payload.reason,
    )


@refunds_router.post(
    "/refunds/{refund_id}/approve",
    response_model=RefundOut,
    dependencies=[Depends(require_role(RoleName.FINANCE_ADMIN, RoleName.SUPER_ADMIN))],
)
async def approve_refund(
    refund_id: str,
    payload: RefundApproveIn,
    current_user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    return await service.approve_refund(uuid.UUID(refund_id), current_user, payload.reason)
