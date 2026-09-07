"""Payment endpoints."""
import uuid

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.payments.schemas import (
    PaymentGatewayOrderOut,
    PaymentInitiateIn,
    PaymentOut,
    PaymentWebhookIn,
    PaymentVerifyIn,
    PaymentWebhookInboxOut,
    RefundApproveIn,
    RefundOut,
    RefundRequestIn,
)
from app.core.pagination import Page
from app.modules.payments.models import PaymentStatus, RefundStatus
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


@router.post("/verify", response_model=PaymentOut)
async def verify_payment(
    payload: PaymentVerifyIn,
    current_user: User = Depends(get_current_user),
    service: PaymentService = Depends(get_payment_service),
):
    """Verify a checkout callback; this is not a public webhook endpoint."""
    return await service.verify_payment_for_actor(
        payload.gateway_order_id,
        payload.gateway_payment_id,
        payload.gateway_signature,
        current_user,
    )


@router.post("/razorpay/webhook", response_model=PaymentOut)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(...),
    service: PaymentService = Depends(get_payment_service),
):
    body = await request.body()
    import json

    return await service.handle_gateway_webhook(
        body, x_razorpay_signature, json.loads(body.decode("utf-8"))
    )


@router.get("", response_model=list[PaymentOut] | Page[PaymentOut], dependencies=[Depends(require_role(RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR, RoleName.SUPER_ADMIN))])
async def list_payments(
    event_id: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    payment_status: PaymentStatus | None = None,
    service: PaymentService = Depends(get_payment_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    if not isinstance(search, str):
        search = None
    if page is not None:
        items, total = await service.page_payments(
            event_id=uuid.UUID(event_id) if event_id else None,
            page=page, page_size=page_size, search=search, status=payment_status,
        )
        return Page(items=items, total=total, page=page, page_size=page_size)
    if event_id is None:
        return await service.list_payments()
    return await service.list_payments(uuid.UUID(event_id))


@router.get(
    "/webhooks",
    response_model=list[PaymentWebhookInboxOut],
    dependencies=[
        Depends(
            require_role(
                RoleName.FINANCE_ADMIN,
                RoleName.FINANCE_OPERATOR,
                RoleName.FINANCE_AUDITOR,
                RoleName.SUPER_ADMIN,
            )
        )
    ],
)
async def list_webhook_events(
    limit: int = 100,
    service: PaymentService = Depends(get_payment_service),
):
    return await service.list_webhook_events(limit)


@refunds_router.get(
    "/refunds",
    response_model=list[RefundOut] | Page[RefundOut],
    dependencies=[
        Depends(
            require_role(
                RoleName.FINANCE_ADMIN, RoleName.FINANCE_OPERATOR, RoleName.FINANCE_AUDITOR, RoleName.SUPER_ADMIN
            )
        )
    ],
)
async def list_refunds(
    event_id: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = Query(default=None, max_length=100),
    refund_status: RefundStatus | None = None,
    service: PaymentService = Depends(get_payment_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    if not isinstance(search, str):
        search = None
    """
    Called by: console (all Finance roles, read-only for Auditor). This
    is the Refunds queue's actual data source — previously there was no
    way to list refund requests at all, only draft one and approve a
    specific ID you'd have to already know from elsewhere.
    """
    if page is not None:
        items, total = await service.page_refunds(
            event_id=uuid.UUID(event_id) if event_id else None,
            page=page, page_size=page_size, search=search, status=refund_status,
        )
        return Page(items=items, total=total, page=page, page_size=page_size)
    if event_id is None:
        return await service.list_refunds()
    return await service.list_refunds(uuid.UUID(event_id))


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
