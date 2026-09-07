import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.models import InvitationStatus, JoinRequestStatus, Team, TeamInvitation, TeamJoinRequest, TeamMember


class TeamRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Team:
        team = Team(**kwargs)
        self.db.add(team)
        await self.db.flush()
        return team

    async def get_by_id(self, team_id: uuid.UUID) -> Team | None:
        return await self.db.get(Team, team_id)

    async def list_for_event(self, event_id: uuid.UUID) -> list[Team]:
        result = await self.db.execute(select(Team).where(Team.event_id == event_id))
        return list(result.scalars().all())

    async def list_for_events(self, event_ids: set[uuid.UUID] | None) -> list[Team]:
        query = select(Team)
        if event_ids is not None:
            if not event_ids:
                return []
            query = query.where(Team.event_id.in_(event_ids))
        result = await self.db.execute(query.order_by(Team.created_at.desc(), Team.id.desc()))
        return list(result.scalars().all())

    async def list_for_user(self, user_id: uuid.UUID, mobile: str) -> list[Team]:
        query = select(Team).outerjoin(TeamMember, TeamMember.team_id == Team.id).outerjoin(TeamInvitation, TeamInvitation.team_id == Team.id).where(or_(Team.captain_user_id == user_id, Team.manager_user_id == user_id, TeamMember.user_id == user_id, TeamInvitation.invitee_mobile == mobile)).distinct()
        result = await self.db.execute(query.order_by(Team.created_at.desc(), Team.id.desc()))
        return list(result.scalars().all())

    async def page_for_event(self, event_id: uuid.UUID, *, page=1, page_size=25):
        total = await self.db.scalar(select(func.count(Team.id)).where(Team.event_id == event_id)) or 0
        result = await self.db.execute(select(Team).where(Team.event_id == event_id).order_by(Team.created_at.desc(), Team.id.desc()).offset((page - 1) * page_size).limit(page_size))
        return list(result.scalars().all()), total

    async def page_for_events(self, event_ids: set[uuid.UUID] | None, *, page=1, page_size=25):
        filters = [] if event_ids is None else [Team.event_id.in_(event_ids)]
        total = int(await self.db.scalar(select(func.count(Team.id)).where(*filters)) or 0)
        result = await self.db.execute(
            select(Team).where(*filters).order_by(Team.created_at.desc(), Team.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total

    async def add_member(self, **kwargs) -> TeamMember:
        member = TeamMember(**kwargs)
        self.db.add(member)
        await self.db.flush()
        return member

    async def count_members(self, team_id: uuid.UUID) -> int:
        result = await self.db.execute(select(TeamMember).where(TeamMember.team_id == team_id))
        return len(result.scalars().all())

    async def list_members(self, team_id: uuid.UUID) -> list[TeamMember]:
        result = await self.db.execute(select(TeamMember).where(TeamMember.team_id == team_id))
        return list(result.scalars().all())

    async def list_member_user_ids(self, team_id: uuid.UUID) -> list[uuid.UUID | None]:
        result = await self.db.execute(
            select(TeamMember.user_id).where(TeamMember.team_id == team_id)
        )
        return list(result.scalars().all())

    async def add_invitation(self, **kwargs) -> TeamInvitation:
        invitation = TeamInvitation(**kwargs)
        self.db.add(invitation)
        await self.db.flush()
        return invitation

    async def get_invitation_by_id(self, invitation_id: uuid.UUID) -> TeamInvitation | None:
        return await self.db.get(TeamInvitation, invitation_id)

    async def get_invitation_by_token(self, token: str) -> TeamInvitation | None:
        result = await self.db.execute(select(TeamInvitation).where(TeamInvitation.token == token))
        return result.scalar_one_or_none()

    async def list_pending_invitations_for_team(self, team_id: uuid.UUID) -> list[TeamInvitation]:
        result = await self.db.execute(
            select(TeamInvitation).where(
                TeamInvitation.team_id == team_id, TeamInvitation.status == InvitationStatus.PENDING
            )
        )
        return list(result.scalars().all())

    async def list_pending_invitations_for_mobile(self, mobile: str) -> list[TeamInvitation]:
        result = await self.db.execute(select(TeamInvitation).where(TeamInvitation.invitee_mobile == mobile, TeamInvitation.status == InvitationStatus.PENDING).order_by(TeamInvitation.created_at.desc(), TeamInvitation.id.desc()))
        return list(result.scalars().all())

    async def get_join_request(self, team_id: uuid.UUID, user_id: uuid.UUID) -> TeamJoinRequest | None:
        result = await self.db.execute(select(TeamJoinRequest).where(TeamJoinRequest.team_id == team_id, TeamJoinRequest.user_id == user_id))
        return result.scalar_one_or_none()

    async def list_join_requests(self, team_id: uuid.UUID):
        result = await self.db.execute(select(TeamJoinRequest).where(TeamJoinRequest.team_id == team_id).order_by(TeamJoinRequest.created_at, TeamJoinRequest.id))
        return list(result.scalars().all())
