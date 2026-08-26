"""
Team lifecycle: create, invite, respond, submit, and approve.
"""
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.teams.exceptions import (
    DuplicateTeamInvitationError,
    InvalidTeamStateError,
    TeamEligibilityError,
    TeamInvitationNotFoundError,
    TeamNotFoundError,
)
from app.modules.teams.models import InvitationStatus, Team, TeamStatus
from app.modules.teams.repository import TeamRepository
from app.modules.rbac.models import RoleName
from app.core.permissions import user_has_scoped_role


class TeamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.teams = TeamRepository(db)
        self.events = EventRepository(db)
        self.config = ConfigEngineService(db)

    async def _get_event_or_raise(self, event_id: uuid.UUID):
        event = await self.events.get_by_id(event_id)
        if event is None:
            raise EventNotFoundError("Event not found.")
        return event

    async def get_team_or_raise(self, team_id: uuid.UUID) -> Team:
        team = await self.teams.get_by_id(team_id)
        if team is None:
            raise TeamNotFoundError("Team not found.")
        return team

    async def create_team(self, event_id: uuid.UUID, actor: User, name: str, captain_date_of_birth=None) -> Team:
        await self._get_event_or_raise(event_id)
        team = await self.teams.create(
            event_id=event_id,
            captain_user_id=actor.id,
            name=name,
            status=TeamStatus.DRAFT,
            captain_date_of_birth=captain_date_of_birth,
        )
        await self.teams.add_member(
            team_id=team.id,
            user_id=actor.id,
            full_name=actor.name or actor.mobile_number,
            date_of_birth=captain_date_of_birth,
            is_captain=True,
        )
        await write_audit_log(
            self.db,
            entity_type="team",
            entity_id=team.id,
            action="created",
            actor_user_id=actor.id,
            after_value={"event_id": str(event_id), "name": name},
        )
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def invite_member(self, team_id: uuid.UUID, actor: User, invitee_mobile: str):
        team = await self.get_team_or_raise(team_id)
        if team.captain_user_id != actor.id:
            raise InvalidTeamStateError("Only the team captain can invite members.")
        pending = await self.teams.list_pending_invitations_for_team(team.id)
        if any(invite.invitee_mobile == invitee_mobile for invite in pending):
            raise DuplicateTeamInvitationError("This mobile number is already invited to the team.")
        token = secrets.token_urlsafe(16)
        invitation = await self.teams.add_invitation(
            team_id=team.id,
            invitee_mobile=invitee_mobile,
            token=token,
            status=InvitationStatus.PENDING,
        )
        team.status = TeamStatus.INVITING
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def respond_to_invitation(
        self, team_id: uuid.UUID, invitation_id: uuid.UUID, actor: User, accept: bool
    ):
        team = await self.get_team_or_raise(team_id)
        invitation = await self.teams.get_invitation_by_id(invitation_id)
        if invitation is None or invitation.team_id != team.id:
            raise TeamInvitationNotFoundError("Invitation not found.")
        if invitation.invitee_mobile != actor.mobile_number:
            raise InvalidTeamStateError("This invitation was not issued to your mobile number.")
        if invitation.status != InvitationStatus.PENDING:
            raise InvalidTeamStateError("This invitation has already been responded to.")

        invitation.status = InvitationStatus.ACCEPTED if accept else InvitationStatus.REJECTED
        invitation.responded_at = datetime.now(timezone.utc)
        if accept:
            member_ids = set(await self.teams.list_member_user_ids(team.id))
            if actor.id not in member_ids:
                await self.teams.add_member(
                    team_id=team.id,
                    user_id=actor.id,
                    full_name=actor.name or actor.mobile_number,
                    date_of_birth=None,
                    is_captain=False,
                )
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def submit_team(self, team_id: uuid.UUID, actor: User) -> Team:
        team = await self.get_team_or_raise(team_id)
        if team.captain_user_id != actor.id:
            raise InvalidTeamStateError("Only the team captain can submit the team.")

        config = await self.config.get_configuration(team.event_id)
        if config is None:
            raise InvalidTeamStateError("Event configuration is missing.")
        if "team" not in config.participation_types:
            raise TeamEligibilityError("Team participation is not enabled for this event.")

        team_size = await self.teams.count_members(team.id)
        is_valid, errors = await self.config.validate_registration(
            team.event_id,
            "team",
            team.captain_date_of_birth,
            team_size,
            [],
            {},
        )
        if not is_valid:
            raise TeamEligibilityError("; ".join(error.message for error in errors))

        team.status = TeamStatus.SUBMITTED
        team.submitted_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def approve_team(self, team_id: uuid.UUID, actor: User) -> Team:
        team = await self.get_team_or_raise(team_id)
        has_access = await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            team.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )
        if not has_access:
            raise InvalidTeamStateError("You cannot approve this team.")
        team.status = TeamStatus.APPROVED
        team.approved_by = actor.id
        team.rejected_by = None
        team.rejection_reason = None
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def list_teams(self, event_id: uuid.UUID) -> list[Team]:
        return await self.teams.list_for_event(event_id)
