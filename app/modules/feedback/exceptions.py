from app.exceptions import ConflictError, NotFoundError, ValidationError


class FeedbackNotFoundError(NotFoundError):
    error_code = "feedback_not_found"


class FeedbackEventUnavailableError(ValidationError):
    error_code = "feedback_unavailable"


class FeedbackDuplicateError(ConflictError):
    error_code = "feedback_duplicate"
