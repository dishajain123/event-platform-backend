import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.teams.models import InvitationStatus, Team, TeamInvitation, TeamMember


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