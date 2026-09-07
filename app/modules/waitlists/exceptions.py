from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


class WaitlistNotFoundError(NotFoundError):
    error_code = "waitlist_not_found"


class WaitlistConflictError(ConflictError):
    error_code = "waitlist_conflict"


class WaitlistPermissionError(PermissionDeniedError):
    error_code = "waitlist_permission_denied"


class WaitlistValidationError(ValidationError):
    error_code = "waitlist_invalid"
