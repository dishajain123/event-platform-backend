from app.exceptions import ConflictError, NotFoundError, ValidationError


class EventNotFoundError(NotFoundError):
    error_code = "event_not_found"


class InvalidEventStatusTransitionError(ValidationError):
    error_code = "invalid_event_status_transition"


class VenueNotFoundError(NotFoundError):
    error_code = "venue_not_found"


class SponsorNotFoundError(NotFoundError):
    error_code = "sponsor_not_found"


class ScheduleConflictError(ConflictError):
    error_code = "schedule_conflict"
