import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user, require_role
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.sponsorships.models import SponsorConsentStatus, SponsorEngagementType, SponsorLeadStatus, SponsorshipDeliverableStatus, SponsorshipInquiryStatus
from app.modules.events.models import SponsorStatus
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
    SponsorStatusIn,
    SponsorFinancialUpdateIn,
    SponsorshipDeliverableIn,
    SponsorshipDeliverableOut,
    SponsorshipDeliverablePage,
    SponsorshipDeliverableUpdateIn,
    SponsorshipMetricsOut,
    SponsorSummaryOut,
    SponsorEngagementCreateIn,
    SponsorEngagementOut,
    SponsorEngagementPage,
    SponsorEngagementMetricsOut,
    SponsorLeadStatusIn,
    SponsorConsentIn,
)
from app.modules.sponsorships.service import SponsorshipService
from app.core.pagination import Page

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


@router.get("/sponsors", response_model=list[EventSponsorOut] | Page[EventSponsorOut])
async def list_manageable_sponsors(
    event_id: uuid.UUID | None = None,
    sponsor_status: SponsorStatus | None = Query(None, alias="status"),
    category: str | None = Query(None, max_length=100),
    search: str | None = Query(None, max_length=100),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    if page is None:
        return await service.list_manageable_sponsors(current_user, event_id)
    if await service._global_manage(current_user):
        event_ids = {event_id} if event_id else None
    else:
        event_ids = await service._event_ids_for_manager(current_user, event_id)
    items, total = await service.repo.page_sponsors(event_ids=event_ids, status=sponsor_status, category=category, search=search, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/events/{event_id}/metrics", response_model=SponsorshipMetricsOut)
async def sponsorship_metrics(event_id: uuid.UUID, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.get_metrics(current_user, event_id)


@router.get("/sponsors/{sponsor_id}/summary", response_model=SponsorSummaryOut)
async def sponsor_summary(sponsor_id: uuid.UUID, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.sponsor_summary(current_user, sponsor_id)


@router.patch("/sponsors/{sponsor_id}/status", response_model=EventSponsorOut)
async def update_sponsor_status(sponsor_id: uuid.UUID, payload: SponsorStatusIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.update_sponsor_status(current_user, sponsor_id, payload.status)


@router.patch("/sponsors/{sponsor_id}/financials", response_model=EventSponsorOut)
async def update_sponsor_financials(sponsor_id: uuid.UUID, payload: SponsorFinancialUpdateIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.update_sponsor_financials(current_user, sponsor_id, payload.committed_value)


@router.get("/sponsors/{sponsor_id}/deliverables", response_model=list[SponsorshipDeliverableOut] | SponsorshipDeliverablePage)
async def list_deliverables(sponsor_id: uuid.UUID, status_filter: SponsorshipDeliverableStatus | None = Query(None, alias="status"), search: str | None = Query(None, max_length=100), page: int | None = Query(None, ge=1), page_size: int = Query(25, ge=1, le=100), current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    if page is None:
        return await service.list_deliverables(current_user, sponsor_id, status=status_filter, search=search)
    items, total = await service.page_deliverables(current_user, sponsor_id, status=status_filter, search=search, page=page, page_size=page_size)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.post("/sponsors/{sponsor_id}/deliverables", response_model=SponsorshipDeliverableOut, status_code=status.HTTP_201_CREATED)
async def create_deliverable(sponsor_id: uuid.UUID, payload: SponsorshipDeliverableIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.create_deliverable(current_user, sponsor_id, payload.model_dump())


@router.patch("/deliverables/{deliverable_id}", response_model=SponsorshipDeliverableOut)
async def update_deliverable(deliverable_id: uuid.UUID, payload: SponsorshipDeliverableUpdateIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.update_deliverable(current_user, deliverable_id, payload.model_dump(exclude_unset=True))


@router.get("/inquiries/mine", response_model=list[SponsorshipInquiryOut])
async def list_my_inquiries(
    current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)
):
    return [inquiry_response(item) for item in await service.list_my_inquiries(current_user)]


@router.get("/inquiries", response_model=list[SponsorshipInquiryOut] | Page[SponsorshipInquiryOut])
async def list_inquiries(
    event_id: uuid.UUID | None = None,
    inquiry_status: SponsorshipInquiryStatus | None = Query(None, alias="status"),
    page: int | None = Query(None, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    search: str | None = None,
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    if not isinstance(page, int):
        page = None
    if not isinstance(page_size, int):
        page_size = 25
    if page is None:
        items = await service.list_manageable_inquiries(current_user, event_id, inquiry_status)
        return [inquiry_response(item) for item in items]
    items, total = await service.page_manageable_inquiries(current_user, event_id, inquiry_status, search, page=page, page_size=page_size)
    return Page(items=[inquiry_response(item) for item in items], total=total, page=page, page_size=page_size)


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
        "committed_value": sponsor.committed_value,
        "paid_value": sponsor.paid_value,
    }


@router.post("/events/{event_id}/engagements", response_model=SponsorEngagementOut, status_code=status.HTTP_201_CREATED)
async def capture_engagement(event_id: uuid.UUID, payload: SponsorEngagementCreateIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.capture_engagement(current_user, event_id, payload.model_dump())


@router.get("/events/{event_id}/engagements", response_model=SponsorEngagementPage)
async def list_engagements(
    event_id: uuid.UUID,
    sponsor_id: uuid.UUID,
    status_filter: SponsorLeadStatus | None = Query(None, alias="status"),
    engagement_type: SponsorEngagementType | None = None,
    consent_status: SponsorConsentStatus | None = None,
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    service: SponsorshipService = Depends(get_service),
):
    items, total = await service.page_engagements(current_user, event_id, sponsor_id=sponsor_id, page=page, page_size=page_size, status=status_filter, engagement_type=engagement_type, consent_status=consent_status, search=search)
    return Page(items=items, total=total, page=page, page_size=page_size)


@router.get("/engagements/{engagement_id}", response_model=SponsorEngagementOut)
async def get_engagement(engagement_id: uuid.UUID, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.get_engagement(current_user, engagement_id)


@router.patch("/engagements/{engagement_id}/status", response_model=SponsorEngagementOut)
async def update_engagement_status(engagement_id: uuid.UUID, payload: SponsorLeadStatusIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.update_lead_status(current_user, engagement_id, payload.status)


@router.patch("/engagements/{engagement_id}/consent", response_model=SponsorEngagementOut)
async def update_engagement_consent(engagement_id: uuid.UUID, payload: SponsorConsentIn, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.update_consent(current_user, engagement_id, payload.consent_given, payload.consent_source)


@router.get("/events/{event_id}/sponsors/{sponsor_id}/engagement-metrics", response_model=SponsorEngagementMetricsOut)
async def engagement_metrics(event_id: uuid.UUID, sponsor_id: uuid.UUID, current_user: User = Depends(get_current_user), service: SponsorshipService = Depends(get_service)):
    return await service.engagement_metrics(current_user, event_id, sponsor_id)
