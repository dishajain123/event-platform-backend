from app.exceptions import ConflictError, NotFoundError, ValidationError


class AssistanceRequestNotFoundError(NotFoundError):
    error_code = "assistance_request_not_found"


class AssistanceReviewerNotFoundError(NotFoundError):
    error_code = "assistance_reviewer_not_found"


class InvalidAssistanceStateError(ValidationError):
    error_code = "invalid_assistance_state"


class AssistanceConflictError(ConflictError):
    error_code = "assistance_conflict"
