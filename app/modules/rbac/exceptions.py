from app.exceptions import ConflictError, NotFoundError, ValidationError


class RoleNotFoundError(NotFoundError):
    error_code = "role_not_found"


class AssignmentNotFoundError(NotFoundError):
    error_code = "assignment_not_found"


class ScopeRequiredError(ValidationError):
    error_code = "scope_required"


class ScopeNotAllowedError(ValidationError):
    error_code = "scope_not_allowed"


class DuplicateAssignmentError(ConflictError):
    error_code = "duplicate_assignment"