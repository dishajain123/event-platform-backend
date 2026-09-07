import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.audit import write_audit_log
from app.core.concurrency import acquire_advisory_lock
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.certificates.models import BadgeAward, BadgeDefinition, Certificate, CertificateStatus, CertificateTemplate, CertificateType
from app.modules.events.models import Event, EventStatus
from app.modules.funnels.models import CompetitionMatch, CompetitionStage, Entry, EntryStatus, MatchStatus
from app.modules.identity.models import User
from app.modules.notifications.service import NotificationService
from app.modules.registrations.models import Registration, RegistrationParticipant, RegistrationStatus
from app.modules.rbac.models import RoleName
from app.modules.tickets.models import CheckIn, Ticket


MANAGER_ROLES = {RoleName.EVENT_MANAGER, RoleName.EVENT_COORDINATOR}
GLOBAL_ROLES = {RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN}


class CertificateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def can_manage(self, actor: User, event_id: uuid.UUID) -> bool:
        return await user_has_scoped_role(self.db, actor.id, MANAGER_ROLES, event_id, allow_global_roles=GLOBAL_ROLES)

    async def event(self, event_id):
        event = await self.db.get(Event, event_id)
        if event is None:
            raise ValueError("Event not found.")
        return event

    async def _eligible(self, registration: Registration, template: CertificateTemplate, participant_id=None) -> tuple[bool, str]:
        event = await self.event(registration.event_id)
        if event.status != EventStatus.COMPLETED:
            return False, "Event is not completed."
        if registration.status not in {RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}:
            return False, "Registration is not confirmed."
        participant = None
        if participant_id:
            participant = await self.db.get(RegistrationParticipant, participant_id)
            if participant is None or participant.registration_id != registration.id:
                return False, "Participant does not belong to registration."
        criteria = template.criteria or {}
        if criteria.get("attendance_min", 0):
            q = select(func.count()).select_from(CheckIn).join(Ticket, CheckIn.ticket_id == Ticket.id).where(Ticket.registration_id == registration.id)
            if participant_id:
                q = q.where(Ticket.participant_id == participant_id)
            if int(await self.db.scalar(q) or 0) < int(criteria["attendance_min"]):
                return False, "Attendance requirement not met."
        required_status = criteria.get("entry_status")
        if template.certificate_type in {CertificateType.WINNER, CertificateType.RUNNER_UP}:
            competition_id = criteria.get("competition_id")
            if not competition_id:
                return False, "Winner and runner-up certificates require a competition."
            try:
                competition_uuid = uuid.UUID(str(competition_id))
            except ValueError:
                return False, "Competition criteria is invalid."
            final_stage = await self.db.scalar(select(CompetitionStage).where(CompetitionStage.competition_id == competition_uuid).order_by(CompetitionStage.order_index.desc()))
            entry = await self.db.scalar(select(Entry).where(Entry.registration_id == registration.id, Entry.competition_id == competition_uuid))
            if final_stage is None or entry is None:
                return False, "Competition result not found."
            final_match = await self.db.scalar(select(CompetitionMatch).where(CompetitionMatch.competition_id == competition_uuid, CompetitionMatch.stage_id == final_stage.id, CompetitionMatch.status == MatchStatus.COMPLETED).order_by(CompetitionMatch.scheduled_end.desc()))
            if final_match is None:
                return False, "The competition final is not complete."
            if template.certificate_type == CertificateType.WINNER and final_match.winner_entry_id != entry.id:
                return False, "Participant is not the authoritative competition winner."
            if template.certificate_type == CertificateType.RUNNER_UP:
                finalist_ids = {final_match.entry_a_id, final_match.entry_b_id}
                if entry.id not in finalist_ids or final_match.winner_entry_id == entry.id:
                    return False, "Participant is not the authoritative competition runner-up."
        elif required_status:
            entry = await self.db.scalar(select(Entry).where(Entry.registration_id == registration.id).order_by(Entry.created_at.desc()))
            if entry is None:
                return False, "Competition result not found."
            expected = required_status
            if expected and entry.status.value != expected:
                return False, "Competition achievement criteria not met."
        if template.certificate_type == CertificateType.COMPLETION and registration.status != RegistrationStatus.COMPLETED:
            return False, "Completion criteria not met."
        return True, "eligible"

    async def upsert_template(self, event_id, actor, payload):
        if not await self.can_manage(actor, event_id):
            raise PermissionDeniedError("You cannot manage certificates for this event.")
        template = await self.db.scalar(select(CertificateTemplate).where(CertificateTemplate.event_id == event_id, CertificateTemplate.certificate_type == payload.certificate_type.value))
        values = payload.model_dump(); values["certificate_type"] = payload.certificate_type.value
        if template is None:
            template = CertificateTemplate(event_id=event_id, **values); self.db.add(template)
        else:
            for key, value in values.items(): setattr(template, key, value)
        await write_audit_log(self.db, entity_type="certificate_template", entity_id=template.id, action="upserted", actor_user_id=actor.id, after_value={"event_id": str(event_id), "type": payload.certificate_type.value})
        await self.db.commit(); await self.db.refresh(template); return template

    async def list_templates(self, event_id, actor):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view certificates for this event.")
        return list((await self.db.scalars(select(CertificateTemplate).where(CertificateTemplate.event_id == event_id).order_by(CertificateTemplate.created_at, CertificateTemplate.id))).all())

    async def issue(self, event_id, template_id, registration_id, actor, participant_id=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot issue certificates for this event.")
        await acquire_advisory_lock(self.db, f"certificate:{event_id}:{template_id}:{registration_id}:{participant_id or 'user'}")
        template = await self.db.get(CertificateTemplate, template_id); registration = await self.db.get(Registration, registration_id)
        if template is None or registration is None or template.event_id != event_id or registration.event_id != event_id:
            raise ValueError("Certificate target is not in this event.")
        eligible, reason = await self._eligible(registration, template, participant_id)
        if not eligible: raise ValueError(reason)
        user_id = registration.user_id
        if participant_id:
            participant = await self.db.get(RegistrationParticipant, participant_id); user_id = participant.user_id or user_id
        existing = await self.db.scalar(select(Certificate).where(Certificate.event_id == event_id, Certificate.template_id == template.id, Certificate.registration_id == registration.id, Certificate.participant_id == participant_id, Certificate.status == CertificateStatus.ISSUED.value))
        if existing is not None: return existing
        verification_token = secrets.token_urlsafe(32)
        certificate = Certificate(event_id=event_id, template_id=template.id, registration_id=registration.id, participant_id=participant_id, user_id=user_id, certificate_number=f"CERT-{secrets.token_urlsafe(10).upper()}", verification_token=verification_token, status=CertificateStatus.ISSUED.value, issued_by=actor.id, artifact_url=f"/certificates/artifact/{verification_token}")
        self.db.add(certificate); await self.db.flush()
        await write_audit_log(self.db, entity_type="certificate", entity_id=certificate.id, action="issued", actor_user_id=actor.id, after_value={"event_id": str(event_id), "registration_id": str(registration.id), "type": template.certificate_type})
        await self.db.commit(); await self.db.refresh(certificate)
        try:
            notification = NotificationService(self.db)
            await notification._queue_automated(event_id=event_id, user_id=user_id, title="Certificate issued", body=f"Your {template.title} is ready.", notification_type="certificate", dedupe_key=f"certificate-issued:{certificate.id}:{user_id}", target_metadata={"certificate_number": certificate.certificate_number})
            await self.db.commit()
        except Exception:
            await self.db.rollback()
        return certificate

    async def page_mine(self, user_id, page=1, page_size=25):
        filters = [Certificate.user_id == user_id, Certificate.status == CertificateStatus.ISSUED.value]
        total = int(await self.db.scalar(select(func.count(Certificate.id)).where(*filters)) or 0)
        rows = list((await self.db.scalars(select(Certificate).where(*filters).order_by(Certificate.created_at.desc(), Certificate.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        return rows, total

    async def get_mine_detail(self, certificate_id, user_id):
        result = await self.db.execute(select(Certificate, CertificateTemplate, Event).join(CertificateTemplate, Certificate.template_id == CertificateTemplate.id).join(Event, Certificate.event_id == Event.id).where(Certificate.id == certificate_id, Certificate.user_id == user_id))
        row = result.first()
        if row is None:
            return None
        certificate, template, event = row
        return {key: getattr(certificate, key) for key in ("id", "event_id", "template_id", "registration_id", "participant_id", "user_id", "certificate_number", "status", "artifact_url", "verification_token", "created_at", "updated_at")} | {"event_name": event.name, "certificate_type": template.certificate_type, "title": template.title, "description": template.description, "issuer_name": template.issuer_name, "criteria": template.criteria or {}}

    async def verify(self, token):
        result = await self.db.execute(select(Certificate, CertificateTemplate, Event).join(CertificateTemplate, Certificate.template_id == CertificateTemplate.id).join(Event, Certificate.event_id == Event.id).where(Certificate.verification_token == token))
        row = result.first()
        if row is None: return None
        certificate, template, event = row
        return certificate, template, event

    async def revoke(self, certificate_id, actor):
        certificate = await self.db.get(Certificate, certificate_id)
        if certificate is None or not await self.can_manage(actor, certificate.event_id): raise PermissionDeniedError("You cannot revoke this certificate.")
        certificate.status = CertificateStatus.REVOKED.value; certificate.revoked_at = datetime.now(timezone.utc); certificate.revocation_reason = "Revoked by event administrator"
        await write_audit_log(self.db, entity_type="certificate", entity_id=certificate.id, action="revoked", actor_user_id=actor.id, after_value={"event_id": str(certificate.event_id)})
        await self.db.commit(); await self.db.refresh(certificate); return certificate

    async def page_event_certificates(self, event_id, actor, *, page=1, page_size=25, status=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view certificates for this event.")
        filters = [Certificate.event_id == event_id]
        if status: filters.append(Certificate.status == status)
        total = int(await self.db.scalar(select(func.count(Certificate.id)).where(*filters)) or 0)
        items = list((await self.db.scalars(select(Certificate).where(*filters).order_by(Certificate.created_at.desc(), Certificate.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        return items, total

    async def page_eligible_participants(self, event_id, template_id, actor, *, page=1, page_size=25, search=None):
        if not await self.can_manage(actor, event_id):
            raise PermissionDeniedError("You cannot view eligible participants for this event.")
        template = await self.db.get(CertificateTemplate, template_id)
        if template is None or template.event_id != event_id:
            raise ValueError("Certificate template does not belong to this event.")
        registrations = list((await self.db.scalars(
            select(Registration).options(selectinload(Registration.participants)).where(
                Registration.event_id == event_id,
                Registration.status.in_((RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED)),
            ).order_by(Registration.created_at, Registration.id)
        )).all())
        rows = []
        for registration in registrations:
            participants = registration.participants or [None]
            for participant in participants:
                full_name = participant.full_name if participant else "Registered participant"
                if search and search.strip().lower() not in full_name.lower():
                    continue
                eligible, reason = await self._eligible(registration, template, participant.id if participant else None)
                if eligible:
                    rows.append({"registration_id": registration.id, "participant_id": participant.id if participant else None, "user_id": participant.user_id if participant and participant.user_id else registration.user_id, "full_name": full_name, "eligible": True, "reason": reason})
        total = len(rows)
        return rows[(page - 1) * page_size: page * page_size], total

    async def upsert_badge(self, event_id, actor, payload):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot manage badges for this event.")
        badge = await self.db.scalar(select(BadgeDefinition).where(BadgeDefinition.event_id == event_id, BadgeDefinition.name == payload.name))
        values = payload.model_dump()
        if badge is None: badge = BadgeDefinition(event_id=event_id, **values); self.db.add(badge)
        else:
            for key, value in values.items(): setattr(badge, key, value)
        await self.db.commit(); await self.db.refresh(badge); return badge

    async def list_badges(self, event_id, actor):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view badges for this event.")
        return list((await self.db.scalars(select(BadgeDefinition).where(BadgeDefinition.event_id == event_id).order_by(BadgeDefinition.created_at, BadgeDefinition.id))).all())

    async def page_eligible_badge_participants(self, event_id, badge_id, actor, *, page=1, page_size=25, search=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view eligible badge participants for this event.")
        badge = await self.db.get(BadgeDefinition, badge_id)
        if badge is None or badge.event_id != event_id: raise ValueError("Badge does not belong to this event.")
        template = CertificateTemplate(event_id=event_id, certificate_type=CertificateType.ACHIEVEMENT.value, title=badge.name, issuer_name="", criteria=badge.criteria)
        return await self._page_eligible_with_template(event_id, template, actor, page=page, page_size=page_size, search=search)

    async def _page_eligible_with_template(self, event_id, template, actor, *, page=1, page_size=25, search=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view eligible participants for this event.")
        registrations = list((await self.db.scalars(select(Registration).options(selectinload(Registration.participants)).where(Registration.event_id == event_id, Registration.status.in_((RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED))).order_by(Registration.created_at, Registration.id))).all())
        rows = []
        for registration in registrations:
            for participant in registration.participants or [None]:
                full_name = participant.full_name if participant else "Registered participant"
                if search and search.strip().lower() not in full_name.lower(): continue
                eligible, reason = await self._eligible(registration, template, participant.id if participant else None)
                if eligible: rows.append({"registration_id": registration.id, "participant_id": participant.id if participant else None, "user_id": participant.user_id if participant and participant.user_id else registration.user_id, "full_name": full_name, "eligible": True, "reason": reason})
        return rows[(page - 1) * page_size: page * page_size], len(rows)

    async def award_badge(self, event_id, badge_id, registration_id, actor, participant_id=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot award badges for this event.")
        await acquire_advisory_lock(self.db, f"badge-award:{event_id}:{badge_id}:{registration_id}:{participant_id or 'user'}")
        registration = await self.db.get(Registration, registration_id); badge = await self.db.get(BadgeDefinition, badge_id)
        if registration is None or badge is None or registration.event_id != event_id or badge.event_id != event_id: raise ValueError("Badge target is not in this event.")
        template = CertificateTemplate(event_id=event_id, certificate_type=CertificateType.ACHIEVEMENT.value, title=badge.name, issuer_name="", criteria=badge.criteria)
        eligible, reason = await self._eligible(registration, template, participant_id)
        if not eligible: raise ValueError(reason)
        participant = await self.db.get(RegistrationParticipant, participant_id) if participant_id else None
        user_id = participant.user_id if participant and participant.user_id else registration.user_id
        existing = await self.db.scalar(select(BadgeAward).where(BadgeAward.event_id == event_id, BadgeAward.badge_id == badge_id, BadgeAward.registration_id == registration_id, BadgeAward.participant_id == participant_id, BadgeAward.status == "awarded"))
        if existing: return existing
        award = BadgeAward(event_id=event_id, badge_id=badge_id, registration_id=registration_id, participant_id=participant_id, user_id=user_id, status="awarded")
        self.db.add(award); await self.db.flush(); await write_audit_log(self.db, entity_type="badge_award", entity_id=award.id, action="awarded", actor_user_id=actor.id, after_value={"event_id": str(event_id), "badge_id": str(badge_id)})
        await self.db.commit(); await self.db.refresh(award); return award

    async def list_mine_badges(self, user_id):
        return list((await self.db.scalars(select(BadgeAward).where(BadgeAward.user_id == user_id, BadgeAward.status == "awarded").order_by(BadgeAward.created_at.desc()))).all())

    async def page_event_badges(self, event_id, actor, *, page=1, page_size=25, status=None):
        if not await self.can_manage(actor, event_id): raise PermissionDeniedError("You cannot view badges for this event.")
        filters = [BadgeAward.event_id == event_id]
        if status: filters.append(BadgeAward.status == status)
        total = int(await self.db.scalar(select(func.count(BadgeAward.id)).where(*filters)) or 0)
        items = list((await self.db.scalars(select(BadgeAward).where(*filters).order_by(BadgeAward.created_at.desc(), BadgeAward.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        return items, total

    async def revoke_badge(self, award_id, actor):
        award = await self.db.get(BadgeAward, award_id)
        if award is None or not await self.can_manage(actor, award.event_id): raise PermissionDeniedError("You cannot revoke this badge.")
        award.status = "revoked"; award.revoked_at = datetime.now(timezone.utc); award.revocation_reason = "Revoked by event administrator"
        await write_audit_log(self.db, entity_type="badge_award", entity_id=award.id, action="revoked", actor_user_id=actor.id, after_value={"event_id": str(award.event_id)})
        await self.db.commit(); await self.db.refresh(award); return award
