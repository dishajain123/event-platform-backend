from app.exceptions import ConflictError, NotFoundError, ValidationError


class TicketNotFoundError(NotFoundError):
    error_code = "ticket_not_found"


class CheckInNotFoundError(NotFoundError):
    error_code = "check_in_not_found"


class InvalidTicketStateError(ValidationError):
    error_code = "invalid_ticket_state"


class DuplicateCheckInError(ConflictError):
    error_code = "duplicate_check_in"
