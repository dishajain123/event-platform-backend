import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funnels.models import CompetitionStage, Entry, StageDecision


class FunnelRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_stage(self, **kwargs) -> CompetitionStage:
        stage = CompetitionStage(**kwargs)
        self.db.add(stage)
        await self.db.flush()
        return stage

    async def list_stages_for_event(self, event_id: uuid.UUID) -> list[CompetitionStage]:
        result = await self.db.execute(
            select(CompetitionStage).where(CompetitionStage.event_id == event_id).order_by(
                CompetitionStage.order_index.asc()
            )
        )
        return list(result.scalars().all())

    async def get_stage_by_id(self, stage_id: uuid.UUID) -> CompetitionStage | None:
        return await self.db.get(CompetitionStage, stage_id)

    async def create_entry(self, **kwargs) -> Entry:
        entry = Entry(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get_entry_by_id(self, entry_id: uuid.UUID) -> Entry | None:
        return await self.db.get(Entry, entry_id)

    async def list_entries_for_stage(self, stage_id: uuid.UUID) -> list[Entry]:
        result = await self.db.execute(select(Entry).where(Entry.current_stage_id == stage_id))
        return list(result.scalars().all())

    async def get_next_stage(self, event_id: uuid.UUID, order_index: int) -> CompetitionStage | None:
        result = await self.db.execute(
            select(CompetitionStage)
            .where(
                CompetitionStage.event_id == event_id,
                CompetitionStage.order_index > order_index,
            )
            .order_by(CompetitionStage.order_index.asc())
        )
        return result.scalar_one_or_none()

    async def add_decision(self, **kwargs) -> StageDecision:
        decision = StageDecision(**kwargs)
        self.db.add(decision)
        await self.db.flush()
        return decision
