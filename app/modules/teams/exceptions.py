from app.exceptions import ConflictError, NotFoundError, ValidationError


class TeamNotFoundError(NotFoundError):
    error_code = "team_not_found"


class TeamInvitationNotFoundError(NotFoundError):
    error_code = "team_invitation_not_found"


class TeamEligibilityError(ValidationError):
    error_code = "team_eligibility_error"


class InvalidTeamStateError(ValidationError):
    error_code = "invalid_team_state"


class DuplicateTeamInvitationError(ConflictError):
    error_code = "duplicate_team_invitation"
