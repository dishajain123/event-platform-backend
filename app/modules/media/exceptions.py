from app.exceptions import ConflictError, NotFoundError, PermissionDeniedError, ValidationError


class MediaNotFoundError(NotFoundError):
    error_code = "media_not_found"


class HighlightNotFoundError(NotFoundError):
    error_code = "highlight_not_found"


class InvalidMediaStateError(ValidationError):
    error_code = "invalid_media_state"


class MediaPermissionDeniedError(PermissionDeniedError):
    error_code = "media_permission_denied"


class MediaConflictError(ConflictError):
    error_code = "media_conflict"
