"""
Team lifecycle: create, invite, respond, submit, and approve.

submit_team() creates the underlying Registration (via
RegistrationService) that Payments/Tickets/Check-in actually key off —
this is the fix for the gap where teams could be built and approved
but never paid for or ticketed, because no Registration ever existed
for them. approve_team() mirrors that decision onto the real
Registration too, so the two "approve" actions stay in sync instead
of being two disconnected parallel workflows.
"""
import secrets
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.rbac.models import RoleName
from app.modules.registrations.exceptions import DuplicateRegistrationError
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.service import RegistrationService
from app.modules.teams.exceptions import (
    DuplicateTeamInvitationError,
    InvalidTeamStateError,
    TeamEligibilityError,
    TeamInvitationNotFoundError,
    TeamNotFoundError,
)
from app.modules.teams.models import InvitationStatus, Team, TeamStatus
from app.modules.teams.repository import TeamRepository


class TeamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.teams = TeamRepository(db)
        self.events = EventRepository(db)
        self.config = ConfigEngineService(db)
        self.registrations = RegistrationService(db)

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

    async def _can_view_team(self, actor: User, team: Team) -> bool:
        """
        BUG FIX: found while building the mobile app's Team Roster screen —
        GET /teams was Event-Manager/console-only, meaning a team's own
        CAPTAIN had no way whatsoever to check on their own team's
        invitation-acceptance progress after creation (no way to re-fetch
        it after an app restart, no way to see who's accepted). Only the
        create/submit responses ever showed team state, and only at that
        one moment.

        This is the permission check behind the new
        get_team_visible_to_actor()/list_members_visible_to_actor() methods
        below, used by the new GET /teams/{team_id} and
        GET /teams/{team_id}/members endpoints (router.py): the captain,
        any accepted member, or anyone with a pending invitation to this
        team, in addition to the pre-existing event-manager/console access.
        """
        if team.captain_user_id == actor.id:
            return True

        member_user_ids = await self.teams.list_member_user_ids(team.id)
        if actor.id in member_user_ids:
            return True

        pending_invitations = await self.teams.list_pending_invitations_for_team(team.id)
        if any(inv.invitee_mobile == actor.mobile_number for inv in pending_invitations):
            return True

        return await user_has_scoped_role(
            self.db,
            actor.id,
            {RoleName.EVENT_MANAGER},
            team.event_id,
            allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
        )

    async def get_team_visible_to_actor(self, team_id: uuid.UUID, actor: User) -> Team:
        team = await self.get_team_or_raise(team_id)
        if not await self._can_view_team(actor, team):
            raise PermissionDeniedError("You don't have permission to view this team.")
        return team

    async def list_members_visible_to_actor(self, team_id: uuid.UUID, actor: User):
        team = await self.get_team_or_raise(team_id)
        if not await self._can_view_team(actor, team):
            raise PermissionDeniedError("You don't have permission to view this team.")
        return await self.teams.list_members(team_id)

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
        if team.registration_id is not None:
            raise InvalidTeamStateError("This team has already been submitted.")

        config = await self.config.get_configuration(team.event_id)
        if config is None:
            raise InvalidTeamStateError("Event configuration is missing.")
        if "team" not in config.participation_types:
            raise TeamEligibilityError("Team participation is not enabled for this event.")

        members = await self.teams.list_members(team.id)
        team_size = len(members)

        # This is the fix: submitting a team now creates the actual
        # Registration record that Payments/Tickets/Check-in key off.
        # RegistrationService.create_registration runs the exact same
        # rule-engine validation (including team_size) that individual
        # registrations go through — team size enforcement is not
        # duplicated here, it's inherited from that single code path.
        participants = [
            {
                "full_name": member.full_name,
                "date_of_birth": member.date_of_birth,
                "is_captain": member.is_captain,
            }
            for member in members
        ]

        try:
            registration = await self.registrations.create_registration(
                event_id=team.event_id,
                actor=actor,
                participation_type="team",
                date_of_birth=team.captain_date_of_birth,
                child_id=None,
                team_id=team.id,
                documents_provided=[],
                answers={},
                participants=participants,
                team_member_count=team_size,
            )
        except DuplicateRegistrationError:
            raise InvalidTeamStateError(
                "This captain already has an active team registration for this event."
            )
        except TeamEligibilityError:
            raise
        except Exception as exc:
            # Surfaces the rule engine's actual violation messages (e.g. team
            # size out of bounds) as a TeamEligibilityError, matching what
            # this module's callers already expect to catch.
            raise TeamEligibilityError(str(exc)) from exc

        team.registration_id = registration.id
        team.status = TeamStatus.SUBMITTED
        team.submitted_at = datetime.now(timezone.utc)
        await write_audit_log(
            self.db,
            entity_type="team",
            entity_id=team.id,
            action="submitted",
            actor_user_id=actor.id,
            after_value={"registration_id": str(registration.id), "member_count": team_size},
        )
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
        if team.registration_id is None:
            raise InvalidTeamStateError("This team has not been submitted yet.")

        # Approving a team approves the underlying Registration too — this
        # is what actually unlocks payment/ticket eligibility. Team.status
        # is kept as a synchronized mirror for display, not a second
        # source of truth. If the registration was already auto-approved
        # at submission time (no approval required, no fee), it's already
        # in a state decide_registration() would reject as "already
        # decided" — that's fine, we only forward the decision when the
        # registration is genuinely still pending it.
        registration = await self.registrations.get_registration_or_raise(team.registration_id)
        decidable_statuses = {
            RegistrationStatus.PENDING_VERIFICATION,
            RegistrationStatus.PENDING_PAYMENT,
            RegistrationStatus.SUBMITTED,
            RegistrationStatus.STARTED,
        }
        if registration.status in decidable_statuses:
            await self.registrations.decide_registration(team.registration_id, actor, True)

        team.status = TeamStatus.APPROVED
        team.approved_by = actor.id
        team.rejected_by = None
        team.rejection_reason = None
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def list_teams(self, event_id: uuid.UUID) -> list[Team]:
        return await self.teams.list_for_event(event_id)