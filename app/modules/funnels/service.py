"""
Generic advancement logic for a multi-stage competition funnel.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.concurrency import acquire_advisory_lock
from app.exceptions import PermissionDeniedError
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.funnels.exceptions import (
    CompetitionStageNotFoundError,
    FunnelEntryNotFoundError,
    InvalidFunnelStateError,
)
from app.modules.funnels.models import Competition, CompetitionMatch, CompetitionStatus, CompetitionStage, Entry, EntryStatus, MatchResultStatus, MatchStatus, StageStatus, StageType
from app.modules.funnels.repository import FunnelRepository
from app.modules.identity.models import User
from app.modules.notifications.service import NotificationService
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.teams.models import TeamMember
from app.modules.events.service import EventService


class FunnelService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.funnels = FunnelRepository(db)
        self.events = EventRepository(db)

    async def _competition_recipient_ids(self, entry_ids: list[uuid.UUID | None]) -> list[uuid.UUID]:
        entry_ids = [entry_id for entry_id in entry_ids if entry_id is not None]
        if not entry_ids:
            return []
        registrations = list((await self.db.execute(
            select(Registration).join(Entry, Entry.registration_id == Registration.id).where(Entry.id.in_(entry_ids))
        )).scalars().all())
        recipients = {registration.user_id for registration in registrations}
        team_ids = {registration.team_id for registration in registrations if registration.team_id is not None}
        if team_ids:
            member_ids = await self.db.scalars(
                select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids), TeamMember.user_id.is_not(None))
            )
            recipients.update(user_id for user_id in member_ids if user_id is not None)
        return list(recipients)

    async def _queue_competition_notifications(self, *, event_id: uuid.UUID, notification_type: str, dedupe_suffix: str, recipient_ids: list[uuid.UUID], title: str, body: str, metadata: dict) -> None:
        """Queue and best-effort dispatch after the competition transaction commits."""
        if not recipient_ids:
            return
        try:
            notification_service = NotificationService(self.db)
            created_ids: list[uuid.UUID] = []
            for recipient_id in set(recipient_ids):
                notification = await notification_service._queue_automated(
                    event_id=event_id, user_id=recipient_id, title=title, body=body,
                    notification_type=notification_type,
                    dedupe_key=f"competition:{dedupe_suffix}:{recipient_id}",
                    target_metadata={**metadata, "event_id": str(event_id)},
                )
                if notification is not None:
                    created_ids.append(notification.id)
            if not created_ids:
                return
            await self.db.commit()
            if notification_service.settings.environment == "production":
                from app.workers.notification_tasks import deliver_notification_batch
                deliver_notification_batch.delay([str(notification_id) for notification_id in created_ids])
            else:
                for notification_id in created_ids:
                    try:
                        await notification_service.deliver_notification(notification_id)
                    except Exception:
                        continue
        except Exception:
            await self.db.rollback()

    async def get_competition_or_raise(self, competition_id: uuid.UUID) -> Competition:
        competition = await self.funnels.get_competition(competition_id)
        if competition is None:
            raise InvalidFunnelStateError("Competition not found.")
        return competition

    async def create_competition(self, event_id: uuid.UUID, actor: User, **kwargs) -> Competition:
        await self._get_event_or_raise(event_id)
        competition = await self.funnels.create_competition(event_id=event_id, **kwargs, status=CompetitionStatus.DRAFT)
        await write_audit_log(self.db, entity_type="competition", entity_id=competition.id, action="created", actor_user_id=actor.id, after_value={"event_id": str(event_id)})
        await self.db.commit()
        return competition

    async def update_competition(self, competition_id: uuid.UUID, actor: User, **changes) -> Competition:
        competition = await self.get_competition_or_raise(competition_id)
        if competition.status in {CompetitionStatus.COMPLETED, CompetitionStatus.CANCELLED}:
            raise InvalidFunnelStateError("Completed or cancelled competitions cannot be edited.")
        for key, value in changes.items():
            if value is not None:
                setattr(competition, key, value)
        await write_audit_log(self.db, entity_type="competition", entity_id=competition.id, action="updated", actor_user_id=actor.id)
        await self.db.commit()
        return competition

    async def change_competition_status(self, competition_id: uuid.UUID, actor: User, target: CompetitionStatus) -> Competition:
        competition = await self.get_competition_or_raise(competition_id)
        allowed = {
            CompetitionStatus.DRAFT: {CompetitionStatus.OPEN, CompetitionStatus.CANCELLED},
            CompetitionStatus.OPEN: {CompetitionStatus.IN_PROGRESS, CompetitionStatus.CANCELLED},
            CompetitionStatus.IN_PROGRESS: {CompetitionStatus.COMPLETED, CompetitionStatus.CANCELLED},
            CompetitionStatus.COMPLETED: set(),
            CompetitionStatus.CANCELLED: set(),
        }
        if target not in allowed[competition.status]:
            raise InvalidFunnelStateError(f"Cannot move competition from {competition.status.value} to {target.value}.")
        if target == CompetitionStatus.COMPLETED:
            unresolved = await self.db.scalar(select(CompetitionMatch.id).where(CompetitionMatch.competition_id == competition.id, CompetitionMatch.status.not_in([MatchStatus.COMPLETED, MatchStatus.CANCELLED])))
            if unresolved is not None:
                raise InvalidFunnelStateError("All required matches must be completed or cancelled first.")
        competition.status = target
        await write_audit_log(self.db, entity_type="competition", entity_id=competition.id, action="status_changed", actor_user_id=actor.id, after_value={"status": target.value})
        await self.db.commit()
        return competition

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def create_stage(self, event_id: uuid.UUID, **kwargs) -> CompetitionStage:
        await self._get_event_or_raise(event_id)
        competition_id = kwargs.get("competition_id")
        if competition_id is not None:
            competition = await self.get_competition_or_raise(competition_id)
            if competition.event_id != event_id:
                raise InvalidFunnelStateError("Competition belongs to another event.")
        stage = await self.funnels.create_stage(event_id=event_id, **kwargs)
        await self.db.commit()
        return stage

    async def list_stages(self, event_id: uuid.UUID) -> list[CompetitionStage]:
        return await self.funnels.list_stages_for_event(event_id)

    async def list_competition_stages(self, competition_id: uuid.UUID):
        return await self.funnels.list_stages_for_competition(competition_id)

    async def create_entry(self, event_id: uuid.UUID, registration_id: uuid.UUID, competition_id: uuid.UUID | None = None) -> Entry:
        registration = await self.db.get(Registration, registration_id)
        if registration is None or registration.event_id != event_id or registration.status not in {RegistrationStatus.CONFIRMED, RegistrationStatus.CHECKED_IN, RegistrationStatus.COMPLETED}:
            raise InvalidFunnelStateError("Registration is not eligible for this competition.")
        competition = None
        if competition_id is not None:
            competition = await self.get_competition_or_raise(competition_id)
            if competition.event_id != event_id or competition.status in {CompetitionStatus.COMPLETED, CompetitionStatus.CANCELLED}:
                raise InvalidFunnelStateError("Competition is not available for this registration.")
            if competition.participation_mode == "team" and registration.team_id is None:
                raise InvalidFunnelStateError("This competition accepts team registrations only.")
            if competition.participation_mode == "individual" and registration.team_id is not None:
                raise InvalidFunnelStateError("This competition accepts individual registrations only.")
        existing_query = select(Entry).where(Entry.registration_id == registration_id)
        if competition_id is not None:
            existing_query = existing_query.where(Entry.competition_id == competition_id)
        else:
            existing_query = existing_query.where(Entry.competition_id.is_(None))
        existing = await self.db.scalar(existing_query)
        if existing is not None:
            raise InvalidFunnelStateError("This registration is already entered in the competition.")
        stages = await (self.list_competition_stages(competition_id) if competition_id else self.list_stages(event_id))
        stage = stages[0] if stages else None
        entry = await self.funnels.create_entry(
            event_id=event_id,
            competition_id=competition_id,
            registration_id=registration_id,
            current_stage_id=stage.id if stage else None,
            status=EntryStatus.ACTIVE,
        )
        await self.db.commit()
        return entry

    async def create_match(self, competition_id: uuid.UUID, actor: User, **fields) -> CompetitionMatch:
        competition = await self.get_competition_or_raise(competition_id)
        stage = await self.funnels.get_stage_by_id(fields["stage_id"])
        if stage is None or stage.competition_id != competition.id or stage.event_id != competition.event_id:
            raise InvalidFunnelStateError("Stage does not belong to this competition.")
        for key in ("entry_a_id", "entry_b_id"):
            entry_id = fields.get(key)
            if entry_id is not None:
                entry = await self.funnels.get_entry_for_competition(competition.id, entry_id)
                if entry is None:
                    raise InvalidFunnelStateError("Match participant does not belong to this competition.")
        await acquire_advisory_lock(self.db, f"competition-schedule:{competition.event_id}:{fields.get('venue_id')}")
        event = await self._get_event_or_raise(competition.event_id)
        await EventService(self.db)._validate_schedule(event, {"venue_id": fields.get("venue_id"), "title": fields.get("title") or "Competition match", "start_time": fields["scheduled_start"], "end_time": fields["scheduled_end"], "expected_capacity": None, "resource_key": None})
        schedule = await EventService(self.db).schedule.create(competition.event_id, venue_id=fields.get("venue_id"), title=fields.get("title") or "Competition match", start_time=fields["scheduled_start"], end_time=fields["scheduled_end"], expected_capacity=None, resource_key=None)
        match = await self.funnels.create_match(competition_id=competition.id, event_id=competition.event_id, schedule_id=schedule.id, **{key: value for key, value in fields.items() if key != "title"})
        await write_audit_log(self.db, entity_type="competition_match", entity_id=match.id, action="created", actor_user_id=actor.id, after_value={"competition_id": str(competition.id)})
        await self.db.commit()
        await self._queue_competition_notifications(
            event_id=competition.event_id,
            notification_type="competition_fixture",
            dedupe_suffix=f"fixture:{match.id}:scheduled",
            recipient_ids=await self._competition_recipient_ids([match.entry_a_id, match.entry_b_id]),
            title="Competition fixture scheduled",
            body=f"A fixture has been scheduled for {competition.name}.",
            metadata={"competition_id": str(competition.id), "match_id": str(match.id), "notification": "fixture_scheduled"},
        )
        return match

    async def page_matches(self, competition_id: uuid.UUID, **filters):
        return await self.funnels.page_matches(competition_id, **filters)

    async def record_result(self, match_id: uuid.UUID, actor: User, *, score_a, score_b, result_status, winner_entry_id=None, notes=None):
        await acquire_advisory_lock(self.db, f"competition-result:{match_id}")
        match = await self.funnels.get_match(match_id, for_update=True)
        if match is None:
            raise InvalidFunnelStateError("Match not found.")
        if match.status == MatchStatus.CANCELLED or match.status == MatchStatus.COMPLETED:
            raise InvalidFunnelStateError("This match result cannot be changed.")
        if result_status == MatchResultStatus.DRAW and (score_a is None or score_b is None or score_a != score_b):
            raise InvalidFunnelStateError("A draw requires equal scores.")
        if result_status == MatchResultStatus.WIN:
            if winner_entry_id not in {match.entry_a_id, match.entry_b_id} or score_a == score_b:
                raise InvalidFunnelStateError("Winner and scores do not match the fixture participants.")
        if result_status != MatchResultStatus.DRAW and winner_entry_id is None:
            raise InvalidFunnelStateError("A winner is required for this result.")
        match.score_a, match.score_b = score_a, score_b
        match.result_status = result_status
        match.winner_entry_id = winner_entry_id
        match.result_notes = notes
        match.status = MatchStatus.COMPLETED
        match.recorded_by = actor.id
        match.result_recorded_at = datetime.now(timezone.utc)
        if result_status in {MatchResultStatus.WIN, MatchResultStatus.FORFEIT} and winner_entry_id is not None:
            stage = await self.funnels.get_stage_by_id(match.stage_id)
            next_stage = await self.funnels.get_next_stage_for_competition(match.competition_id, stage.order_index) if stage else None
            winner = await self.funnels.get_entry_for_competition(match.competition_id, winner_entry_id)
            loser_id = match.entry_b_id if winner_entry_id == match.entry_a_id else match.entry_a_id
            loser = await self.funnels.get_entry_for_competition(match.competition_id, loser_id) if loser_id else None
            if winner is not None:
                winner.current_stage_id = next_stage.id if next_stage is not None else match.stage_id
                winner.status = EntryStatus.ADVANCED if next_stage is not None else EntryStatus.COMPLETED
            if loser is not None:
                loser.status = EntryStatus.ELIMINATED
        await write_audit_log(self.db, entity_type="competition_match", entity_id=match.id, action="result_recorded", actor_user_id=actor.id, after_value={"result_status": result_status.value})
        await self.db.commit()
        await self._queue_competition_notifications(
            event_id=match.event_id,
            notification_type="competition_result",
            dedupe_suffix=f"match:{match.id}:result",
            recipient_ids=await self._competition_recipient_ids([match.entry_a_id, match.entry_b_id]),
            title="Competition result published",
            body="A competition result has been published.",
            metadata={"competition_id": str(match.competition_id), "match_id": str(match.id), "notification": "result_published"},
        )
        if result_status in {MatchResultStatus.WIN, MatchResultStatus.FORFEIT} and winner_entry_id is not None:
            await self._queue_competition_notifications(
                event_id=match.event_id,
                notification_type="competition_progression",
                dedupe_suffix=f"match:{match.id}:progression:{winner_entry_id}",
                recipient_ids=await self._competition_recipient_ids([winner_entry_id]),
                title="You advanced in the competition",
                body="Your competition entry advanced after the published result.",
                metadata={"competition_id": str(match.competition_id), "match_id": str(match.id), "entry_id": str(winner_entry_id), "notification": "progression"},
            )
            loser_id = match.entry_b_id if winner_entry_id == match.entry_a_id else match.entry_a_id
            await self._queue_competition_notifications(
                event_id=match.event_id,
                notification_type="competition_elimination",
                dedupe_suffix=f"match:{match.id}:elimination:{loser_id}",
                recipient_ids=await self._competition_recipient_ids([loser_id]),
                title="Competition entry eliminated",
                body="Your competition entry was eliminated after the published result.",
                metadata={"competition_id": str(match.competition_id), "match_id": str(match.id), "entry_id": str(loser_id), "notification": "elimination"},
            )
        return match

    async def standings(self, competition_id: uuid.UUID):
        entries = await self.funnels.list_entries_for_competition(competition_id)
        matches = await self.funnels.completed_matches(competition_id)
        table = {entry.id: {"entry_id": entry.id, "played": 0, "wins": 0, "losses": 0, "draws": 0, "points": 0, "score_for": 0, "score_against": 0} for entry in entries}
        for match in matches:
            if match.entry_a_id not in table or match.entry_b_id not in table:
                continue
            a, b = table[match.entry_a_id], table[match.entry_b_id]
            a["played"] += 1; b["played"] += 1
            a["score_for"] += match.score_a or 0; a["score_against"] += match.score_b or 0
            b["score_for"] += match.score_b or 0; b["score_against"] += match.score_a or 0
            if match.result_status == MatchResultStatus.DRAW:
                a["draws"] += 1; b["draws"] += 1; a["points"] += 1; b["points"] += 1
            elif match.winner_entry_id == match.entry_a_id:
                a["wins"] += 1; b["losses"] += 1; a["points"] += 3
            elif match.winner_entry_id == match.entry_b_id:
                b["wins"] += 1; a["losses"] += 1; b["points"] += 3
        rows = list(table.values())
        rows.sort(key=lambda row: (-row["points"], -(row["score_for"] - row["score_against"]), -row["score_for"], str(row["entry_id"])))
        return [{**row, "position": index + 1, "difference": row["score_for"] - row["score_against"]} for index, row in enumerate(rows)]

    async def list_entries(self, stage_id: uuid.UUID) -> list[Entry]:
        return await self.funnels.list_entries_for_stage(stage_id)

    async def page_entries(self, stage_id: uuid.UUID, *, page=1, page_size=25):
        return await self.funnels.page_entries_for_stage(stage_id, page=page, page_size=page_size)

    async def list_public_vote_entries(self, stage_id: uuid.UUID) -> list[Entry]:
        """
        BUG FIX: found while building the mobile app's public voting
        screen — GET /entries is Event-Manager-only, meaning a plain
        participant had no way whatsoever to discover which entries
        exist to vote for, even during an active public_vote stage. This
        is deliberately narrower than list_entries above: it only ever
        returns entries for a stage whose stage_type is PUBLIC_VOTE,
        raising if the stage is a jury/manual-review stage instead — a
        participant should never be able to browse entries mid-judging
        for a stage that was never meant to be public.
        """
        stage = await self._get_stage_or_raise(stage_id)
        if stage.stage_type != StageType.PUBLIC_VOTE:
            raise PermissionDeniedError("This stage is not open for public voting.")
        return await self.funnels.list_entries_for_stage(stage_id)

    async def _get_entry_or_raise(self, entry_id: uuid.UUID) -> Entry:
        entry = await self.funnels.get_entry_by_id(entry_id)
        if entry is None:
            raise FunnelEntryNotFoundError("Entry not found.")
        return entry

    async def _get_stage_or_raise(self, stage_id: uuid.UUID) -> CompetitionStage:
        stage = await self.funnels.get_stage_by_id(stage_id)
        if stage is None:
            raise CompetitionStageNotFoundError("Stage not found.")
        return stage

    async def advance_entry(self, entry_id: uuid.UUID, actor: User, decision: str, score=None, notes=None) -> Entry:
        entry = await self._get_entry_or_raise(entry_id)
        if entry.current_stage_id is None:
            raise InvalidFunnelStateError("Entry has no current stage.")
        current_stage = await self._get_stage_or_raise(entry.current_stage_id)
        next_stage = await self.funnels.get_next_stage(entry.event_id, current_stage.order_index)
        if decision.lower() == "eliminate":
            entry.status = EntryStatus.ELIMINATED
        elif next_stage is None:
            entry.status = EntryStatus.COMPLETED
            entry.current_stage_id = None
        else:
            entry.status = EntryStatus.ADVANCED
            entry.current_stage_id = next_stage.id
        await self.funnels.add_decision(
            entry_id=entry.id,
            stage_id=current_stage.id,
            decided_by=actor.id,
            decision=decision,
            score=score,
            notes=notes,
        )
        await write_audit_log(
            self.db,
            entity_type="funnel_entry",
            entity_id=entry.id,
            action="advanced",
            actor_user_id=actor.id,
            after_value={"decision": decision, "status": entry.status.value},
        )
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def vote_entry(self, entry_id: uuid.UUID, actor: User) -> Entry:
        entry = await self._get_entry_or_raise(entry_id)
        current_stage = await self._get_stage_or_raise(entry.current_stage_id) if entry.current_stage_id else None
        if current_stage is None or current_stage.stage_type != StageType.PUBLIC_VOTE:
            raise InvalidFunnelStateError("This entry is not currently open for voting.")
        entry.vote_count += 1
        if current_stage.threshold is not None and entry.vote_count >= current_stage.threshold:
            next_stage = await self.funnels.get_next_stage(entry.event_id, current_stage.order_index)
            if next_stage is None:
                entry.status = EntryStatus.COMPLETED
                entry.current_stage_id = None
            else:
                entry.status = EntryStatus.ADVANCED
                entry.current_stage_id = next_stage.id
        await write_audit_log(
            self.db,
            entity_type="funnel_entry",
            entity_id=entry.id,
            action="voted",
            actor_user_id=actor.id,
            after_value={"vote_count": entry.vote_count},
        )
        await self.db.commit()
        await self.db.refresh(entry)
        return entry
