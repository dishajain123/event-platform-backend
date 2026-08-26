from app.exceptions import ConflictError, NotFoundError, ValidationError


class RegistrationNotFoundError(NotFoundError):
    error_code = "registration_not_found"


class DuplicateRegistrationError(ConflictError):
    error_code = "duplicate_registration"


class RegistrationCapacityExceededError(ConflictError):
    error_code = "registration_capacity_exceeded"


class InvalidRegistrationStateError(ValidationError):
    error_code = "invalid_registration_state"


class RegistrationScopeError(ValidationError):
    error_code = "registration_scope_error"
