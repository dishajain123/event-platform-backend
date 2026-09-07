import uuid
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import Page
from app.database import get_db
from app.dependencies import get_current_user
from app.modules.certificates.schemas import BadgeAwardOut, BadgeDefinitionIn, BadgeDefinitionOut, BadgePage, CertificateDetailOut, CertificateOut, CertificatePage, CertificateTemplateIn, CertificateTemplateOut, EligibleParticipantOut, EligibleParticipantPage, PublicCertificateOut
from app.modules.certificates.service import CertificateService
from app.modules.identity.models import User

router = APIRouter(prefix="/certificates", tags=["certificates"])
badges_router = APIRouter(prefix="/badges", tags=["badges"])

def service(db: AsyncSession = Depends(get_db)): return CertificateService(db)

@router.get("/mine", response_model=CertificatePage)
async def mine(page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    items, total = await svc.page_mine(user.id, page, page_size); return CertificatePage(items=items, total=total, page=page, page_size=page_size)

@router.get("/mine/{certificate_id}", response_model=CertificateDetailOut)
async def mine_detail(certificate_id: uuid.UUID, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    result = await svc.get_mine_detail(certificate_id, user.id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Certificate not found.")
    return result

@router.get("/verify/{token}", response_model=PublicCertificateOut)
async def verify(token: str, svc: CertificateService = Depends(service)):
    result = await svc.verify(token)
    if result is None or result[0].status != "issued":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Certificate not found or revoked.")
    certificate, template, event = result
    return PublicCertificateOut(certificate_number=certificate.certificate_number, event_name=event.name, certificate_type=template.certificate_type, title=template.title, issuer_name=template.issuer_name, status=certificate.status, issued_at=certificate.created_at)

@router.get("/artifact/{token}", response_class=HTMLResponse)
async def artifact(token: str, svc: CertificateService = Depends(service)):
    result = await svc.verify(token)
    if result is None or result[0].status != "issued":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Certificate not found or revoked.")
    certificate, template, event = result
    return HTMLResponse(f"<html><head><title>{template.title}</title></head><body style='font-family:serif;text-align:center;padding:8rem'><h1>{template.title}</h1><p>{event.name}</p><p>Issued by {template.issuer_name}</p><h2>{certificate.certificate_number}</h2><p>Public verification reference: {certificate.certificate_number}</p></body></html>")

@router.get("/events/{event_id}/templates", response_model=list[CertificateTemplateOut])
async def templates(event_id: uuid.UUID, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.list_templates(event_id, user)

@router.put("/events/{event_id}/templates", response_model=CertificateTemplateOut)
async def upsert_template(event_id: uuid.UUID, payload: CertificateTemplateIn, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.upsert_template(event_id, user, payload)

@router.post("/events/{event_id}/templates/{template_id}/issue", response_model=CertificateOut, status_code=status.HTTP_201_CREATED)
async def issue(event_id: uuid.UUID, template_id: uuid.UUID, registration_id: uuid.UUID, participant_id: uuid.UUID | None = None, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.issue(event_id, template_id, registration_id, user, participant_id)

@router.get("/events/{event_id}/templates/{template_id}/eligible", response_model=EligibleParticipantPage)
async def eligible(event_id: uuid.UUID, template_id: uuid.UUID, search: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    items, total = await svc.page_eligible_participants(event_id, template_id, user, page=page, page_size=page_size, search=search)
    return EligibleParticipantPage(items=items, total=total, page=page, page_size=page_size)

@router.post("/{certificate_id}/revoke", response_model=CertificateOut)
async def revoke(certificate_id: uuid.UUID, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.revoke(certificate_id, user)

@router.get("/events/{event_id}", response_model=CertificatePage)
async def event_certificates(event_id: uuid.UUID, status_filter: str | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    items, total = await svc.page_event_certificates(event_id, user, page=page, page_size=page_size, status=status_filter)
    return CertificatePage(items=items, total=total, page=page, page_size=page_size)

@badges_router.get("/mine", response_model=list[BadgeAwardOut])
async def my_badges(user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.list_mine_badges(user.id)

@badges_router.put("/events/{event_id}", response_model=BadgeDefinitionOut)
async def upsert_badge(event_id: uuid.UUID, payload: BadgeDefinitionIn, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.upsert_badge(event_id, user, payload)

@badges_router.get("/events/{event_id}", response_model=list[BadgeDefinitionOut])
async def list_badges(event_id: uuid.UUID, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.list_badges(event_id, user)

@badges_router.post("/events/{event_id}/{badge_id}/award", response_model=BadgeAwardOut)
async def award_badge(event_id: uuid.UUID, badge_id: uuid.UUID, registration_id: uuid.UUID, participant_id: uuid.UUID | None = None, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.award_badge(event_id, badge_id, registration_id, user, participant_id)

@badges_router.get("/events/{event_id}/{badge_id}/eligible", response_model=EligibleParticipantPage)
async def eligible_badge_participants(event_id: uuid.UUID, badge_id: uuid.UUID, search: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    items, total = await svc.page_eligible_badge_participants(event_id, badge_id, user, page=page, page_size=page_size, search=search)
    return EligibleParticipantPage(items=items, total=total, page=page, page_size=page_size)

@badges_router.get("/events/{event_id}/awards", response_model=BadgePage)
async def event_badge_awards(event_id: uuid.UUID, status_filter: str | None = Query(None, alias="status"), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100), user: User = Depends(get_current_user), svc: CertificateService = Depends(service)):
    items, total = await svc.page_event_badges(event_id, user, page=page, page_size=page_size, status=status_filter)
    return BadgePage(items=items, total=total, page=page, page_size=page_size)

@badges_router.post("/awards/{award_id}/revoke", response_model=BadgeAwardOut)
async def revoke_badge(award_id: uuid.UUID, user: User = Depends(get_current_user), svc: CertificateService = Depends(service)): return await svc.revoke_badge(award_id, user)
