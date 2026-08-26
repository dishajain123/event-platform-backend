from app.exceptions import NotFoundError, ValidationError


class EventNotFoundError(NotFoundError):
    error_code = "event_not_found"


class InvalidEventStatusTransitionError(ValidationError):
    error_code = "invalid_event_status_transition"


class VenueNotFoundError(NotFoundError):
    error_code = "venue_not_found"