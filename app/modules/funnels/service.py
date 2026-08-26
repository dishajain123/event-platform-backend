"""
Generic advancement logic for a multi-stage competition funnel.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_global_role, user_has_scoped_role
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.funnels.exceptions import (
    CompetitionStageNotFoundError,
    FunnelEntryNotFoundError,
    InvalidFunnelStateError,
)
from app.modules.funnels.models import CompetitionStage, Entry, EntryStatus, StageType
from app.modules.funnels.repository import FunnelRepository
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName


class FunnelService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.funnels = FunnelRepository(db)
        self.events = EventRepository(db)

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def create_stage(self, event_id: uuid.UUID, **kwargs) -> CompetitionStage:
        await self._get_event_or_raise(event_id)
        stage = await self.funnels.create_stage(event_id=event_id, **kwargs)
        await self.db.commit()
        return stage

    async def list_stages(self, event_id: uuid.UUID) -> list[CompetitionStage]:
        return await self.funnels.list_stages_for_event(event_id)

    async def create_entry(self, event_id: uuid.UUID, registration_id: uuid.UUID) -> Entry:
        stages = await self.list_stages(event_id)
        stage = stages[0] if stages else None
        entry = await self.funnels.create_entry(
            event_id=event_id,
            registration_id=registration_id,
            current_stage_id=stage.id if stage else None,
            status=EntryStatus.ACTIVE,
        )
        await self.db.commit()
        return entry

    async def list_entries(self, stage_id: uuid.UUID) -> list[Entry]:
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
