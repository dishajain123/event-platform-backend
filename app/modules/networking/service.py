import uuid
from datetime import datetime, timezone
from sqlalchemy import and_, case, delete, exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from app.core.audit import write_audit_log
from app.core.pagination import Page
from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError
from app.modules.events.models import Event, ScheduleItem
from app.modules.funnels.models import Competition, Entry
from app.modules.identity.models import User
from app.modules.networking.models import ConnectionIntent, ConnectionStatus, EventNetworkingConfig, NetworkingConnection, NetworkingDismissal, NetworkingProfile, NetworkingReport, NetworkingReportStatus, NetworkingVisibility
from app.modules.notifications.service import NotificationService
from app.modules.registrations.models import ACTIVE_REGISTRATION_STATUSES, Registration


class NetworkingService:
    def __init__(self, db: AsyncSession): self.db = db

    async def event(self, event_id):
        event = await self.db.get(Event, event_id)
        if event is None: raise NotFoundError("Event not found.")
        return event

    async def config(self, event_id):
        return await self.db.scalar(select(EventNetworkingConfig).where(EventNetworkingConfig.event_id == event_id))

    async def ensure_eligible(self, event_id, user_id, *, require_enabled=True):
        event = await self.event(event_id)
        config = await self.config(event_id)
        if config is None or (require_enabled and not config.enabled): raise ValidationError("Networking is not enabled for this event.")
        end_date = event.end_date if event.end_date.tzinfo else event.end_date.replace(tzinfo=timezone.utc)
        if end_date <= datetime.now(timezone.utc): raise ValidationError("Networking is closed for this event.")
        registration = await self.db.scalar(select(Registration).where(Registration.event_id == event_id, Registration.user_id == user_id, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES))))
        if registration is None: raise PermissionDeniedError("An eligible event registration is required.")
        if config.allowed_participant_types and registration.participation_type not in config.allowed_participant_types: raise PermissionDeniedError("Your participation type is not eligible for networking.")
        return config

    async def profile(self, event_id, user_id):
        await self.ensure_eligible(event_id, user_id)
        profile = await self.db.scalar(select(NetworkingProfile).where(NetworkingProfile.event_id == event_id, NetworkingProfile.user_id == user_id))
        if profile is None:
            profile = NetworkingProfile(event_id=event_id, user_id=user_id)
            self.db.add(profile)
            await self.db.commit()
            await self.db.refresh(profile)
        return profile

    async def save_profile(self, event_id, user, values):
        await self.ensure_eligible(event_id, user.id)
        if hasattr(values, "model_dump"):
            values = values.model_dump()
        profile = await self.db.scalar(select(NetworkingProfile).where(NetworkingProfile.event_id == event_id, NetworkingProfile.user_id == user.id))
        if profile is None: profile = NetworkingProfile(event_id=event_id, user_id=user.id); self.db.add(profile)
        for key, value in values.items(): setattr(profile, key, value)
        await self.db.flush()
        await write_audit_log(self.db, entity_type="networking_profile", entity_id=profile.id, action="updated", actor_user_id=user.id, after_value={"event_id": str(event_id), "visibility": profile.visibility.value})
        await self.db.commit(); await self.db.refresh(profile)
        return profile

    async def public_profile(self, event_id, profile_id, viewer_id):
        await self.ensure_eligible(event_id, viewer_id)
        profile = await self.db.scalar(select(NetworkingProfile).where(NetworkingProfile.id == profile_id, NetworkingProfile.event_id == event_id, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE))
        if profile is None: raise NotFoundError("Networking participant not found.")
        if profile.user_id == viewer_id:
            raise NotFoundError("Networking participant not found.")
        eligible = await self.db.scalar(select(Registration.id).where(Registration.event_id == event_id, Registration.user_id == profile.user_id, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES))))
        if eligible is None: raise NotFoundError("Networking participant not found.")
        blocked = await self.db.scalar(select(NetworkingConnection.id).where(NetworkingConnection.event_id == event_id, NetworkingConnection.status == ConnectionStatus.BLOCKED, or_(and_(NetworkingConnection.participant_low_id == viewer_id, NetworkingConnection.participant_high_id == profile.user_id), and_(NetworkingConnection.participant_high_id == viewer_id, NetworkingConnection.participant_low_id == profile.user_id))))
        if blocked is not None: raise NotFoundError("Networking participant not found.")
        return profile

    async def discover(self, event_id, user_id, *, page, page_size, search=None, organization=None, designation=None, interest=None, skill=None, recommended=False):
        config = await self.ensure_eligible(event_id, user_id)
        if recommended and not config.matchmaking_enabled: raise ValidationError("Matchmaking is not enabled for this event.")
        blocked = select(NetworkingConnection.participant_high_id).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_low_id == user_id, NetworkingConnection.status == ConnectionStatus.BLOCKED).union_all(select(NetworkingConnection.participant_low_id).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_high_id == user_id, NetworkingConnection.status == ConnectionStatus.BLOCKED))
        filters = [NetworkingProfile.event_id == event_id, NetworkingProfile.user_id != user_id, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE, NetworkingProfile.user_id.in_(select(Registration.user_id).where(Registration.event_id == event_id, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)))), ~NetworkingProfile.user_id.in_(blocked)]
        if recommended:
            filters.append(~NetworkingProfile.user_id.in_(select(NetworkingDismissal.participant_id).where(NetworkingDismissal.event_id == event_id, NetworkingDismissal.requester_id == user_id)))
            accepted = select(NetworkingConnection.participant_high_id).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_low_id == user_id, NetworkingConnection.status == ConnectionStatus.ACCEPTED).union_all(select(NetworkingConnection.participant_low_id).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_high_id == user_id, NetworkingConnection.status == ConnectionStatus.ACCEPTED))
            filters.append(~NetworkingProfile.user_id.in_(accepted))
        if search: filters.append(or_(NetworkingProfile.display_name.ilike(f"%{search}%"), NetworkingProfile.organization.ilike(f"%{search}%"), NetworkingProfile.designation.ilike(f"%{search}%")))
        if organization: filters.append(NetworkingProfile.organization.ilike(f"%{organization}%"))
        if designation: filters.append(NetworkingProfile.designation.ilike(f"%{designation}%"))
        if interest: filters.append(NetworkingProfile.interests.contains([interest]))
        if skill: filters.append(NetworkingProfile.skills.contains([skill]))
        own = await self.profile(event_id, user_id)
        own_interests, own_skills = set(own.interests or []), set(own.skills or [])
        own_registration = await self.db.scalar(select(Registration).where(Registration.event_id == event_id, Registration.user_id == user_id, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES))))
        own_type = own_registration.participation_type if own_registration else None
        own_competitions = set((await self.db.scalars(select(Entry.competition_id).join(Registration, Registration.id == Entry.registration_id).where(Entry.event_id == event_id, Registration.user_id == user_id, Entry.competition_id.is_not(None)))).all())
        score_expr = literal(0)
        for value in own_interests:
            score_expr = score_expr + case((NetworkingProfile.interests.contains([value]), 2), else_=0)
        for value in own_skills:
            score_expr = score_expr + case((NetworkingProfile.skills.contains([value]), 1), else_=0)
        if own.organization:
            score_expr = score_expr + case((NetworkingProfile.organization == own.organization, 2), else_=0)
        if own.designation:
            score_expr = score_expr + case((NetworkingProfile.designation == own.designation, 1), else_=0)
        if own_type:
            score_expr = score_expr + case((exists(select(Registration.id).where(Registration.event_id == event_id, Registration.user_id == NetworkingProfile.user_id, Registration.participation_type == own_type, Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES)))), 2), else_=0)
        if own_competitions:
            score_expr = score_expr + case((exists(select(Entry.id).join(Registration, Registration.id == Entry.registration_id).where(Entry.event_id == event_id, Entry.competition_id.in_(own_competitions), Registration.user_id == NetworkingProfile.user_id)), 3), else_=0)
        ordering = [NetworkingProfile.display_name.asc().nullslast(), NetworkingProfile.id.asc()]
        if recommended:
            ordering = [score_expr.desc(), NetworkingProfile.id.asc()]
        rows = list((await self.db.scalars(select(NetworkingProfile).where(*filters).order_by(*ordering).offset((page-1)*page_size).limit(page_size))).all())
        total = await self.db.scalar(select(func.count(NetworkingProfile.id)).where(*filters)) or 0
        result = []
        candidate_ids = [row.user_id for row in rows]
        candidate_types = {}
        if candidate_ids:
            candidate_types = {uid: ptype for uid, ptype in (await self.db.execute(select(Registration.user_id, Registration.participation_type).where(Registration.event_id == event_id, Registration.user_id.in_(candidate_ids), Registration.status.in_(tuple(ACTIVE_REGISTRATION_STATUSES))))).all()}
        candidate_competitions = {}
        if candidate_ids:
            competition_rows = await self.db.execute(select(Registration.user_id, Entry.competition_id).join(Entry, Entry.registration_id == Registration.id).where(Entry.event_id == event_id, Registration.user_id.in_(candidate_ids), Entry.competition_id.is_not(None)))
            for uid, competition_id in competition_rows.all(): candidate_competitions.setdefault(uid, set()).add(competition_id)
        for row in rows:
            shared_i = sorted(own_interests.intersection(row.interests or [])); shared_s = sorted(own_skills.intersection(row.skills or [])); same_org = bool(own.organization and own.organization == row.organization); same_designation = bool(own.designation and own.designation == row.designation); same_type = bool(own_type and candidate_types.get(row.user_id) == own_type); shared_competitions = own_competitions.intersection(candidate_competitions.get(row.user_id, set()))
            score = len(shared_i) * 2 + len(shared_s) + (2 if same_org else 0) + (1 if same_designation else 0) + (2 if same_type else 0) + (3 if shared_competitions else 0)
            explanation = ([f"{len(shared_i)} shared interests"] if shared_i else []) + ([f"{len(shared_s)} shared skills"] if shared_s else []) + (["same organization"] if same_org else []) + (["same designation"] if same_designation else []) + (["same participation type"] if same_type else []) + (["same competition"] if shared_competitions else [])
            result.append({**{k: getattr(row, k) for k in ("id", "event_id", "user_id", "display_name", "organization", "designation", "interests", "skills", "bio", "visibility", "share_contact")}, "score": score if recommended else None, "explanation": explanation if recommended else []})
        return Page(items=result, total=total, page=page, page_size=page_size)

    async def dismiss(self, event_id, actor_id, participant_id):
        await self.ensure_eligible(event_id, actor_id)
        profile_id = await self.db.scalar(select(NetworkingProfile.id).where(NetworkingProfile.event_id == event_id, NetworkingProfile.user_id == participant_id, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE))
        await self.public_profile(event_id, profile_id or uuid.uuid4(), actor_id)
        existing = await self.db.scalar(select(NetworkingDismissal).where(NetworkingDismissal.event_id == event_id, NetworkingDismissal.requester_id == actor_id, NetworkingDismissal.participant_id == participant_id))
        if existing:
            return existing
        dismissal = NetworkingDismissal(event_id=event_id, requester_id=actor_id, participant_id=participant_id)
        self.db.add(dismissal)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            dismissal = await self.db.scalar(select(NetworkingDismissal).where(NetworkingDismissal.event_id == event_id, NetworkingDismissal.requester_id == actor_id, NetworkingDismissal.participant_id == participant_id))
            if dismissal is None:
                raise
        await self.db.refresh(dismissal)
        return dismissal

    async def activities(self, event_id, user_id, *, page, page_size, search=None):
        await self.ensure_eligible(event_id, user_id)
        term = f"%{search}%" if search else None
        schedule_where = [ScheduleItem.event_id == event_id]
        competition_where = [Competition.event_id == event_id]
        if term:
            schedule_where.append(ScheduleItem.title.ilike(term)); competition_where.append(Competition.name.ilike(term))
        schedules = list((await self.db.scalars(select(ScheduleItem).where(*schedule_where).order_by(ScheduleItem.start_time.asc(), ScheduleItem.id.asc()).limit(page * page_size))).all())
        competitions = list((await self.db.scalars(select(Competition).where(*competition_where).order_by(Competition.created_at.asc(), Competition.id.asc()).limit(page * page_size))).all())
        schedule_total = await self.db.scalar(select(func.count(ScheduleItem.id)).where(*schedule_where)) or 0
        competition_total = await self.db.scalar(select(func.count(Competition.id)).where(*competition_where)) or 0
        items = [{"id": item.id, "event_id": event_id, "activity_type": "session", "title": item.title, "starts_at": item.start_time, "ends_at": item.end_time, "status": item.status.value} for item in schedules]
        items.extend({"id": item.id, "event_id": event_id, "activity_type": "competition", "title": item.name, "starts_at": None, "ends_at": None, "status": item.status.value} for item in competitions)
        items.sort(key=lambda item: (item["starts_at"] is None, item["starts_at"] or datetime.max.replace(tzinfo=timezone.utc), item["title"], str(item["id"])))
        total = schedule_total + competition_total
        start = (page - 1) * page_size
        return Page(items=items[start:start + page_size], total=total, page=page, page_size=page_size)

    async def pair(self, event_id, actor_id, other_id):
        if actor_id == other_id: raise ValidationError("You cannot connect with yourself.")
        low, high = sorted((actor_id, other_id), key=str)
        return low, high

    async def connection(self, connection_id):
        connection = await self.db.get(NetworkingConnection, connection_id)
        if connection is None: raise NotFoundError("Connection not found.")
        return connection

    async def unblock_participant(self, event_id, actor, participant_id):
        await self.ensure_eligible(event_id, actor.id)
        low, high = await self.pair(event_id, actor.id, participant_id)
        connection = await self.db.scalar(select(NetworkingConnection).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_low_id == low, NetworkingConnection.participant_high_id == high, NetworkingConnection.status == ConnectionStatus.BLOCKED).with_for_update())
        if connection is None: raise NotFoundError("Blocked participant not found.")
        await write_audit_log(self.db, entity_type="networking_connection", entity_id=connection.id, action="unblocked", actor_user_id=actor.id, after_value={"event_id": str(event_id), "participant_id": str(participant_id)})
        await self.db.delete(connection); await self.db.commit()

    async def send_request(self, event_id, actor, other_id, intent):
        await self.ensure_eligible(event_id, actor.id); await self.ensure_eligible(event_id, other_id)
        if actor.id == other_id: raise ValidationError("You cannot connect with yourself.")
        low, high = await self.pair(event_id, actor.id, other_id)
        existing = await self.db.scalar(select(NetworkingConnection).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_low_id == low, NetworkingConnection.participant_high_id == high))
        if existing and existing.status in {ConnectionStatus.PENDING, ConnectionStatus.ACCEPTED, ConnectionStatus.BLOCKED}: raise ConflictError("An active connection already exists or is blocked.")
        target_profile_id = await self.db.scalar(select(NetworkingProfile.id).where(NetworkingProfile.event_id == event_id, NetworkingProfile.user_id == other_id, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE))
        await self.public_profile(event_id, target_profile_id or uuid.uuid4(), actor.id)
        if existing: existing.status, existing.requested_by, existing.intent, existing.responded_at = ConnectionStatus.PENDING, actor.id, intent, None; connection = existing
        else: connection = NetworkingConnection(event_id=event_id, participant_low_id=low, participant_high_id=high, requested_by=actor.id, intent=intent); self.db.add(connection)
        await self.db.flush(); await write_audit_log(self.db, entity_type="networking_connection", entity_id=connection.id, action="requested", actor_user_id=actor.id, after_value={"event_id": str(event_id)})
        await self.db.commit()
        await self._notify(event_id, other_id, "Networking request received", "A participant sent you a networking request.", f"networking-request:{connection.id}")
        return connection

    async def transition(self, connection_id, actor, target):
        connection = await self.connection(connection_id)
        if actor.id not in {connection.participant_low_id, connection.participant_high_id}: raise PermissionDeniedError("You are not part of this connection.")
        await self.ensure_eligible(connection.event_id, actor.id)
        if target == ConnectionStatus.ACCEPTED and actor.id == connection.requested_by: raise PermissionDeniedError("Only the recipient can accept a request.")
        if target == ConnectionStatus.REJECTED and actor.id == connection.requested_by: raise PermissionDeniedError("Only the recipient can reject a request.")
        if target == ConnectionStatus.CANCELLED and actor.id != connection.requested_by: raise PermissionDeniedError("Only the requester can cancel a request.")
        if target == ConnectionStatus.BLOCKED: pass
        allowed = {ConnectionStatus.PENDING: {ConnectionStatus.ACCEPTED, ConnectionStatus.REJECTED, ConnectionStatus.CANCELLED, ConnectionStatus.BLOCKED}, ConnectionStatus.ACCEPTED: {ConnectionStatus.BLOCKED}, ConnectionStatus.REJECTED: set(), ConnectionStatus.CANCELLED: set(), ConnectionStatus.BLOCKED: set()}
        if target not in allowed[connection.status]: raise ValidationError("Invalid connection transition.")
        connection.status, connection.responded_at = target, datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="networking_connection", entity_id=connection.id, action=target.value, actor_user_id=actor.id)
        await self.db.commit()
        recipient = connection.participant_low_id if actor.id == connection.participant_high_id else connection.participant_high_id
        if target in {ConnectionStatus.ACCEPTED, ConnectionStatus.REJECTED}: await self._notify(connection.event_id, recipient, f"Networking request {target.value}", "Your networking request was updated.", f"networking:{connection.id}:{target.value}")
        return connection

    async def block_participant(self, event_id, actor, participant_id):
        await self.ensure_eligible(event_id, participant_id)
        if actor.id == participant_id: raise ValidationError("You cannot block yourself.")
        low, high = await self.pair(event_id, actor.id, participant_id)
        connection = await self.db.scalar(select(NetworkingConnection).where(NetworkingConnection.event_id == event_id, NetworkingConnection.participant_low_id == low, NetworkingConnection.participant_high_id == high).with_for_update())
        if connection is None:
            connection = NetworkingConnection(event_id=event_id, participant_low_id=low, participant_high_id=high, requested_by=actor.id, status=ConnectionStatus.BLOCKED)
            self.db.add(connection)
        else:
            connection.status = ConnectionStatus.BLOCKED
        await self.db.flush()
        await write_audit_log(self.db, entity_type="networking_connection", entity_id=connection.id, action="blocked", actor_user_id=actor.id, after_value={"event_id": str(event_id), "participant_id": str(participant_id)})
        await self.db.commit()
        return connection

    async def _notify(self, event_id, user_id, title, body, dedupe):
        try:
            service = NotificationService(self.db); notification = await service._queue_automated(event_id=event_id, user_id=user_id, title=title, body=body, notification_type="networking", dedupe_key=dedupe, target_metadata={"event_id": str(event_id), "notification": "networking"})
            if notification: await self.db.commit()
        except Exception: await self.db.rollback()

    async def report(self, event_id, actor, reported_user_id, reason):
        await self.ensure_eligible(event_id, actor.id); await self.ensure_eligible(event_id, reported_user_id)
        if actor.id == reported_user_id: raise ValidationError("You cannot report yourself.")
        duplicate = await self.db.scalar(select(NetworkingReport.id).where(NetworkingReport.event_id == event_id, NetworkingReport.reporter_id == actor.id, NetworkingReport.reported_user_id == reported_user_id, NetworkingReport.status.in_([NetworkingReportStatus.OPEN, NetworkingReportStatus.REVIEWED])))
        if duplicate: raise ConflictError("You already have an active report for this participant.")
        report = NetworkingReport(event_id=event_id, reporter_id=actor.id, reported_user_id=reported_user_id, reason=reason); self.db.add(report); await self.db.flush(); await write_audit_log(self.db, entity_type="networking_report", entity_id=report.id, action="created", actor_user_id=actor.id); await self.db.commit(); return report

    async def report_action(self, report_id, actor, status, notes):
        report = await self.db.get(NetworkingReport, report_id)
        if report is None: raise NotFoundError("Report not found.")
        report.status, report.reviewed_by, report.resolution_notes = status, actor.id, notes
        await write_audit_log(self.db, entity_type="networking_report", entity_id=report.id, action="status_changed", actor_user_id=actor.id, after_value={"status": status.value}); await self.db.commit(); return report

    async def reports(self, event_id, page, page_size, status=None):
        filters = [NetworkingReport.event_id == event_id]
        if status: filters.append(NetworkingReport.status == status)
        total = await self.db.scalar(select(func.count(NetworkingReport.id)).where(*filters)) or 0
        rows = list((await self.db.scalars(select(NetworkingReport).where(*filters).order_by(NetworkingReport.created_at.desc(), NetworkingReport.id.desc()).offset((page-1)*page_size).limit(page_size))).all())
        return Page(items=rows, total=total, page=page, page_size=page_size)

    async def metrics(self, event_id):
        base = NetworkingProfile.event_id == event_id
        opt_in = await self.db.scalar(select(func.count(NetworkingProfile.id)).where(base, NetworkingProfile.visibility == NetworkingVisibility.VISIBLE)) or 0
        values = {}
        for key, value in (("connection_requests", ConnectionStatus.PENDING), ("accepted_connections", ConnectionStatus.ACCEPTED), ("rejected_requests", ConnectionStatus.REJECTED), ("blocked_users", ConnectionStatus.BLOCKED)):
            values[key] = await self.db.scalar(select(func.count(NetworkingConnection.id)).where(NetworkingConnection.event_id == event_id, NetworkingConnection.status == value)) or 0
        values["opt_in_count"] = opt_in; values["discoverable_count"] = opt_in; values["open_reports"] = await self.db.scalar(select(func.count(NetworkingReport.id)).where(NetworkingReport.event_id == event_id, NetworkingReport.status == NetworkingReportStatus.OPEN)) or 0
        values["recommendations_dismissed"] = await self.db.scalar(select(func.count(NetworkingDismissal.id)).where(NetworkingDismissal.event_id == event_id)) or 0
        return values
