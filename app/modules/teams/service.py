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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.concurrency import acquire_advisory_lock
from app.core.permissions import user_has_scoped_role
from app.exceptions import PermissionDeniedError
from app.modules.config_engine.service import ConfigEngineService
from app.modules.events.exceptions import EventNotFoundError
from app.modules.events.repository import EventRepository
from app.modules.identity.models import User
from app.modules.notifications.models import Notification, NotificationChannel, NotificationDeliveryStatus
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
from app.modules.teams.models import InvitationStatus, JoinRequestStatus, Team, TeamJoinRequest, TeamMember, TeamMemberRole, TeamStatus
from app.modules.teams.repository import TeamRepository


class TeamService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.teams = TeamRepository(db)
        self.events = EventRepository(db)
        self.config = ConfigEngineService(db)
        self.registrations = RegistrationService(db)

    async def _queue_team_notification(self, *, recipient_id: uuid.UUID, event_id: uuid.UUID, title: str, body: str, dedupe_key: str) -> None:
        existing = await self.db.scalar(select(Notification).where(Notification.dedupe_key == dedupe_key))
        if existing is None:
            self.db.add(Notification(
                event_id=event_id,
                recipient_user_id=recipient_id,
                channel=NotificationChannel.PUSH,
                title=title,
                body=body,
                target_metadata={"team": True},
                delivery_status=NotificationDeliveryStatus.QUEUED,
                notification_type="operational",
                dedupe_key=dedupe_key,
            ))

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

    async def _can_manage_team(self, actor: User, team: Team) -> bool:
        return (
            actor.id in {team.captain_user_id, team.manager_user_id}
            or await user_has_scoped_role(
                self.db, actor.id, {RoleName.EVENT_MANAGER}, team.event_id,
                allow_global_roles={RoleName.SUPER_ADMIN, RoleName.OPERATIONS_ADMIN},
            )
        )

    async def list_members_visible_to_actor(self, team_id: uuid.UUID, actor: User):
        team = await self.get_team_or_raise(team_id)
        if not await self._can_view_team(actor, team):
            raise PermissionDeniedError("You don't have permission to view this team.")
        return await self.teams.list_members(team_id)

    async def create_team(self, event_id: uuid.UUID, actor: User, name: str, captain_date_of_birth=None) -> Team:
        await self._get_event_or_raise(event_id)
        config = await self.config.get_configuration(event_id)
        if config is not None:
            if "team" not in config.participation_types:
                raise TeamEligibilityError("Team participation is not enabled for this event.")
            max_teams = (config.rules or {}).get("max_teams")
            if max_teams is not None:
                existing_count = int(await self.db.scalar(select(func.count(Team.id)).where(Team.event_id == event_id, Team.status != TeamStatus.ARCHIVED)) or 0)
                if existing_count >= int(max_teams):
                    raise TeamEligibilityError("The event has reached its maximum number of teams.")
        team_code = f"TEAM-{secrets.token_hex(6).upper()}"
        team = await self.teams.create(
            event_id=event_id,
            captain_user_id=actor.id,
            name=name,
            team_code=team_code,
            status=TeamStatus.DRAFT,
            captain_date_of_birth=captain_date_of_birth,
        )
        await self.teams.add_member(
            team_id=team.id,
            user_id=actor.id,
            full_name=actor.name or actor.mobile_number,
            date_of_birth=captain_date_of_birth,
            is_captain=True,
            role=TeamMemberRole.CAPTAIN,
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
        await acquire_advisory_lock(self.db, f"team-roster:{team.id}")
        if team.captain_user_id != actor.id:
            raise InvalidTeamStateError("Only the team captain can invite members.")
        if team.registration_id is not None or team.status in {TeamStatus.SUBMITTED, TeamStatus.APPROVED, TeamStatus.ARCHIVED}:
            raise InvalidTeamStateError("Members cannot be changed after team submission.")
        config = await self.config.get_configuration(team.event_id)
        max_size = (config.rules or {}).get("team_size", {}).get("max") if config else None
        if max_size is not None and await self.teams.count_members(team.id) >= int(max_size):
            raise TeamEligibilityError("The team has reached its maximum size.")
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
        invitee = await self.db.scalar(select(User).where(User.mobile_number == invitee_mobile))
        if invitee is not None:
            await self._queue_team_notification(
                recipient_id=invitee.id,
                event_id=team.event_id,
                title="Team invitation",
                body=f"You have been invited to join {team.name}.",
                dedupe_key=f"team-invite:{invitation.id}",
            )
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def respond_to_invitation(
        self, team_id: uuid.UUID, invitation_id: uuid.UUID, actor: User, accept: bool
    ):
        team = await self.get_team_or_raise(team_id)
        await acquire_advisory_lock(self.db, f"team-roster:{team.id}")
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
                    role=TeamMemberRole.MEMBER,
                )
            await self._queue_team_notification(
                recipient_id=team.captain_user_id,
                event_id=team.event_id,
                title="Team member joined",
                body=f"{actor.name or actor.mobile_number} joined {team.name}.",
                dedupe_key=f"team-invite-accepted:{invitation.id}",
            )
        await self.db.commit()
        await self.db.refresh(invitation)
        return invitation

    async def request_to_join(self, team_id: uuid.UUID, actor: User) -> TeamJoinRequest:
        team = await self.get_team_or_raise(team_id)
        await acquire_advisory_lock(self.db, f"team-roster:{team.id}")
        if team.status in {TeamStatus.REJECTED, TeamStatus.ARCHIVED, TeamStatus.APPROVED}:
            raise InvalidTeamStateError("This team is not accepting join requests.")
        if actor.id in set(await self.teams.list_member_user_ids(team.id)):
            raise InvalidTeamStateError("You are already a member of this team.")
        existing = await self.teams.get_join_request(team.id, actor.id)
        if existing is not None and existing.status == JoinRequestStatus.PENDING:
            raise InvalidTeamStateError("You already have a pending join request.")
        request = existing or TeamJoinRequest(team_id=team.id, user_id=actor.id)
        request.status = JoinRequestStatus.PENDING
        request.responded_at = None
        if existing is None:
            self.db.add(request)
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="join_requested", actor_user_id=actor.id)
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def list_join_requests_visible_to_actor(self, team_id: uuid.UUID, actor: User):
        team = await self.get_team_or_raise(team_id)
        if not await self._can_manage_team(actor, team):
            raise PermissionDeniedError("You don't have permission to manage this team.")
        return await self.teams.list_join_requests(team.id)

    async def respond_to_join_request(self, team_id: uuid.UUID, request_id: uuid.UUID, actor: User, approve: bool):
        team = await self.get_team_or_raise(team_id)
        await acquire_advisory_lock(self.db, f"team-roster:{team.id}")
        if not await self._can_manage_team(actor, team):
            raise PermissionDeniedError("You don't have permission to manage this team.")
        request = await self.db.get(TeamJoinRequest, request_id)
        if request is None or request.team_id != team.id or request.status != JoinRequestStatus.PENDING:
            raise InvalidTeamStateError("Join request is not available.")
        if approve:
            config = await self.config.get_configuration(team.event_id)
            members = await self.teams.count_members(team.id)
            max_size = (config.rules or {}).get("team_size", {}).get("max") if config else None
            if max_size is not None and members >= int(max_size):
                raise TeamEligibilityError("The team has reached its maximum size.")
            user = await self.db.get(User, request.user_id)
            await self.teams.add_member(team_id=team.id, user_id=request.user_id, full_name=user.name or user.mobile_number, date_of_birth=None, is_captain=False, role=TeamMemberRole.MEMBER)
            request.status = JoinRequestStatus.APPROVED
        else:
            request.status = JoinRequestStatus.REJECTED
        request.responded_at = datetime.now(timezone.utc)
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="join_request_approved" if approve else "join_request_rejected", actor_user_id=actor.id, after_value={"user_id": str(request.user_id)})
        await self.db.commit()
        await self.db.refresh(request)
        return request

    async def remove_member(self, team_id: uuid.UUID, member_id: uuid.UUID, actor: User):
        team = await self.get_team_or_raise(team_id)
        await acquire_advisory_lock(self.db, f"team-roster:{team.id}")
        if not await self._can_manage_team(actor, team):
            raise PermissionDeniedError("You don't have permission to manage this team.")
        member = await self.db.get(TeamMember, member_id)
        if member is None or member.team_id != team.id or member.is_captain:
            raise InvalidTeamStateError("The captain cannot be removed or the member was not found.")
        await self.db.delete(member)
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="member_removed", actor_user_id=actor.id, after_value={"member_id": str(member_id)})
        await self.db.commit()
        return member

    async def leave_team(self, team_id: uuid.UUID, actor: User):
        team = await self.get_team_or_raise(team_id)
        if team.captain_user_id == actor.id:
            raise InvalidTeamStateError("The captain must cancel the team registration instead of leaving.")
        if team.registration_id is not None or team.status in {TeamStatus.SUBMITTED, TeamStatus.APPROVED}:
            raise InvalidTeamStateError("Members cannot leave after team registration submission.")
        member = await self.db.scalar(select(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == actor.id))
        if member is None:
            raise InvalidTeamStateError("You are not a member of this team.")
        await self.db.delete(member)
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="member_left", actor_user_id=actor.id)
        await self.db.commit()
        return {"status": "left"}

    async def set_member_role(self, team_id: uuid.UUID, member_id: uuid.UUID, role: TeamMemberRole, actor: User):
        team = await self.get_team_or_raise(team_id)
        if not await self._can_manage_team(actor, team) or role == TeamMemberRole.CAPTAIN:
            raise PermissionDeniedError("Only a team manager can assign non-captain roles.")
        member = await self.db.get(TeamMember, member_id)
        if member is None or member.team_id != team.id or member.is_captain:
            raise InvalidTeamStateError("The member was not found or is the captain.")
        member.role = role
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="member_role_changed", actor_user_id=actor.id, after_value={"member_id": str(member_id), "role": role.value})
        await self.db.commit()
        await self.db.refresh(member)
        return member

    async def assign_manager(self, team_id: uuid.UUID, user_id: uuid.UUID | None, actor: User):
        team = await self.get_team_or_raise(team_id)
        if not await self._can_manage_team(actor, team):
            raise PermissionDeniedError("You don't have permission to manage this team.")
        if user_id is not None and user_id not in set(await self.teams.list_member_user_ids(team.id)):
            raise InvalidTeamStateError("A team manager must be an accepted team member.")
        team.manager_user_id = user_id
        await write_audit_log(self.db, entity_type="team", entity_id=team.id, action="manager_assigned", actor_user_id=actor.id, after_value={"user_id": str(user_id) if user_id else None})
        await self.db.commit()
        await self.db.refresh(team)
        return team

    async def submit_team(self, team_id: uuid.UUID, actor: User) -> Team:
        team = await self.get_team_or_raise(team_id)
        await acquire_advisory_lock(self.db, f"team-submit:{team.id}")
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
                "user_id": member.user_id,
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

    async def list_teams_for_events(self, event_ids: set[uuid.UUID] | None) -> list[Team]:
        return await self.teams.list_for_events(event_ids)

    async def list_my_teams(self, actor: User) -> list[Team]:
        return await self.teams.list_for_user(actor.id, actor.mobile_number)

    async def list_my_invitations(self, actor: User):
        return await self.teams.list_pending_invitations_for_mobile(actor.mobile_number)

    async def page_teams(self, event_id: uuid.UUID, *, page=1, page_size=25):
        return await self.teams.page_for_event(event_id, page=page, page_size=page_size)

    async def page_teams_for_events(self, event_ids: set[uuid.UUID] | None, *, page=1, page_size=25):
        return await self.teams.page_for_events(event_ids, page=page, page_size=page_size)
