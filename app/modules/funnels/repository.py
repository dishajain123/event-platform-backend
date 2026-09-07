import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funnels.models import Competition, CompetitionMatch, CompetitionStage, CompetitionStatus, Entry, MatchStatus, StageDecision


class FunnelRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_competition(self, **kwargs) -> Competition:
        competition = Competition(**kwargs)
        self.db.add(competition)
        await self.db.flush()
        return competition

    async def get_competition(self, competition_id: uuid.UUID) -> Competition | None:
        return await self.db.get(Competition, competition_id)

    async def list_competitions(self, event_id: uuid.UUID | None = None, *, page=1, page_size=25, search=None, public=False):
        filters = []
        if event_id is not None:
            filters.append(Competition.event_id == event_id)
        if search:
            filters.append(Competition.name.ilike(f"%{search.strip()}%"))
        if public:
            filters.append(Competition.status.in_([CompetitionStatus.OPEN, CompetitionStatus.IN_PROGRESS, CompetitionStatus.COMPLETED]))
        total = int(await self.db.scalar(select(func.count(Competition.id)).where(*filters)) or 0)
        result = await self.db.execute(select(Competition).where(*filters).order_by(Competition.created_at.desc(), Competition.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

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

    async def list_stages_for_competition(self, competition_id: uuid.UUID) -> list[CompetitionStage]:
        result = await self.db.execute(select(CompetitionStage).where(CompetitionStage.competition_id == competition_id).order_by(CompetitionStage.order_index, CompetitionStage.id))
        return list(result.scalars().all())

    async def get_stage_by_id(self, stage_id: uuid.UUID) -> CompetitionStage | None:
        return await self.db.get(CompetitionStage, stage_id)

    async def create_entry(self, **kwargs) -> Entry:
        entry = Entry(**kwargs)
        self.db.add(entry)
        await self.db.flush()
        return entry

    async def get_entry_for_competition(self, competition_id: uuid.UUID, entry_id: uuid.UUID) -> Entry | None:
        result = await self.db.execute(select(Entry).where(Entry.id == entry_id, Entry.competition_id == competition_id))
        return result.scalar_one_or_none()

    async def list_entries_for_competition(self, competition_id: uuid.UUID):
        result = await self.db.execute(select(Entry).where(Entry.competition_id == competition_id).order_by(Entry.created_at, Entry.id))
        return list(result.scalars().all())

    async def page_entries_for_competition(self, competition_id: uuid.UUID, *, page=1, page_size=25):
        filters = [Entry.competition_id == competition_id]
        total = int(await self.db.scalar(select(func.count(Entry.id)).where(*filters)) or 0)
        result = await self.db.execute(
            select(Entry)
            .where(*filters)
            .order_by(Entry.created_at.asc(), Entry.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(result.scalars().all()), total

    async def create_match(self, **kwargs) -> CompetitionMatch:
        match = CompetitionMatch(**kwargs)
        self.db.add(match)
        await self.db.flush()
        return match

    async def get_match(self, match_id: uuid.UUID, *, for_update=False) -> CompetitionMatch | None:
        query = select(CompetitionMatch).where(CompetitionMatch.id == match_id)
        if for_update:
            query = query.with_for_update()
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def page_matches(self, competition_id: uuid.UUID, *, page=1, page_size=25, stage_id=None, status=None):
        filters = [CompetitionMatch.competition_id == competition_id]
        if stage_id is not None:
            filters.append(CompetitionMatch.stage_id == stage_id)
        if status is not None:
            filters.append(CompetitionMatch.status == status)
        total = int(await self.db.scalar(select(func.count(CompetitionMatch.id)).where(*filters)) or 0)
        result = await self.db.execute(select(CompetitionMatch).where(*filters).order_by(CompetitionMatch.scheduled_start, CompetitionMatch.id).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

    async def completed_matches(self, competition_id: uuid.UUID):
        result = await self.db.execute(select(CompetitionMatch).where(CompetitionMatch.competition_id == competition_id, CompetitionMatch.status == MatchStatus.COMPLETED).order_by(CompetitionMatch.scheduled_start, CompetitionMatch.id))
        return list(result.scalars().all())

    async def get_entry_by_id(self, entry_id: uuid.UUID) -> Entry | None:
        return await self.db.get(Entry, entry_id)

    async def list_entries_for_stage(self, stage_id: uuid.UUID) -> list[Entry]:
        result = await self.db.execute(select(Entry).where(Entry.current_stage_id == stage_id))
        return list(result.scalars().all())

    async def page_entries_for_stage(self, stage_id: uuid.UUID, *, page=1, page_size=25):
        total = await self.db.scalar(select(func.count(Entry.id)).where(Entry.current_stage_id == stage_id)) or 0
        result = await self.db.execute(select(Entry).where(Entry.current_stage_id == stage_id).order_by(Entry.created_at.desc(), Entry.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

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

    async def get_next_stage_for_competition(self, competition_id: uuid.UUID, order_index: int) -> CompetitionStage | None:
        result = await self.db.execute(
            select(CompetitionStage)
            .where(
                CompetitionStage.competition_id == competition_id,
                CompetitionStage.order_index > order_index,
            )
            .order_by(CompetitionStage.order_index.asc(), CompetitionStage.id.asc())
        )
        return result.scalars().first()

    async def add_decision(self, **kwargs) -> StageDecision:
        decision = StageDecision(**kwargs)
        self.db.add(decision)
        await self.db.flush()
        return decision
