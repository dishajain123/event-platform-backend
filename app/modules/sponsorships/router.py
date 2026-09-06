import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import user_has_global_role
from app.database import get_db
from app.dependencies import get_current_user, get_current_user_optional, require_role
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.sponsorships.models import SponsorshipInquiryStatus
from app.modules.sponsorships.schemas import (
    SponsorshipAssignIn,
    SponsorshipCategoryIn,
    SponsorshipCategoryOut,
    SponsorshipInquiryCreateIn,
    SponsorshipInquiryOut,
    SponsorshipInquiryStatusIn,
    SponsorshipPackageIn,
    SponsorshipPackageOut,
    EventSponsorOut,
)
from app.modules.sponsorships.service import SponsorshipService

router = APIRouter(prefix="/sponsorship", tags=["sponsorship"])


def get_service(db: AsyncSession = Depends(get_db)) -> SponsorshipService:
    return SponsorshipService(db)


def inquiry_response(inquiry):
    response = SponsorshipInquiryOut.model_validate(inquiry)
    return response.model_copy(update={"event_ids": [link.event_id for link in inquiry.events]})


@router.get("/categories", response_model=list[SponsorshipCategoryOut])
async def list_categories(service: SponsorshipService = Depends(get_service)):
    return await service.repo.list_categories()


@router.post(
    "/categories",
    response_model=SponsorshipCategoryOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def create_category(payload: SponsorshipCategoryIn, service: SponsorshipService = Depends(get_service)):
    return await service.create_category(**payload.model_dump())


@router.get("/packages", response_model=list[SponsorshipPackageOut])
async def list_packages(service: SponsorshipService = Depends(get_service)):
    return await service.repo.list_packages()


@router.post(
    "/packages",
    response_model=SponsorshipPackageOut,
    dependencies=[Depends(require_role(RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN))],
)
async def create_package(payload: SponsorshipPackageIn, service: SponsorshipService = Depends(get_service)):
    return await service.create_package(**payload.model_dump())


@router.post("/inquiries", response_model=SponsorshipInquiryOut, status_code=status.HTTP_201_CREATED)
async def create_inquiry(
    payload: SponsorshipInquiryCreateIn,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    return inquiry_response(await service.create_inquiry(current_user, payload.model_dump()))


@router.get("/sponsors", response_model=list[EventSponsorOut])
async def list_manageable_sponsors(
    event_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    return await service.list_manageable_sponsors(current_user, event_id)


@router.get("/inquiries/mine", response_model=list[SponsorshipInquiryOut])
async def list_my_inquiries(
    current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)
):
    return [inquiry_response(item) for item in await service.list_my_inquiries(current_user)]


@router.get("/inquiries", response_model=list[SponsorshipInquiryOut])
async def list_inquiries(
    event_id: uuid.UUID | None = None,
    inquiry_status: SponsorshipInquiryStatus | None = Query(None, alias="status"),
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    items = await service.list_manageable_inquiries(current_user, event_id, inquiry_status)
    return [inquiry_response(item) for item in items]


@router.get("/inquiries/{inquiry_id}", response_model=SponsorshipInquiryOut)
async def get_inquiry(
    inquiry_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    return inquiry_response(await service.get_visible_inquiry(current_user, inquiry_id))


@router.patch("/inquiries/{inquiry_id}/status", response_model=SponsorshipInquiryOut)
async def update_inquiry_status(
    inquiry_id: uuid.UUID,
    payload: SponsorshipInquiryStatusIn,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    return inquiry_response(await service.update_status(current_user, inquiry_id, payload.status))


@router.post("/inquiries/{inquiry_id}/assign", response_model= dict)
async def assign_sponsor(
    inquiry_id: uuid.UUID,
    payload: SponsorshipAssignIn,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    sponsor = await service.assign_sponsor(current_user, inquiry_id, payload.model_dump())
    return {
        "id": sponsor.id,
        "event_id": sponsor.event_id,
        "name": sponsor.name,
        "status": sponsor.status,
        "logo_url": sponsor.logo_url,
        "category": sponsor.category,
        "description": sponsor.description,
        "offer_details": sponsor.offer_details,
        "benefits": sponsor.benefits,
        "website_url": sponsor.website_url,
        "contact_email": sponsor.contact_email,
        "inquiry_id": sponsor.inquiry_id,
    }
