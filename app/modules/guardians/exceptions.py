from app.exceptions import ConflictError, NotFoundError, ValidationError


class ChildProfileNotFoundError(NotFoundError):
    error_code = "child_profile_not_found"


class GuardianRelationshipNotFoundError(NotFoundError):
    error_code = "guardian_relationship_not_found"


class GuardianAuthorizationError(ValidationError):
    error_code = "guardian_authorization_error"


class DuplicateGuardianRelationshipError(ConflictError):
    error_code = "duplicate_guardian_relationship"
