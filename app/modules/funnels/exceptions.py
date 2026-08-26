from app.exceptions import ConflictError, NotFoundError, ValidationError


class CompetitionStageNotFoundError(NotFoundError):
    error_code = "competition_stage_not_found"


class FunnelEntryNotFoundError(NotFoundError):
    error_code = "funnel_entry_not_found"


class InvalidFunnelStateError(ValidationError):
    error_code = "invalid_funnel_state"


class DuplicateStageError(ConflictError):
    error_code = "duplicate_stage"
