import pytest
from sqlalchemy import select

from app.modules.certificates.models import CertificateStatus, CertificateTemplate, CertificateType
from app.modules.certificates.service import CertificateService
from app.modules.events.models import EventStatus
from app.modules.identity.models import User
from app.modules.tickets.models import TicketStatus
from tests.modules.tickets.test_tickets import _assign_role, _make_ticket_context


@pytest.mark.asyncio
async def test_certificate_precedence_eligibility_duplicate_and_revocation(db_session):
    context = await _make_ticket_context(db_session)
    context["event"].status = EventStatus.COMPLETED
    template = CertificateTemplate(
        event_id=context["event"].id,
        certificate_type=CertificateType.PARTICIPATION.value,
        title="Participation",
        issuer_name="Organizer",
        criteria={},
    )
    db_session.add(template)
    await db_session.flush()
    service = CertificateService(db_session)

    issued = await service.issue(context["event"].id, template.id, context["registration"].id, context["staff"])
    duplicate = await service.issue(context["event"].id, template.id, context["registration"].id, context["staff"])
    assert issued.id == duplicate.id
    verified = await service.verify(issued.verification_token)
    assert verified is not None
    await service.revoke(issued.id, context["staff"])
    revoked = await service.verify(issued.verification_token)
    assert revoked is not None and revoked[0].status == CertificateStatus.REVOKED.value


@pytest.mark.asyncio
async def test_invalid_registration_and_incomplete_event_never_issue(db_session):
    context = await _make_ticket_context(db_session)
    context["event"].status = EventStatus.COMPLETED
    context["registration"].status = "cancelled"
    template = CertificateTemplate(event_id=context["event"].id, certificate_type="completion", title="Completion", issuer_name="Organizer", criteria={})
    db_session.add(template)
    await db_session.flush()
    service = CertificateService(db_session)
    with pytest.raises(ValueError):
        await service.issue(context["event"].id, template.id, context["registration"].id, context["staff"])

    context["registration"].status = "confirmed"
    context["event"].status = EventStatus.LIVE
    await db_session.commit()
    with pytest.raises(ValueError):
        await service.issue(context["event"].id, template.id, context["registration"].id, context["staff"])
